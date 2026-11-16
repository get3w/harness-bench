from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from .models import TERMINALS, fingerprint, write_json


@dataclass
class Execution:
    status: str
    session_id: str | None = None
    identity: dict | None = None
    trace_complete: bool = False
    detail: str = ""


class ExecutionTarget(Protocol):
    def diagnose(self) -> dict: ...
    def execute(self, request: dict, directory: Path) -> Execution: ...
    def close(self) -> None: ...


def run_process(argv: list[str], *, timeout: float, stdout: Path, stderr: Path) -> tuple[int, bool]:
    """Start an argv without a shell; kill and reap its entire process group."""
    import signal
    with stdout.open("wb") as out, stderr.open("wb") as err:
        process = subprocess.Popen(argv, stdout=out, stderr=err, start_new_session=True)
        try:
            return process.wait(timeout=timeout), False
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
            return process.returncode, True


class NativeTarget:
    """A task image implements the Get3W original JSON run-control ABI.

    This supervisor has Docker access; the agent container never does.
    Images must be pinned, prepared offline and include the selected runtime.
    """
    def __init__(self, target: dict):
        self.target = target
        self.container: str | None = None

    def diagnose(self) -> dict:
        docker = shutil.which("docker")
        if not docker:
            return {"status": "blocked", "detail": "Docker executable missing"}
        probe = subprocess.run([docker, "info", "--format", "{{.ServerVersion}}"], capture_output=True, text=True, timeout=15)
        if probe.returncode:
            return {"status": "blocked", "detail": "Docker daemon unavailable"}
        image = subprocess.run([docker, "image", "inspect", self.target["image"]], capture_output=True, text=True, timeout=15)
        return {"status": "ready" if image.returncode == 0 else "blocked", "detail": "pinned image installed" if image.returncode == 0 else "pinned image not installed"}

    def execute(self, request: dict, directory: Path) -> Execution:
        self.container = "get3w-bench-" + uuid.uuid4().hex
        if self.target.get("environment_digest") != fingerprint(request["environment"]):
            return Execution("infrastructure_error", detail="native environment attestation missing or mismatched")
        control, trace, state, workspace = (directory / x for x in ("control", "trace", "state", "workspace"))
        for path in (control, trace, state):
            path.mkdir(exist_ok=True)
        write_json(control / "request.json", request)
        # Only this explicit proxy network can be joined; it must be internal.
        network = self.target.get("network", "none")
        if network != "none":
            info = subprocess.run(["docker", "network", "inspect", network], capture_output=True, text=True, check=True)
            if not json.loads(info.stdout)[0].get("Internal"):
                raise ValueError("agent network must be Docker internal (model access through gateway only)")
        argv = ["docker", "run", "--name", self.container, "--network", network,
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "256",
                "--memory", str(request["environment"].get("memory", "4g")), "--cpus", str(request["environment"].get("cpus", 2)),
                "--read-only", "--tmpfs", "/tmp:rw,nosuid,size=512m", "--user", f"{os.getuid()}:{os.getgid()}",
                "--workdir", "/workspace"]
        for source, destination, readonly in ((control, "/run/bench", True), (workspace, "/workspace", False), (state, "/state", False), (trace, "/trace", False)):
            argv += ["--mount", f"type=bind,src={source.resolve()},dst={destination}" + (",readonly" if readonly else "")]
        argv += ["-e", "HOME=/state", "-e", "WORKSPACE=/workspace"]
        # Container receives only a disposable gateway token, never provider credentials.
        argv += [self.target["image"], *self.target["command"]]
        try:
            code, expired = run_process(argv, timeout=request["budget"]["timeout_sec"], stdout=directory / "stdout.log", stderr=directory / "stderr.log")
        finally:
            self.close()
        if expired:
            return Execution("timeout", detail="controller deadline")
        receipt = trace / "execution.json"
        if not receipt.exists():
            return Execution("protocol_error", detail=f"missing runtime receipt; exit {code}")
        value = json.loads(receipt.read_text())
        status = value.get("status", "protocol_error")
        if status not in TERMINALS or code and status == "completed":
            status = "protocol_error"
        return Execution(status, value.get("session_id"), value.get("identity"), value.get("trace_complete") is True, value.get("detail", ""))

    def close(self) -> None:
        if self.container:
            subprocess.run(["docker", "rm", "-f", self.container], capture_output=True, timeout=20)
            self.container = None


class Get3WTarget:
    """Versioned benchmark bridge; never fall back to native execution."""
    def __init__(self, target: dict, *, transport: httpx.BaseTransport | None = None):
        headers = {}
        token = os.environ.get(target.get("token_env", "GET3W_BENCH_TOKEN"))
        if token:
            headers["Authorization"] = "Bearer " + token
        self.target = target
        self.client = httpx.Client(base_url=target["url"].rstrip("/") + "/", headers=headers, timeout=10, transport=transport, trust_env=False)
        self.session_id: str | None = None

    def call(self, method: str, path: str, **kwargs) -> dict:
        response = self.client.request(method, path, **kwargs)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Get3W bridge returned non-object response")
        return data

    def diagnose(self) -> dict:
        try:
            info = self.call("GET", "v1/info")
            if info.get("protocol_version") != 1:
                raise ValueError("unsupported bench bridge protocol")
            runtime = next((r for r in info.get("runtimes", []) if r.get("harness") == self.target["harness"]), None)
            if not runtime or not runtime.get("available"):
                return {"status": "blocked", "detail": "Harness not integrated", "info": info}
            for field in ("runtime_version", "runtime_digest"):
                if runtime.get(field) != self.target[field]:
                    raise ValueError(f"runtime {field} mismatch")
            return {"status": "ready", "info": info}
        except (httpx.HTTPError, ValueError) as error:
            return {"status": "blocked", "detail": str(error)}

    def execute(self, request: dict, directory: Path) -> Execution:
        payload = {**request, "harness": self.target["harness"], "workspace": str((directory / "workspace").resolve()), "run_directory": str(directory.resolve())}
        result = self.call("POST", "v1/sessions", json=payload)
        self.session_id = result["session_id"]
        from .models import safe_id
        safe_id(self.session_id)
        # Admission idempotency is owned by the bridge, not an automatic HTTP retry.
        self.call("POST", f"v1/sessions/{self.session_id}/turns", json={"request_id": request["trial_id"], "text": request["instruction"]})
        deadline = time.monotonic() + request["budget"]["timeout_sec"]
        cursor = None
        trace_file = directory / "trace" / "events.jsonl"
        trace_file.parent.mkdir(exist_ok=True)
        identity = result.get("identity")
        environment_digest = result.get("environment_digest")
        if environment_digest != fingerprint(request["environment"]):
            return Execution("infrastructure_error", self.session_id, None, detail="bridge environment attestation mismatch")
        while time.monotonic() < deadline:
            batch = self.call("GET", f"v1/sessions/{self.session_id}/events", params={"after": cursor or ""})
            events = batch.get("events", [])
            with trace_file.open("a") as out:
                for event in events:
                    out.write(json.dumps(event) + "\n")
            cursor = batch.get("cursor", cursor)
            state = self.call("GET", f"v1/sessions/{self.session_id}")
            if state.get("status") in TERMINALS:
                return Execution(state["status"], self.session_id, identity, state.get("trace_complete") is True)
            if state.get("status") in {"waiting_permission", "waiting_question"}:
                return Execution("blocked", self.session_id, identity, detail="unanswered human interaction; configure contract responder")
            time.sleep(0.1)
        self.call("POST", f"v1/sessions/{self.session_id}/abort", json={"clear_queue": True})
        return Execution("timeout", self.session_id, identity, detail="controller deadline")

    def close(self) -> None:
        if self.session_id:
            try:
                self.call("DELETE", f"v1/sessions/{self.session_id}")
            finally:
                self.session_id = None
                self.client.close()
        else:
            self.client.close()


def target_for(config: dict) -> ExecutionTarget:
    return NativeTarget(config) if config["backend"] == "native" else Get3WTarget(config)


def verify_runtime(expected: dict, actual: dict | None) -> bool:
    return actual is not None and all(actual.get(key) == expected.get(key) for key in ("harness", "runtime_version", "runtime_digest", "tools_fingerprint", "permissions_fingerprint", "profile_fingerprint"))


def environment_identity(config: dict) -> str:
    return fingerprint(config["environment"])
