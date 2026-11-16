from __future__ import annotations

import json
import time
import uuid
import threading
import secrets

from .proxy import server
from pathlib import Path

from .execution import environment_identity, target_for, verify_runtime
from .grading import DockerEvaluator
from .models import fingerprint, public_config, validate_experiment, write_json
from .tasks import DirectorySource, verify_lock


def load_tasks(config: dict):
    source = config["source"]
    tasks = DirectorySource(Path(source["path"]), Path(source["authorization"]) if source.get("authorization") else None).tasks()
    return verify_lock(tasks, Path(config["task_lock"]))


def run(config: dict, output: Path) -> list[dict]:
    validate_experiment(config)
    if output.exists():
        raise ValueError("run directory already exists; use a new run identity")
    tasks = load_tasks(config)
    gateway_config = config.get("gateway", {})
    if not gateway_config.get("advertise_host"):
        raise ValueError("gateway.advertise_host required (reachable from isolated target)")
    grader = DockerEvaluator(config["grader"]["image"], config["grader"]["command"], config["grader"].get("timeout_sec", 120))
    output.mkdir(parents=True, mode=0o700)
    write_json(output / "config.json", public_config(config))
    results = []
    task_lock = json.loads(Path(config["task_lock"]).read_text())
    max_trials = config.get("max_trials", len(tasks) * len(config["targets"]) * config.get("repetitions", 1))
    # Persist all expected observations before any execution, including budget stops.
    for task in tasks:
        for repetition in range(config.get("repetitions", 1)):
            for target in config["targets"]:
                results.append({"schema_version": 1, "task_id": task.id, "repetition": repetition,
                    "backend": target["backend"], "target_id": target["id"],
                    "identity": {"harness": target["harness"], "suite": task_lock["suite"]},
                    "status": "blocked", "detail": "not executed", "score": None})
    write_json(output / "results.json", results)
    completed = 0
    for task in tasks:
        for repetition in range(config.get("repetitions", 1)):
            # Alternate pair order to reduce order/endpoint load bias.
            targets = config["targets"] if repetition % 2 == 0 else list(reversed(config["targets"]))
            for target_config in targets:
                if completed >= max_trials:
                    write_json(output / "budget-stop.json", {"reason": "max_trials reached", "completed": completed, "planned": len(tasks) * len(config["targets"]) * config.get("repetitions", 1)})
                    return results
                trial_id = f"{task.id}-{target_config['id']}-r{repetition}"
                directory = output / trial_id
                directory.mkdir(mode=0o700)
                task.copy_workspace(directory / "workspace")
                identity = {"model": config["model"], "budget": config["budget"], "task_digest": task.digest, "environment_digest": environment_identity(config), "harness": target_config["harness"], "runtime_version": target_config["runtime_version"], "runtime_digest": target_config["runtime_digest"], "tools_fingerprint": target_config["tools_fingerprint"], "permissions_fingerprint": target_config["permissions_fingerprint"], "profile_fingerprint": target_config["profile_fingerprint"], "suite": task_lock["suite"], "task_lock_digest": task_lock["digest"], "benchmark_kind": "integration_fixture" if task.metadata.get("grader") == "get3w-contract-v1" else "capability"}
                request = {"schema_version": 1, "trial_id": str(uuid.uuid4()), "task_id": task.id, "instruction": task.instruction, "model": config["model"], "budget": config["budget"], "environment": config["environment"], "expected_identity": {k: target_config[k] for k in ("harness", "runtime_version", "runtime_digest", "tools_fingerprint", "permissions_fingerprint", "profile_fingerprint")}}
                record = {"schema_version": 1, "trial_id": trial_id, "task_id": task.id, "category": task.category, "repetition": repetition, "target_id": target_config["id"], "backend": target_config["backend"], "identity": identity, "status": "blocked", "score": None, "passed": False, "evidence": {"identity_verified": False, "trace_complete": False, "usage_complete": False}}
                gateway = None
                gateway_thread = None
                target = target_for(target_config)
                started = time.monotonic()
                try:
                    diagnosis = target.diagnose()
                    write_json(directory / "diagnosis.json", diagnosis)
                    if diagnosis["status"] != "ready":
                        record["detail"] = diagnosis.get("detail", "target unavailable")
                    else:
                        token = secrets.token_urlsafe(32)
                        gateway = server(config, directory / "provider-trace", gateway_config.get("bind_host", "127.0.0.1"), token=token)
                        gateway_thread = threading.Thread(target=gateway.serve_forever, daemon=True)
                        gateway_thread.start()
                        request["model"] = {**config["model"], "endpoint": f"http://{gateway_config['advertise_host']}:{gateway.server_address[1]}/v1", "gateway_token": token}
                        execution = target.execute(request, directory)
                        record.update(status=execution.status, detail=execution.detail, session_id=execution.session_id)
                        verified = verify_runtime(target_config, execution.identity)
                        record["actual_identity"] = execution.identity
                        record["evidence"].update(identity_verified=verified, trace_complete=execution.trace_complete)
                        if not verified:
                            record.update(status="infrastructure_error", detail="runtime/configuration identity mismatch")
                        elif execution.status not in {"blocked", "infrastructure_error"}:
                            grade = grader.evaluate(task.root, directory / "workspace", directory / "grade")
                            record.update(score=grade["score"], passed=grade["passed"])
                            write_json(directory / "grade.json", grade)
                        # Wait for the last streaming HTTP handler to commit its evidence.
                        with gateway.recorder.request_lock:
                            pass
                        usage_file = directory / "provider-trace" / "summary.json"
                        if usage_file.exists():
                            usage = json.loads(usage_file.read_text())
                            record["usage"] = usage
                            record["evidence"]["usage_complete"] = usage.get("usage_complete") is True and usage.get("accepted_requests", 0) > 0 and usage.get("accepted_requests") == usage.get("recorded_requests")
                except Exception as error:
                    record.update(status="infrastructure_error", detail=f"{type(error).__name__}: {error}")
                finally:
                    if gateway:
                        gateway.shutdown()
                        gateway.server_close()
                        gateway_thread.join(timeout=5)
                    try:
                        target.close()
                    except Exception as error:
                        record.update(status="infrastructure_error", detail=f"cleanup failed: {type(error).__name__}")
                record["elapsed_sec"] = time.monotonic() - started
                record["record_digest"] = fingerprint(public_config(record))
                write_json(directory / "result.json", public_config(record))
                index = next(i for i, row in enumerate(results) if row["task_id"] == task.id and row["repetition"] == repetition and row["target_id"] == target_config["id"])
                results[index] = record
                completed += 1
                write_json(output / "results.json", public_config(results))
    return results
