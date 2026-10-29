"""Evaluate actual IOS evidence. Missing evidence can never become a pass."""

import json
import re
from pathlib import Path


def stdout(result):
    if not isinstance(result, dict) or result.get("failed") or result.get("unreachable"):
        return None
    lines = result.get("stdout")
    if not isinstance(lines, list) or not lines or not isinstance(lines[0], str):
        return None
    return lines[0]


def evaluate(manifest, directory, run_id):
    directory = Path(directory)
    checks = []
    for host, expected in manifest["expected"].items():
        try:
            evidence = json.loads((directory / f"{host}.json").read_text())
            if (
                evidence.get("run_id") != run_id
                or evidence.get("scenario_sha256") != manifest["scenario_sha256"]
                or evidence.get("host") != host
            ):
                evidence = {}
        except (OSError, ValueError, AttributeError):
            evidence = {}
        neighbor_text = stdout(evidence.get("neighbors"))
        found = set(
            re.findall(r"(?m)^\s*(\d+\.\d+\.\d+\.\d+)\s+\d+\s+FULL/[ \t]*\S+", neighbor_text or "")
        )
        for neighbor in expected["neighbors"]:
            state = (
                "unknown" if neighbor_text is None else "passed" if neighbor in found else "failed"
            )
            checks.append({"host": host, "check": f"OSPF FULL {neighbor}", "status": state})
        ping_record = evidence.get("pings")
        ping_results = ping_record.get("results", []) if isinstance(ping_record, dict) else []
        if not isinstance(ping_results, list):
            ping_results = []
        for target in expected["targets"]:
            matches = [p for p in ping_results if isinstance(p, dict) and p.get("item") == target]
            output = stdout(matches[0]) if len(matches) == 1 else None
            rate = re.search(r"Success rate is (\d+) percent \((\d+)/(\d+)\)", output or "")
            state = "unknown"
            if rate:
                percent, received, sent = map(int, rate.groups())
                state = "passed" if percent == 100 and received == sent == 5 else "failed"
            checks.append({"host": host, "check": f"Loopback ping {target}", "status": state})
    status = "passed" if checks and all(c["status"] == "passed" for c in checks) else "incomplete"
    if any(c["status"] == "failed" for c in checks):
        status = "failed"
    return {
        "run_id": run_id,
        "lab": manifest["lab"],
        "status": status,
        "scenario_sha256": manifest["scenario_sha256"],
        "checks": checks,
    }


def write_report(result, directory):
    directory = Path(directory)
    (directory / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    lines = [
        f"# {result['lab']} — verification",
        "",
        f"Status: **{result['status']}**",
        "",
        f"Run: `{result['run_id']}`",
        "",
        "| Router | Check | Result |",
        "|---|---|---|",
    ]
    lines.extend(f"| {c['host']} | {c['check']} | {c['status']} |" for c in result["checks"])
    lines.extend(
        [
            "",
            "This report covers observed OSPF neighbors and five-packet loopback probes.",
            "It does not establish convergence time, throughput, SLA or application health.",
        ]
    )
    (directory / "report.md").write_text("\n".join(lines) + "\n")
