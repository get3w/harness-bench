from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from .compare import compare, contract_verdict
from .contracts import run_contracts
from .execution import target_for
from .models import read_config, validate_experiment
from .report import report
from .runner import run
from .tasks import DirectorySource, lock_tasks, verify_lock


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="get3w-bench")
    sub = root.add_subparsers(dest="action", required=True)
    for name in ("doctor", "run", "contract", "gateway"):
        p = sub.add_parser(name)
        p.add_argument("--config", type=Path, required=True)
        if name in {"run", "contract", "gateway"}:
            p.add_argument("--output", type=Path, required=True)
        if name == "contract":
            p.add_argument("--target", required=True)
        if name == "gateway":
            p.add_argument("--host", default="127.0.0.1")
            p.add_argument("--port", default=8789, type=int)
    p = sub.add_parser("lock")
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--authorization", type=Path)
    p.add_argument("--suite", choices=("general", "multimodal"), default="general")
    p.add_argument("--selection", choices=("smoke12", "regression60", "full"), default="smoke12")
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("compare")
    p.add_argument("inputs", nargs="+", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--mode", choices=("equivalent", "product"), default="equivalent")
    p.add_argument("--margin", type=float, default=0.02)
    p.add_argument("--contracts", type=Path)
    p = sub.add_parser("report")
    p.add_argument("input", type=Path)
    p.add_argument("--output", type=Path, required=True)
    return root


def doctor(config: dict) -> dict:
    validate_experiment(config)
    checks = []
    checks.append({"component": "docker", "status": "ready" if shutil.which("docker") else "blocked"})
    if shutil.which("docker"):
        try:
            result = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], capture_output=True, text=True, timeout=10)
            checks.append({"component": "docker-daemon", "status": "ready" if not result.returncode else "blocked"})
        except subprocess.TimeoutExpired:
            checks.append({"component": "docker-daemon", "status": "blocked"})
    try:
        source = config["source"]
        tasks = DirectorySource(Path(source["path"]), Path(source["authorization"]) if source.get("authorization") else None).tasks()
        selected = verify_lock(tasks, Path(config["task_lock"]))
        checks.append({"component": "task-source", "status": "ready", "tasks": len(selected)})
    except Exception as error:
        checks.append({"component": "task-source", "status": "blocked", "detail": str(error)})
    for target_config in config["targets"]:
        target = target_for(target_config)
        try:
            checks.append({"component": target_config["id"], **target.diagnose()})
        finally:
            target.close()
    return {"schema_version": 1, "checks": checks, "status": "ready" if all(c["status"] == "ready" for c in checks) else "blocked"}


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.action == "lock":
            if args.suite == "multimodal" and args.selection != "full":
                raise ValueError("multimodal selection must be full; do not mix modality suites")
            tasks = DirectorySource(args.source, args.authorization).tasks()
            count = {"smoke12": 2, "regression60": 10, "full": None}[args.selection]
            result = lock_tasks(tasks, args.output, args.suite, count)
            print(json.dumps({"status": "locked", "tasks": len(result["tasks"]), "digest": result["digest"]}))
        elif args.action == "doctor":
            result = doctor(read_config(args.config))
            print(json.dumps(result, indent=2))
            return 0 if result["status"] == "ready" else 2
        elif args.action == "run":
            result = run(read_config(args.config), args.output)
            print(json.dumps({"trials": len(result), "output": str(args.output)}))
            return 2 if any(r["status"] in {"blocked", "infrastructure_error"} for r in result) else 0
        elif args.action == "contract":
            config = read_config(args.config)
            target = next(t for t in config["targets"] if t["id"] == args.target and t["backend"] == "get3w")
            result = run_contracts(target, args.output)
            return 0 if contract_verdict(result) == "passed" else 2
        elif args.action == "gateway":
            from .proxy import server
            config = read_config(args.config)
            validate_experiment(config)
            instance = server(config, args.output, args.host, args.port)
            print(json.dumps({"listening": instance.server_address}), flush=True)
            try:
                instance.serve_forever()
            finally:
                instance.server_close()
        elif args.action == "compare":
            records = []
            for path in args.inputs:
                value = json.loads(path.read_text())
                records.extend(value if isinstance(value, list) else [value])
            result = compare(records, mode=args.mode, margin=args.margin)
            if args.contracts:
                rows = json.loads(args.contracts.read_text())
                result["contracts"] = rows
                harnesses = {r.get("harness") for r in rows}
                verdicts = [contract_verdict([r for r in rows if r.get("harness") == h]) for h in harnesses]
                result["contract_verdict"] = "failed" if "failed" in verdicts else "passed" if verdicts and all(v == "passed" for v in verdicts) else "blocked"
            else:
                result["contract_verdict"] = "not_run"
            required = {"opencode", "pi", "deepseek"}
            observed = {s["harness"] for s in result["summaries"] if s["suite"] == "general"}
            contract_harnesses = {row.get("harness") for row in result.get("contracts", [])}
            result["release_verdict"] = "pass" if observed == required and all(s["verdict"] == "pass" for s in result["summaries"]) and contract_harnesses == required and all(contract_verdict([r for r in result["contracts"] if r.get("harness") == h]) == "passed" for h in required) else "not_passed"
            report(result, args.output)
            return 0 if result["release_verdict"] == "pass" else 2
        elif args.action == "report":
            report(json.loads(args.input.read_text()), args.output)
        return 0
    except (ValueError, OSError, KeyError, StopIteration, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "blocked", "detail": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
