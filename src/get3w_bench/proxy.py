"""Model-boundary recorder and request/output budget enforcement.

Run on a dedicated network gateway. It forwards only a configured origin/path;
provider credentials are injected upstream and never recorded. Original raw
bodies are preserved locally; normalization is explicitly a derived view.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .models import write_json


class Recorder:
    def __init__(self, config: dict, directory: Path):
        self.config = config
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.accepted = 0
        self.transactions: list[dict] = []
        self.total_output = 0
        self.request_lock = threading.Lock()

    def admit(self, body: dict) -> int:
        with self.lock:
            if body.get("model") != self.config["model"]["id"]:
                raise ValueError("model substitution rejected")
            for parameter, expected in self.config["model"].get("parameters", {}).items():
                if body.get(parameter) != expected:
                    raise ValueError(f"model parameter mismatch: {parameter}")
            budget = self.config["budget"]
            if self.accepted >= budget["max_requests"] or self.total_output >= budget.get("total_output_tokens", float("inf")):
                raise ValueError("trial budget exhausted")
            field = "max_output_tokens" if self.config["model"]["api_format"] == "responses" else "max_tokens"
            requested = body.get(field, body.get("max_completion_tokens", budget["max_output_tokens"]))
            if not isinstance(requested, int) or isinstance(requested, bool) or not 0 < requested <= budget["max_output_tokens"]:
                raise ValueError("invalid or excessive output token budget")
            remaining = budget.get("total_output_tokens", float("inf")) - self.total_output
            if requested > remaining:
                raise ValueError("remaining output budget too small")
            if body.get("n", 1) != 1:
                raise ValueError("multiple completions are not allowed")
            self.accepted += 1
            return self.accepted

    def record(self, transaction: dict) -> None:
        with self.lock:
            self.transactions.append(transaction)
            usage = transaction.get("usage")
            if usage:
                self.total_output += usage.get("output_tokens", usage.get("completion_tokens", 0))
            with (self.directory / "transactions.jsonl").open("a") as out:
                out.write(json.dumps(transaction) + "\n")
                out.flush()
                os.fsync(out.fileno())
            complete = sum(t.get("usage") is not None and not t.get("error") and 200 <= t.get("status", 0) < 300 for t in self.transactions)
            write_json(self.directory / "summary.json", {"schema_version": 1, "accepted_requests": self.accepted, "recorded_requests": len(self.transactions), "usage_complete": complete == self.accepted and self.accepted > 0, "token_coverage": complete / self.accepted if self.accepted else 0, "output_tokens": self.total_output})


def extract_usage(data: bytes) -> dict | None:
    values = []
    try:
        values.append(json.loads(data))
    except (ValueError, UnicodeDecodeError):
        for line in data.split(b"\n"):
            if line.startswith(b"data:"):
                try:
                    values.append(json.loads(line[5:].strip()))
                except (ValueError, UnicodeDecodeError):
                    continue
    usage = {}
    for value in values:
        if not isinstance(value, dict):
            continue
        for candidate in (value.get("usage"), (value.get("response") if isinstance(value.get("response"), dict) else {}).get("usage"), (value.get("message") if isinstance(value.get("message"), dict) else {}).get("usage")):
            if isinstance(candidate, dict):
                usage.update(candidate)
    if not usage or not any(k in usage for k in ("output_tokens", "completion_tokens")) or not any(k in usage for k in ("input_tokens", "prompt_tokens")):
        return None
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for k, v in usage.items() if k in {"output_tokens", "completion_tokens", "input_tokens", "prompt_tokens"}):
        return None
    return usage


def server(config: dict, directory: Path, host: str = "127.0.0.1", port: int = 0, *, token: str | None = None) -> ThreadingHTTPServer:
    recorder = Recorder(config, directory)
    endpoint = config["model"]["endpoint"].rstrip("/")
    key = os.environ.get(config["model"].get("api_key_env", "OPENAI_API_KEY"), "")
    gateway_token = token or os.environ.get(config.get("gateway_token_env", "GET3W_GATEWAY_TOKEN"), "")
    if config["model"].get("api_key_env") and not key:
        raise ValueError("configured provider credential environment variable is missing")
    if not gateway_token:
        raise ValueError("gateway token environment variable required")

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *_args):
            pass

        def reject(self, code: int, detail: str):
            data = json.dumps({"error": detail}).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            with recorder.request_lock:
                self.handle_post()

        def handle_post(self):
            token = self.headers.get("Authorization", "").removeprefix("Bearer ") or self.headers.get("x-api-key", "")
            import hmac
            if not hmac.compare_digest(token, gateway_token):
                return self.reject(401, "invalid gateway credential")
            path = urlsplit(self.path).path
            allowed = {"chat_completions": "/chat/completions", "responses": "/responses", "anthropic_messages": "/messages"}
            suffix = allowed[config["model"]["api_format"]]
            if path not in {suffix, "/v1" + suffix} or urlsplit(self.path).query:
                return self.reject(404, "unsupported model API path")
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return self.reject(400, "invalid Content-Length")
            if length <= 0 or length > 16 * 1024 * 1024:
                return self.reject(413, "invalid body size")
            raw = self.rfile.read(length)
            try:
                body = json.loads(raw)
                sequence = recorder.admit(body)
            except (ValueError, AttributeError, TypeError) as error:
                return self.reject(400, str(error))
            if body.get("stream") and config["model"]["api_format"] == "chat_completions" and not isinstance(body.get("stream_options", {}), dict):
                recorder.record({"sequence": sequence, "status": 400, "error": "invalid stream_options", "usage": None})
                return self.reject(400, "invalid stream_options")
            budget_field = "max_output_tokens" if config["model"]["api_format"] == "responses" else "max_tokens"
            if "max_completion_tokens" not in body:
                body.setdefault(budget_field, config["budget"]["max_output_tokens"])
            encoded = json.dumps(body).encode()
            headers = {"Content-Type": "application/json"}
            if config["model"]["api_format"] == "anthropic_messages":
                headers.update({"x-api-key": key, "anthropic-version": self.headers.get("anthropic-version", "2023-06-01")})
            else:
                headers["Authorization"] = "Bearer " + key
            if body.get("stream") and config["model"]["api_format"] == "chat_completions":
                body.setdefault("stream_options", {})["include_usage"] = True
                encoded = json.dumps(body).encode()
            started = time.monotonic()
            chunks = []
            status, error = 502, None
            headers_sent = False
            received = 0
            try:
                with httpx.Client(timeout=config["budget"]["timeout_sec"], follow_redirects=False, trust_env=False) as client:
                    with client.stream("POST", endpoint + suffix, headers=headers, content=encoded) as response:
                        status = response.status_code
                        self.send_response(status)
                        headers_sent = True
                        self.send_header("Content-Type", response.headers.get("content-type", "application/json"))
                        self.end_headers()
                        for chunk in response.iter_bytes():
                            received += len(chunk)
                            if received > config.get("max_response_bytes", 64 * 1024 * 1024):
                                raise OSError("response limit exceeded")
                            chunks.append(chunk)
                            self.wfile.write(chunk)
                            self.wfile.flush()
            except (httpx.HTTPError, OSError) as exc:
                error = type(exc).__name__
                if not headers_sent:
                    self.reject(502, "upstream unavailable")
            finally:
                response_bytes = b"".join(chunks)
                transaction = {"schema_version": 1, "sequence": sequence, "request_body": raw.decode(errors="replace"), "forwarded_body": encoded.decode(), "response_body": response_bytes.decode(errors="replace"), "request_sha256": hashlib.sha256(encoded).hexdigest(), "response_sha256": hashlib.sha256(response_bytes).hexdigest(), "status": status, "elapsed_sec": time.monotonic() - started, "usage": extract_usage(response_bytes), "error": error}
                recorder.record(transaction)
                with recorder.lock, (directory / "trajectory.jsonl").open("a") as out:
                    out.write(json.dumps({"sequence": sequence, "type": "provider_transaction", "request_messages": body.get("messages", body.get("input")), "response": transaction["response_body"]}) + "\n")

    instance = ThreadingHTTPServer((host, port), Handler)
    instance.recorder = recorder
    return instance
