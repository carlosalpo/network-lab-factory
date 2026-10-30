"""Opt-in live validation: create isolated QA labs, collect evidence, stop own nodes."""

import argparse
from datetime import datetime
from pathlib import Path

from netlab.catalog import CATALOG
from netlab.recipes import make_catalog_plan
from netlab.wizard import connector_from_record, deploy_plan, save_json

p = argparse.ArgumentParser()
p.add_argument("cases", nargs="+", choices=list(CATALOG))
p.add_argument("--host", required=True)
p.add_argument("--control", required=True)
p.add_argument("--backend", choices=["eve", "gns3"], default="eve")
p.add_argument("--guest-id", type=int)
p.add_argument("--mode", choices=["practice", "reference"], default="reference")
p.add_argument("--output", type=Path, required=True)
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=False)
record = {"host": a.host, "user": "root", "control": a.control, "backend": a.backend}
if a.guest_id:
    if a.backend != "gns3":
        p.error("--guest-id requires --backend gns3")
    record.update(transport="qga", guest_id=a.guest_id)
c = connector_from_record(record, batch=True)
stamp = datetime.now().strftime("%m%d%H%M%S")
summary = []
for case in a.cases:
    plan = make_catalog_plan(
        case,
        "nlf-qa-" + case.lower() + "-" + stamp,
        backend=a.backend,
        mode=a.mode,
        folder="Network-Lab-Factory/Catalog-QA",
    )
    out = a.output / case.lower()
    print("BEGIN", case, flush=True)
    events = []
    try:
        result = deploy_plan(c, plan, out, callback=events.append)
        summary.append({"scenario": case, "status": result["status"], "directory": str(out)})
    except Exception as exc:  # noqa: BLE001 — QA records failures and always cleans up its own nodes.
        summary.append(
            {"scenario": case, "status": "incomplete", "reason": str(exc), "directory": str(out)}
        )
        print("FAILED", case, str(exc)[:300], flush=True)
    finally:
        if any(e.get("event") == "created" for e in events):
            try:
                save_json(out / "stopped.json", c.run("stop", plan=plan))
            except Exception as exc:  # noqa: BLE001 — QA records failures and always cleans up its own nodes.
                save_json(a.output / "summary.json", summary)
                raise RuntimeError(
                    "Could not stop QA nodes; stop validation to preserve capacity"
                ) from exc
    save_json(a.output / "summary.json", summary)
    print("END", case, summary[-1]["status"], flush=True)
