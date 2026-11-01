import argparse
import getpass
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .build import bootstrap, build, check_build
from .model import load
from .report import evaluate, write_report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Prepare repeatable EVE-NG and GNS3 network labs")
    parser.add_argument("--version", action="version", version=f"Network Lab Factory {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("catalog", help="List all 24 executable scenario recipes")
    plan_parser = commands.add_parser("plan", help="Compile a catalog scenario without connecting")
    plan_parser.add_argument("case")
    plan_parser.add_argument("--name", required=True)
    plan_parser.add_argument("--mode", choices=("practice", "reference"), default="practice")
    plan_parser.add_argument("--backend", choices=("eve", "gns3"), default="eve")
    plan_parser.add_argument("--folder", default="Network-Lab-Factory")
    plan_parser.add_argument("--output", type=Path, required=True)
    deploy_parser = commands.add_parser(
        "deploy", help="Deploy a compiled plan after explicit confirmation"
    )
    deploy_parser.add_argument("plan", type=Path)
    deploy_parser.add_argument("--host", required=True)
    deploy_parser.add_argument("--user")
    deploy_parser.add_argument(
        "--guest-id", type=int, help="GNS3 guest VM through an authorized Proxmox SSH session"
    )
    deploy_parser.add_argument(
        "--auth-file",
        default="/etc/gns3/nexo-admin.json",
        help="Private GNS3 credentials file on the server; never copied locally",
    )
    deploy_parser.add_argument("--confirm", required=True, help="Exact lab name")
    deploy_parser.add_argument("--output", type=Path, required=True)
    action_parser = commands.add_parser(
        "lab-action", help="Check or change one identified workshop"
    )
    action_parser.add_argument("directory", type=Path)
    action_parser.add_argument(
        "action", choices=("check-base", "check-exercise", "fault", "restore", "stop")
    )
    action_parser.add_argument("--confirm", help="Exact lab name, required for changes")
    wizard = commands.add_parser(
        "wizard", help="Choose and prepare a catalog workshop interactively"
    )
    existing = commands.add_parser("existing", help="Prepare IPv4 addressing in an existing lab")
    existing.add_argument("--theme", choices=("dark", "light", "mono"))
    workshop = commands.add_parser("workshop", help="Reopen a deployed workshop and its consoles")
    workshop.add_argument("directory", type=Path)
    for command in (wizard, workshop):
        command.add_argument("--plain", action="store_true", help="Use linear text prompts")
        command.add_argument(
            "--theme",
            choices=("dark", "light", "mono"),
            help="Terminal interface theme (default: dark, or NO_COLOR)",
        )
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
        if args.command == "existing":
            if not sys.stdin.isatty() or not sys.stdout.isatty():
                raise ValueError("Run nlf existing in an interactive terminal.")
            from .tui import run_tui

            return run_tui(theme=args.theme, existing=True)
        if args.command == "catalog":
            from .catalog import CATALOG

            for sid, s in CATALOG.items():
                print(f"{sid}  {s['level']:<12}  {s['title']}")
            print(
                "Recipes are implemented; consult docs/catalog-validation.md for live validation."
            )
            return 0
        if args.command == "plan":
            from .catalog_render import write_bundle
            from .recipes import make_catalog_plan

            p = make_catalog_plan(
                args.case.upper(),
                args.name,
                mode=args.mode,
                folder=args.folder,
                backend=args.backend,
            )
            write_bundle(p, args.output)
            print(f"Plan ready: {args.output} ({len(p['nodes'])} nodes). Nothing deployed.")
            return 0
        if args.command == "deploy":
            from .wizard import connector_from_record, deploy_plan, gns3_transport_options
            from .workshop import validate_plan

            p = validate_plan(json.loads(args.plan.read_text()))
            if args.confirm != p["name"]:
                raise ValueError("Confirmation must match the exact lab name")
            backend = p.get("backend", "eve")
            connection = {
                "backend": backend,
                "host": args.host,
                "user": args.user or ("gns3admin" if backend == "gns3" else "root"),
                "control": os.environ.get(
                    "NLF_GNS3_SSH_CONTROL" if backend == "gns3" else "NLF_SSH_CONTROL"
                ),
            }
            if backend == "gns3":
                connection.update(gns3_transport_options())
                if args.guest_id:
                    connection.update(transport="qga", guest_id=args.guest_id)
                if connection.get("transport") == "qga" and not args.user:
                    connection["user"] = "root"
                connection["auth_file"] = args.auth_file
            c = connector_from_record(connection, batch=True)
            result = deploy_plan(c, p, args.output)
            print(f"Deployment: {result['status']}; {result['path']}")
            return 0 if result["status"] == "ready" else 1
        if args.command == "lab-action":
            from .wizard import (
                connector_from_record,
                save_json,
                session_credentials,
                update_observation,
            )
            from .workshop import validate_plan

            p = validate_plan(json.loads((args.directory / "plan.json").read_text()))
            current = args.directory / "latest-result.json"
            result = json.loads(
                (current if current.exists() else args.directory / "result.json").read_text()
            )
            connection = json.loads((args.directory / "connection.json").read_text())
            connection["control"] = os.environ.get(
                "NLF_GNS3_SSH_CONTROL"
                if connection.get("backend") == "gns3"
                else "NLF_SSH_CONTROL",
                connection.get("control"),
            )
            c = connector_from_record(connection, batch=True, **session_credentials(connection))
            checking = args.action.startswith("check-")
            if not checking and args.confirm != p["name"]:
                raise ValueError("Confirmation must match the exact lab name")
            values = {"plan": p, "ports": result.get("ports", {})}
            if checking:
                values["exercise"] = args.action == "check-exercise"
            else:
                save_json(current, update_observation(p, result, args.action))
            report = c.run("verify" if checking else args.action, **values)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S-%f")
            save_json(args.directory / f"{args.action}-{stamp}.json", report)
            save_json(
                current,
                update_observation(p, result, "verify" if checking else args.action, report),
            )
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1 if report.get("status") == "failed" else 0
        if args.command == "wizard":
            if not args.plain and sys.stdin.isatty() and sys.stdout.isatty():
                from .tui import run_tui

                return run_tui(theme=args.theme)
            from .wizard import run_wizard

            return run_wizard()
        if args.command == "workshop":
            if not args.plain and sys.stdin.isatty() and sys.stdout.isatty():
                from .tui import run_tui

                return run_tui(resume=args.directory, theme=args.theme)
            from .wizard import resume_workshop

            return resume_workshop(args.directory)
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
    except (OSError, ValueError, KeyError, TypeError, RecursionError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except (KeyboardInterrupt, EOFError):
        print("\nStopped. Any created workshop is preserved; consult its local events record.")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
