"""Trusted oracle for Get3W-authored deterministic fixtures, not upstream tasks."""
from __future__ import annotations

import json
from pathlib import Path

from .grading import validate_grade
from .models import write_json


def grade(task: Path, workspace: Path) -> dict:
    spec = json.loads((task / "oracle.json").read_text())
    checks = []
    for check in spec["checks"]:
        path = workspace / check["path"]
        passed = False
        try:
            if not path.resolve().is_relative_to(workspace.resolve()) or path.is_symlink():
                raise ValueError("output escapes workspace")
            actual = path.read_text()
            passed = json.loads(actual) == check["expected"] if check["kind"] == "json" else actual == check["expected"]
        except (ValueError, OSError):
            pass
        checks.append({"id": check["id"], "weight": check["weight"], "core": True, "passed": passed})
    score = sum(c["weight"] for c in checks if c["passed"])
    return validate_grade({"schema_version": 1, "score": score, "passed": all(c["passed"] for c in checks), "pass_threshold": 1, "cases": checks})


def main():
    write_json(Path("/grade/grade.json"), grade(Path("/task"), Path("/workspace")))


if __name__ == "__main__":
    main()
