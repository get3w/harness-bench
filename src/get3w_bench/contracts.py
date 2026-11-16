from __future__ import annotations

from pathlib import Path

from .execution import Get3WTarget
from .models import write_json

SCENARIOS = ("selection_binding", "stream_final_consistency", "abort_clear_queue", "permission_deny", "question_cancel", "resume_after_restart", "concurrent_isolation", "attachment_roundtrip", "mcp_tool_result", "browser_stop", "computer_takeover")


def run_contracts(target_config: dict, directory: Path, scenarios: tuple[str, ...] = SCENARIOS) -> list[dict]:
    """The external bridge must execute scenarios against an isolated real app.

    Missing scenarios are blocked. No simulator can produce a desktop pass.
    """
    directory.mkdir(parents=True, exist_ok=True)
    target = Get3WTarget(target_config)
    rows = []
    try:
        diagnosis = target.diagnose()
        if diagnosis["status"] != "ready":
            rows = [{"scenario": name, "status": "blocked", "detail": diagnosis.get("detail")} for name in scenarios]
        else:
            for name in scenarios:
                try:
                    result = target.call("POST", "v1/contracts", json={"scenario": name, "harness": target_config["harness"]})
                    if result.get("scenario") != name or result.get("status") not in {"passed", "failed", "blocked"}:
                        raise ValueError("invalid contract response")
                    if result["status"] == "passed" and (not result.get("evidence") or result.get("execution_mode") != "real_desktop"):
                        raise ValueError("desktop pass requires real_desktop evidence")
                    result["harness"] = target_config["harness"]
                    rows.append(result)
                except Exception as error:
                    rows.append({"scenario": name, "status": "blocked", "detail": str(error)})
    finally:
        target.close()
    write_json(directory / "contracts.json", rows)
    return rows
