from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml

from .models import fingerprint, safe_id, write_json

CATEGORIES = ("Software Engineering", "Business Operations", "Systems Engineering", "Research and Analysis", "Web Development", "Content Production")


def tree_digest(root: Path) -> str:
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"task package must not contain symlinks: {path}")
        if path.is_file():
            entries.append((path.relative_to(root).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()))
    return fingerprint(entries)


def contained(root: Path, name: str) -> Path:
    path = root / name
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"task path escapes package: {name}")
    return path


@dataclass(frozen=True)
class Task:
    id: str
    category: str
    root: Path
    metadata: dict
    digest: str

    @property
    def instruction(self) -> str:
        return contained(self.root, self.metadata.get("prompt_file", "instruction.md")).read_text()

    @property
    def workspace(self) -> Path:
        return contained(self.root, self.metadata.get("workspace_dir", "workspace"))

    def copy_workspace(self, destination: Path) -> None:
        shutil.copytree(self.workspace, destination, symlinks=False)


class TaskSource(Protocol):
    def tasks(self) -> list[Task]: ...


class DirectorySource:
    """External upstream packages stay untouched. Access is license-gated."""
    def __init__(self, root: Path, authorization: Path | None = None, *, original: bool = False):
        self.root = root.resolve()
        self.authorization = authorization
        self.original = original

    def tasks(self) -> list[Task]:
        builtin = Path(__file__).resolve().parents[2] / "suites" / "get3w-contract-v1"
        if self.root == builtin.resolve() and (self.root / "PROVENANCE.json").exists():
            self.original = True
        if not self.original:
            if not self.authorization:
                raise ValueError("upstream authorization required; see UPSTREAM.md")
            proof = json.loads(self.authorization.read_text())
            if proof.get("status") != "approved" or not all(proof.get(x) for x in ("source", "commit", "license", "evidence", "reviewed_by")):
                raise ValueError("authorization must record approved source, commit, license, evidence, reviewed_by")
            import subprocess
            revision = subprocess.run(["git", "-C", str(self.root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
            if revision != proof["commit"]:
                raise ValueError("authorization commit does not match source checkout")
            dirty = subprocess.run(["git", "-C", str(self.root), "status", "--porcelain"], capture_output=True, text=True, check=True).stdout
            if dirty.strip():
                raise ValueError("upstream checkout must be clean")
        result = []
        seen = set()
        # Accept repository root or a suite directory; never recurse into archive copies.
        roots = [self.root / "tasks", self.root / "multimodal-tasks"] if (self.root / "tasks").is_dir() else [self.root]
        for directory in roots:
            for manifest in sorted(directory.glob("*/task.yaml")):
                data = yaml.safe_load(manifest.read_text())
                tid = safe_id(data["task_id"])
                if tid in seen:
                    raise ValueError(f"duplicate task {tid}")
                seen.add(tid)
                data["suite"] = "multimodal" if directory.name == "multimodal-tasks" else data.get("suite", "general")
                result.append(Task(tid, data.get("task_category", "Uncategorized"), manifest.parent, data, tree_digest(manifest.parent)))
        if not result:
            raise ValueError(f"no task.yaml packages under {self.root}")
        return result


def lock_tasks(tasks: list[Task], path: Path, suite: str, per_category: int | None = None) -> dict:
    selected = [t for t in tasks if t.metadata.get("suite", "general") == suite]
    if per_category:
        # Keep fixed total size when a category is scarce (general web has one).
        ordered = {c: sorted((t for t in selected if t.category == c), key=lambda t: hashlib.sha256(t.id.encode()).hexdigest()) for c in CATEGORIES}
        count = per_category * len(CATEGORIES)
        subset = [t for c in CATEGORIES for t in ordered[c][:per_category]]
        chosen = {t.id for t in subset}
        remaining = sorted((t for t in selected if t.id not in chosen), key=lambda t: hashlib.sha256(t.id.encode()).hexdigest())
        subset.extend(remaining[:max(0, count - len(subset))])
        if len(subset) != count:
            raise ValueError(f"selection requires {count} tasks; found {len(subset)}")
        selected = subset
    if not selected:
        raise ValueError("empty task selection")
    rows = [{"id": t.id, "digest": t.digest, "category": t.category} for t in sorted(selected, key=lambda t: t.id)]
    lock = {"schema_version": 1, "suite": suite, "selection": "sha256(task_id) per category, scarce-category remainder redistributed globally" if per_category else "full", "tasks": rows, "digest": fingerprint(rows)}
    write_json(path, lock)
    return lock


def verify_lock(tasks: list[Task], path: Path) -> list[Task]:
    lock = json.loads(path.read_text())
    rows = lock.get("tasks", [])
    if not rows or fingerprint(rows) != lock.get("digest"):
        raise ValueError("empty or corrupt task lock")
    indexed = {t.id: t for t in tasks}
    selected = []
    seen = set()
    for row in rows:
        task = indexed.get(row["id"])
        if row["id"] in seen or not task or task.digest != row["digest"] or task.category != row["category"] or task.metadata.get("suite", "general") != lock["suite"]:
            raise ValueError(f"task lock mismatch: {row['id']}")
        seen.add(task.id)
        selected.append(task)
    return selected
