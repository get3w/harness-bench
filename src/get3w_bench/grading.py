from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Protocol

from .execution import run_process
from .models import finite


class Evaluator(Protocol):
    def evaluate(self, task: Path, workspace: Path, output: Path) -> dict: ...


def validate_grade(value: dict) -> dict:
    score = finite(value.get("score"), "score")
    if score > 1 or not isinstance(value.get("passed"), bool):
        raise ValueError("grader requires score in [0,1] and boolean passed")
    if value.get("schema_version") != 1 or not isinstance(value.get("cases"), list) or not value["cases"]:
        raise ValueError("grader receipt requires schema_version 1 and nonempty cases")
    ids = set()
    total = earned = 0.0
    gates_pass = core_pass = True
    for case in value["cases"]:
        if not case.get("id") or case["id"] in ids or not isinstance(case.get("passed"), bool):
            raise ValueError("invalid or duplicate grader case")
        ids.add(case["id"])
        weight = finite(case.get("weight"), "case weight")
        if case.get("gate") and weight:
            raise ValueError("gate weight must be zero")
        total += weight
        if case["passed"]:
            earned += weight
        if case.get("core") and not case["passed"]:
            core_pass = False
        if case.get("gate") and not case["passed"]:
            gates_pass = False
    if abs(total - 1) > 1e-8:
        raise ValueError("case weights must sum to one")
    calculated = earned if gates_pass else 0.0
    threshold = finite(value.get("pass_threshold", 0.8), "pass threshold")
    if not 0 < threshold <= 1:
        raise ValueError("invalid pass threshold")
    if abs(calculated - score) > 1e-8 or value["passed"] != (gates_pass and core_pass and calculated >= threshold):
        raise ValueError("grader score/pass inconsistent with cases")
    return value


class DockerEvaluator:
    """Trusted grader reads workspace only. No network or writable task mount.

    The configured image contains a task-family-specific grader adapter.
    It writes exactly one grade.json using the documented receipt schema.
    Upstream scoring is not replaced with guessed generic assertions.
    """
    def __init__(self, image: str, command: list[str], timeout: float = 120):
        if "@sha256:" not in image:
            raise ValueError("grader image must be pinned by digest")
        self.image, self.command, self.timeout = image, command, timeout

    def evaluate(self, task: Path, workspace: Path, output: Path) -> dict:
        import uuid
        name = "get3w-grader-" + uuid.uuid4().hex
        output.mkdir(parents=True, exist_ok=True)
        argv = ["docker", "run", "--name", name, "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "128", "--memory", "2g", "--cpus", "2", "--tmpfs", "/tmp:rw,nosuid,size=256m"]
        for source, target, readonly in ((task, "/task", True), (workspace, "/workspace", True), (output, "/grade", False)):
            argv += ["--mount", f"type=bind,src={source.resolve()},dst={target}" + (",readonly" if readonly else "")]
        argv += [self.image, *self.command]
        try:
            code, expired = run_process(argv, timeout=self.timeout, stdout=output / "stdout.log", stderr=output / "stderr.log")
        finally:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=20)
        if code or expired:
            raise RuntimeError("trusted grader failed or timed out")
        return validate_grade(json.loads((output / "grade.json").read_text()))
