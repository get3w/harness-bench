from __future__ import annotations

import html
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from .models import write_json


def report(value: dict, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    write_json(destination / "report.json", value)
    summaries = value.get("summaries", [])
    tests = ET.Element("testsuite", name="Get3W Harness Bench", tests=str(len(summaries)))
    rows = []
    failures = 0
    for row in summaries:
        verdict = row["verdict"]
        case = ET.SubElement(tests, "testcase", name=f"{row['harness']}/{row['suite']}")
        if verdict == "regression":
            failures += 1
            ET.SubElement(case, "failure", message="integration quality regression").text = json.dumps(row)
        elif verdict != "pass":
            ET.SubElement(case, "skipped", message=verdict)
        cells = [row.get(k) for k in ("harness", "suite", "tasks", "valid_pairs", "expected_pairs", "mean_delta", "ci95", "verdict")]
        rows.append("<tr>" + "".join("<td>" + html.escape(str(x)) + "</td>" for x in cells) + "</tr>")
    for row in value.get("contracts", []):
        case = ET.SubElement(tests, "testcase", name="contract/" + str(row.get("scenario")))
        if row.get("status") == "failed":
            failures += 1
            ET.SubElement(case, "failure", message="desktop contract failed").text = json.dumps(row)
        elif row.get("status") != "passed":
            ET.SubElement(case, "skipped", message="blocked")
    tests.set("tests", str(len(tests)))
    tests.set("failures", str(failures))
    ET.ElementTree(tests).write(destination / "junit.xml", encoding="utf-8", xml_declaration=True)
    evidence = html.escape(json.dumps(value, ensure_ascii=False, indent=2))
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'"><title>Get3W Harness Bench</title><style>body{font:15px system-ui;max-width:1200px;margin:32px auto;padding:0 20px;line-height:1.5}table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:10px;border-bottom:1px solid #888;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere} .scroll{overflow-x:auto}</style><h1>Get3W Harness Bench</h1><p>Paired quality, configuration identity and missing evidence are reported separately. No score proves universal losslessness.</p><div class="scroll"><table><thead><tr>'''
    page += "".join(f"<th>{x}</th>" for x in ("Harness", "Suite", "Tasks", "Valid pairs", "Expected pairs", "Mean Δ", "95% CI", "Verdict"))
    page += "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div><details><summary>Complete machine-readable evidence</summary><pre>" + evidence + "</pre></details></html>"
    (destination / "index.html").write_text(page)
