from __future__ import annotations

import random
import statistics
from collections import defaultdict

from .models import finite, fingerprint

IDENTITY_FIELDS = ("model", "budget", "task_digest", "environment_digest", "harness", "runtime_version", "runtime_digest", "tools_fingerprint", "permissions_fingerprint", "profile_fingerprint", "suite", "task_lock_digest", "benchmark_kind")


def comparison_identity(record: dict) -> str:
    identity = record.get("identity", {})
    missing = [key for key in IDENTITY_FIELDS if not identity.get(key)]
    if missing:
        raise ValueError("missing comparison identity: " + ", ".join(missing))
    return fingerprint({key: identity[key] for key in IDENTITY_FIELDS})


def compare(records: list[dict], *, margin: float = 0.02, samples: int = 10_000, seed: int = 0, mode: str = "equivalent") -> dict:
    finite(margin, "margin")
    if margin > 1 or samples < 100:
        raise ValueError("margin must be <= 1 and bootstrap samples >= 100")
    if mode not in {"equivalent", "product"}:
        raise ValueError("comparison mode must be equivalent or product")
    groups = defaultdict(dict)
    issues = []
    expected = defaultdict(set)
    for record in records:
        harness = record.get("identity", {}).get("harness", "unknown")
        suite = record.get("identity", {}).get("suite", "unknown")
        key = (harness, suite, record.get("task_id"), record.get("repetition"))
        backend = record.get("backend")
        if backend not in {"native", "get3w"}:
            issues.append({"key": key, "reason": "unknown backend"})
            continue
        if backend in groups[key]:
            raise ValueError(f"duplicate observation for {key}, {backend}; select one target per backend/harness")
        groups[key][backend] = record
        expected[(harness, suite)].add((record.get("task_id"), record.get("repetition")))
    summaries = []
    differences = []
    valid = defaultdict(lambda: defaultdict(list))
    for key, pair in sorted(groups.items(), key=lambda x: str(x[0])):
        harness, suite, task, repetition = key
        if set(pair) != {"native", "get3w"}:
            issues.append({"key": key, "reason": "missing paired backend"})
            continue
        native, integrated = pair["native"], pair["get3w"]
        try:
            if comparison_identity(native) != comparison_identity(integrated):
                raise ValueError("configuration/environment/runtime identity mismatch")
            for row in pair.values():
                if row.get("status") in {"blocked", "infrastructure_error"}:
                    raise ValueError("blocked or infrastructure failure")
                evidence = row.get("evidence", {})
                if not evidence.get("identity_verified") or not evidence.get("trace_complete") or not evidence.get("usage_complete"):
                    raise ValueError("missing verified runtime identity, trace or provider usage")
            a = finite(native.get("score"), "native score")
            b = finite(integrated.get("score"), "integrated score")
            if a > 1 or b > 1:
                raise ValueError("scores must be in [0,1]")
        except (ValueError, TypeError) as error:
            issues.append({"key": key, "reason": str(error)})
            continue
        delta = b - a
        valid[(harness, suite)][task].append(delta)
        differences.append({"harness": harness, "suite": suite, "task_id": task, "repetition": repetition, "native_score": a, "get3w_score": b, "delta": delta})
    rng = random.Random(seed)
    for group in sorted(expected):
        harness, suite = group
        by_task = valid[group]
        means = [statistics.mean(values) for _, values in sorted(by_task.items())]
        group_issues = [issue for issue in issues if tuple(issue["key"][:2]) == group]
        if means:
            boot = sorted(statistics.mean(rng.choices(means, k=len(means))) for _ in range(samples))
            low, high = boot[int(0.025 * samples)], boot[min(samples - 1, int(0.975 * samples))]
            verdict = "pass" if low >= -margin - 1e-12 else "regression" if high < -margin - 1e-12 else "inconclusive"
        else:
            low = high = None
            verdict = "inconclusive"
        if len(means) < 30:
            verdict = "insufficient_evidence"
        # No silent deletion of invalid pairs, even if valid remainder is large.
        if group_issues:
            verdict = "not_comparable"
        if any(r.get("identity", {}).get("benchmark_kind") == "integration_fixture" for pair in groups.values() for r in pair.values() if r.get("identity", {}).get("harness") == harness and r.get("identity", {}).get("suite") == suite):
            verdict = "fixture_only"
        if mode == "product":
            verdict = "descriptive_only"
        summaries.append({"harness": harness, "suite": suite, "tasks": len(means), "valid_pairs": sum(map(len, by_task.values())), "expected_pairs": len(expected[group]), "mean_delta": statistics.mean(means) if means else None, "ci95": [low, high], "margin": margin, "verdict": verdict})
    native_scores = defaultdict(list)
    for record in records:
        if record.get("backend") == "native" and record.get("score") is not None and record.get("status") not in {"blocked", "infrastructure_error"}:
            try:
                score = finite(record["score"], "native score")
                if score > 1:
                    continue
                native_scores[(record["identity"].get("harness"), record["identity"].get("suite"))].append(score)
            except (ValueError, TypeError):
                continue
    baselines = [{"harness": key[0], "suite": key[1], "observations": len(values), "mean_score": statistics.mean(values), "interpretation": "descriptive native baseline; compare model/task/runtime identities before cross-harness conclusions"} for key, values in sorted(native_scores.items())]
    return {"schema_version": 1, "native_baselines": baselines, "mode": mode, "method": "task-cluster paired bootstrap; repetitions averaged within each task", "samples": samples, "seed": seed, "summaries": summaries, "differences": differences, "issues": issues}


def contract_verdict(rows: list[dict]) -> str:
    from .contracts import SCENARIOS
    if not rows or len({r.get("scenario") for r in rows}) != len(SCENARIOS) or {r.get("scenario") for r in rows} != set(SCENARIOS):
        return "blocked"
    if any(row.get("status") == "failed" for row in rows):
        return "failed"
    if any(row.get("status") != "passed" or row.get("execution_mode") != "real_desktop" or not row.get("evidence") for row in rows):
        return "blocked"
    return "passed"
