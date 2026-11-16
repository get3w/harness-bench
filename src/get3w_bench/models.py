from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

import yaml

HARNESS_IDS = {"opencode", "pi", "deepseek"}
TERMINALS = {"completed", "timeout", "protocol_error", "model_error", "aborted", "infrastructure_error", "blocked"}


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def read_config(path: Path) -> dict:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("configuration requires schema_version: 1")
    return data


def safe_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,119}", value):
        raise ValueError(f"unsafe identifier: {value!r}")
    return value


def finite(value: Any, name: str, minimum: float = 0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < minimum:
        raise ValueError(f"{name} must be finite and >= {minimum}")
    return float(value)


def validate_experiment(config: dict) -> None:
    if config.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")
    model = config.get("model", {})
    for key in ("id", "revision", "endpoint", "api_format"):
        if not model.get(key):
            raise ValueError(f"model.{key} is required")
    if any(k in model for k in ("api_key", "token", "gateway_token")):
        raise ValueError("use api_key_env; inline model credentials are forbidden")
    if model["revision"] in ("latest", "auto"):
        raise ValueError("pin model.revision; latest/auto is not reproducible")
    if model["api_format"] not in {"chat_completions", "responses", "anthropic_messages"}:
        raise ValueError("unsupported model API format")
    if not str(model["endpoint"]).startswith(("http://", "https://")):
        raise ValueError("model.endpoint must be HTTP(S)")
    finite(config.get("budget", {}).get("timeout_sec"), "budget.timeout_sec", 0.01)
    for name in ("max_requests", "max_output_tokens"):
        value = config.get("budget", {}).get(name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"budget.{name} must be a positive integer")
    targets = config.get("targets", [])
    if not targets:
        raise ValueError("at least one target is required")
    seen = set()
    for target in targets:
        tid = safe_id(target.get("id"))
        if tid in seen:
            raise ValueError("duplicate target id")
        seen.add(tid)
        if target.get("harness") not in HARNESS_IDS or target.get("backend") not in {"native", "get3w"}:
            raise ValueError("target must name a supported harness and native/get3w backend")
        for key in ("runtime_version", "runtime_digest", "capabilities", "tools_fingerprint", "permissions_fingerprint", "profile_fingerprint"):
            if not target.get(key):
                raise ValueError(f"target {tid}: {key} required")
        if target.get("runtime_version") in ("latest", "auto"):
            raise ValueError("pin runtime_version")
        if target["backend"] == "native":
            if "@sha256:" not in target.get("image", ""):
                raise ValueError("native target image must use a digest")
            if not isinstance(target.get("command"), list) or not target["command"] or not all(isinstance(x, str) for x in target["command"]):
                raise ValueError("native command must be an argv array")
        elif not target.get("url", "").startswith(("http://", "https://")):
            raise ValueError("Get3W target requires url")
    pairs = [(t["harness"], t["backend"]) for t in targets]
    if len(set(pairs)) != len(pairs):
        raise ValueError("one target per harness/backend is allowed per experiment")
    maximum = config.get("max_trials", 1)
    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 1:
        raise ValueError("max_trials must be positive")
    if not isinstance(config.get("environment"), dict) or not config["environment"].get("image_digest"):
        raise ValueError("environment.image_digest required")
    repetitions = config.get("repetitions", 1)
    if not isinstance(repetitions, int) or isinstance(repetitions, bool) or repetitions < 1:
        raise ValueError("repetitions must be a positive integer")


def public_config(value: Any) -> Any:
    """Remove inline secrets; credential references are safe to keep."""
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if k.lower() in {"authorization", "api_key", "token", "password", "secret", "gateway_token"} else public_config(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [public_config(v) for v in value]
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)
