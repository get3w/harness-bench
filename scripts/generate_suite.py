"""Generate original, deterministic contract fixtures; never a capability leaderboard."""
import csv
import hashlib
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1] / "suites" / "get3w-contract-v1"
CATEGORIES = ("Software Engineering", "Business Operations", "Systems Engineering", "Research and Analysis", "Web Development", "Content Production")


def generate(root=ROOT):
    for index in range(60):
        category = index % 6
        seed = index // 6 + 1
        task = root / "tasks" / f"g3w-{category + 1}-{seed:02d}"
        work = task / "workspace"
        work.mkdir(parents=True, exist_ok=True)
        numbers = [seed * 3, -seed, 0, seed * 3, seed + 7]
        if category == 0:
            (work / "input.json").write_text(json.dumps(numbers))
            prompt = "Read input.json. Write result.json with an object containing sorted_unique (ascending unique integers) and sum (sum including duplicates)."
            expected = {"sorted_unique": sorted(set(numbers)), "sum": sum(numbers)}
            path, kind = "result.json", "json"
        elif category == 1:
            with (work / "sales.csv").open("w") as out:
                writer = csv.writer(out)
                writer.writerows([["region", "amount"], ["west", seed * 12], ["east", seed * 4], ["west", -seed]])
            prompt = "Read sales.csv. Sum signed amounts per region. Write totals.json as an object mapping region to integer total."
            expected = {"west": seed * 11, "east": seed * 4}
            path, kind = "totals.json", "json"
        elif category == 2:
            (work / "events.json").write_text(json.dumps([{"service": "api", "status": 500}, {"service": "api", "status": 200}] * seed + [{"service": "db", "status": 503}]))
            prompt = "Read events.json. Count only events whose status is at least 500 per service. Write errors.json mapping each affected service to its error count."
            expected = {"api": seed, "db": 1}
            path, kind = "errors.json", "json"
        elif category == 3:
            (work / "measurements.json").write_text(json.dumps(numbers))
            prompt = "Read measurements.json. Write statistics.json containing count, minimum, maximum and median (include duplicates)."
            expected = {"count": 5, "minimum": min(numbers), "maximum": max(numbers), "median": sorted(numbers)[2]}
            path, kind = "statistics.json", "json"
        elif category == 4:
            (work / "product.json").write_text(json.dumps({"title": f"Widget <{seed}>", "price": seed * 5}))
            prompt = "Read product.json. Create card.html exactly as <article><h1>TITLE</h1><p>PRICE</p></article> followed by a newline. Escape < and > in TITLE as HTML entities; PRICE is the integer without currency."
            expected = f"<article><h1>Widget &lt;{seed}&gt;</h1><p>{seed * 5}</p></article>\n"
            path, kind = "card.html", "text"
        else:
            (work / "notes.json").write_text(json.dumps({"title": f"Release {seed}", "items": ["Fix login", "Improve search"]}))
            prompt = "Read notes.json. Write release.md exactly as a Markdown level-one title, a blank line, then one '- ' bullet per item in order. End every line with newline; no extra text."
            expected = f"# Release {seed}\n\n- Fix login\n- Improve search\n"
            path, kind = "release.md", "text"
        (task / "instruction.md").write_text(prompt + "\nDo not modify the input files.\n")
        checks = [{"id": "output", "kind": kind, "path": path, "expected": expected, "weight": 0.8}]
        for source in sorted(work.iterdir()):
            checks.append({"id": "preserve-" + source.name, "kind": "text", "path": source.name, "expected": source.read_text(), "weight": 0.2})
        (task / "oracle.json").write_text(json.dumps({"checks": checks}, indent=2) + "\n")
        (task / "task.yaml").write_text(yaml.safe_dump({"task_id": task.name, "task_category": CATEGORIES[category], "prompt_file": "instruction.md", "workspace_dir": "workspace", "suite": "general", "grader": "get3w-contract-v1"}, sort_keys=False))
    digest = hashlib.sha256(b"get3w-original-contract-v1").hexdigest()
    (root / "PROVENANCE.json").write_text(json.dumps({"source": "get3w/harness-bench", "license": "MIT", "kind": "original", "generator_id": digest, "purpose": "Integration functionality fixtures, not a general capability benchmark"}, indent=2) + "\n")


if __name__ == "__main__":
    generate()
