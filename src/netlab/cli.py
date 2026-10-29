import argparse
import getpass
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .build import bootstrap, build, check_build
from .model import load
from .report import evaluate, write_report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build repeatable EVE-NG + Ansible labs")
    parser.add_argument("--version", action="version", version="Network Lab Factory 0.1.0")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Validate a scenario without network access")
    validate.add_argument("scenario", type=Path)
    render = commands.add_parser("build", help="Generate a new EVE lab and inventory")
    render.add_argument("scenario", type=Path)
    render.add_argument("--output", type=Path, required=True)
    boot = commands.add_parser("bootstrap", help="Write private, local console snippets")
    boot.add_argument("scenario", type=Path)
    boot.add_argument("--output", type=Path, default=Path("secrets/bootstrap"))
    verify = commands.add_parser("verify", help="Collect live evidence with Ansible and report")
    verify.add_argument("build_dir", type=Path)
    verify.add_argument("--playbook", type=Path, default=Path("ansible/verify.yml"))
    verify.add_argument("--reports", type=Path, default=Path("reports"))
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            data = load(args.scenario)
            print(
                f"Valid: {data['name']} ({len(data['nodes'])} routers, {len(data['links'])} links)"
            )
        elif args.command == "build":
            out = build(load(args.scenario), args.output)
            print(f"Built {out}: EVE-NG lab, inventory, routing configs and integrity manifest")
        elif args.command == "bootstrap":
            username = os.environ.get("LAB_USERNAME") or input("Lab username: ").strip()
            password = os.environ.get("LAB_PASSWORD") or getpass.getpass("Lab password: ")
            out = bootstrap(load(args.scenario), username, password, args.output)
            print(f"Private console snippets written to {out}. Do not commit or share them.")
        elif args.command == "verify":
            manifest = check_build(args.build_dir)
            playbook = args.playbook.resolve(strict=True)
            if not os.environ.get("LAB_USERNAME") or not os.environ.get("LAB_PASSWORD"):
                raise ValueError("Set LAB_USERNAME and LAB_PASSWORD before verification")
            run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
            out = args.reports.resolve() / run_id
            out.mkdir(parents=True, mode=0o700)
            variables = {
                "report_dir": str(out),
                "run_id": run_id,
                "scenario_sha256": manifest["scenario_sha256"],
            }
            try:
                completed = subprocess.run(
                    [
                        "ansible-playbook",
                        "-i",
                        str(args.build_dir.resolve() / "inventory.yml"),
                        str(playbook),
                        "--extra-vars",
                        json.dumps(variables),
                    ],
                    check=False,
                )
                returncode = completed.returncode
            except OSError:
                returncode = 127
            result = evaluate(manifest, out, run_id)
            result["ansible_exit_code"] = returncode
            if returncode != 0 and result["status"] == "passed":
                result["status"] = "incomplete"
            write_report(result, out)
            print(f"Verification: {result['status']}. Report: {out / 'report.md'}")
            return 0 if result["status"] == "passed" else 1
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
