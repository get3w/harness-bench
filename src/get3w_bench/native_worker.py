"""Original run-control entrypoint to bake into pinned runtime images.

Image builders must provide /opt/bench-runtime.json containing the immutable
runtime identity and version command. The controller never trusts exit zero
alone. This module is run inside a container, not on the host.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import re
from pathlib import Path

from .models import write_json


def command_for(harness: str, executable: str, model: str, prompt: str, runtime: dict) -> list[str]:
    if harness == "opencode":
        return [executable, "run", "--format", "json", "--model", model, "--", prompt]
    if harness == "pi":
        return [executable, "--mode", "json", "--model", model, "--no-approve", "--session-dir", "/state/sessions", "--", prompt]
    if harness == "deepseek":
        # Model/provider routes live in a version-pinned Cordis overlay.
        return [executable, "--profile", "headless", "--patch", runtime["patch"], "--json", "--approval-policy", "never", "--", prompt]
    raise ValueError("unsupported harness")


def terminal_status(harness: str, records: list[dict], code: int) -> str:
    if code:
        return "model_error" if any(r.get("type") == "error" for r in records) else "protocol_error"
    if harness == "pi":
        settled = [r for r in records if r.get("type") == "agent_settled"]
        if not settled:
            return "protocol_error"
        return "aborted" if settled[-1].get("aborted") else "completed"
    if harness == "deepseek":
        final = [r for r in records if r.get("type") == "final"]
        return "completed" if final and (final[-1].get("reason") or {}).get("kind") == "completed" else "protocol_error"
    if any(r.get("type") == "error" for r in records):
        return "model_error"
    return "completed" if any(r.get("type") == "step_finish" for r in records) else "protocol_error"


def main() -> int:
    request = json.loads(Path("/run/bench/request.json").read_text())
    runtime = json.loads(Path("/opt/bench-runtime.json").read_text())
    harness = runtime["identity"]["harness"]
    executable = runtime["executable"]
    version = subprocess.run([executable, "--version"], capture_output=True, text=True, check=True).stdout.strip()
    if runtime["identity"]["runtime_version"] not in re.findall(r"(?<![\w.])\d+\.\d+\.\d+(?:[-+][\w.-]+)?(?![\w.])", version):
        raise ValueError("installed runtime version does not match image receipt")
    if runtime["model_id"] != request["model"]["id"] or runtime["model_revision"] != request["model"]["revision"]:
        raise ValueError("model does not match prepared runtime configuration")
    env = {**os.environ, "HOME": "/state", "PI_CODING_AGENT_DIR": "/state/pi", "DSH_HOME": "/state/dsh", "WORKSPACE": "/workspace"}
    substitutions = {"endpoint": request["model"]["endpoint"], "token": request["model"]["gateway_token"], "model": request["model"]["id"]}
    for name, template in runtime.get("environment", {}).items():
        env[name] = template.format(**substitutions)
    for entry in runtime.get("config_files", []):
        destination = Path(entry["path"])
        if not destination.resolve().is_relative_to(Path("/state")):
            raise ValueError("runtime config must be under /state")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(entry["template"].replace("$ENDPOINT", substitutions["endpoint"]).replace("$TOKEN", substitutions["token"]))
    # Model-specific configuration is prepared by the trusted image recipe.
    # The request cannot name an executable or change the pinned identity.
    argv = command_for(harness, executable, runtime["model_selector"], request["instruction"], runtime)
    records = []
    malformed = False
    with Path("/trace/native.jsonl").open("w") as out:
        process = subprocess.Popen(argv, cwd="/workspace", env=env, stdout=subprocess.PIPE, text=True)
        assert process.stdout is not None
        for line in process.stdout:
            out.write(line)
            out.flush()
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    malformed = True
                else:
                    records.append(record)
                    # Terminal parsing needs only recent events, raw evidence stays on disk.
                    if len(records) > 10000:
                        del records[:5000]
            except json.JSONDecodeError:
                malformed = True
        code = process.wait()
    status = "protocol_error" if malformed else terminal_status(harness, records, code)
    write_json(Path("/trace/execution.json"), {"schema_version": 1, "status": status, "identity": runtime["identity"], "trace_complete": not malformed and bool(records), "session_id": next((r.get("sessionId") or r.get("session", {}).get("sessionId") for r in records if r.get("sessionId") or isinstance(r.get("session"), dict)), None)})
    return 0 if status == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
