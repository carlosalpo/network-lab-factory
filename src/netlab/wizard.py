"""Interactive workshop wizard with explicit, reviewable deployment."""

import base64
import json
import os
import queue
import re
import shlex
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

from .language import english
from .workshop import ascii_preview, config_lines, lab_xml, make_plan, validate_plan


def heading(text):
    color = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    print("\n" + ("\033[1;35m" if color else "") + text + ("\033[0m" if color else ""))
    print("-" * min(76, max(40, len(text))))


def ask(label, default=None):
    value = input(f"{label}" + (f" [{default}]" if default is not None else "") + ": ").strip()
    return value or default or ""


class EveSSH:
    backend = "eve"

    def __init__(self, host, user="root", control=None, *, batch=False, cancel=None):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", host):
            raise ValueError("Invalid host name")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", user):
            raise ValueError("Invalid SSH user")
        self.host, self.user, self.control = host, user, control
        self.batch, self.cancel = batch, cancel

    def ssh_args(self):
        args = ["ssh", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=yes"]
        if self.control:
            args += ["-S", str(self.control)]
        return args + [f"{self.user}@{self.host}"]

    def connection(self):
        return {"host": self.host, "user": self.user, "control": self.control}

    def worker_source(self):
        source = Path(__file__).with_name("eve_worker.py").read_text()
        source = source.replace('if __name__ == "__main__":', "if False:")
        source += "\n" + Path(__file__).with_name("catalog_worker.py").read_text()
        return source

    def run(self, action, callback=None, **values):
        if "plan" in values:
            validate_plan(values["plan"])
            if values["plan"].get("backend", "eve") != self.backend:
                raise ValueError("The recipe belongs to another platform")
        source = self.worker_source().encode()
        code = (
            "import base64;exec(compile(base64.b64decode("
            + repr(base64.b64encode(source).decode())
            + "),'<nlf-eve-worker>','exec'))"
        )
        events = []
        args = self.ssh_args()
        if self.batch:
            args[1:1] = ["-o", "BatchMode=yes"]
        if self.cancel and self.cancel.is_set():
            raise RuntimeError(
                "Operation cancelled; review the record before creating another lab."
            )
        # A separate reader keeps cancellation responsive even while IOSv is booting.
        with tempfile.TemporaryFile(mode="w+t") as errors:
            process = subprocess.Popen(
                args + ["python3 -c " + shlex.quote(code)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=errors,
                text=True,
            )
            lines = queue.Queue()

            def read_events():
                try:
                    for line in process.stdout:
                        lines.put(line)
                finally:
                    lines.put(None)

            reader = threading.Thread(target=read_events, daemon=True)
            reader.start()
            deadline = time.monotonic() + {
                "deploy": 3600,
                "verify": 1800,
                "stop": 600,
                "fault": 120,
                "restore": 120,
            }.get(action, 45)
            try:
                process.stdin.write(json.dumps({"action": action, **values}))
                process.stdin.close()
                while True:
                    if self.cancel and self.cancel.is_set():
                        raise RuntimeError(
                            "Operation cancelled. The lab is preserved; "
                            "check its state on the server."
                        )
                    if time.monotonic() > deadline:
                        raise RuntimeError("Timed out. Check the state on the server.")
                    try:
                        line = lines.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    if line is None:
                        break
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    events.append(event)
                    if callback:
                        callback(event)
                rc = process.wait(timeout=10)
            except BaseException:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                raise
            finally:
                reader.join(timeout=1)
                process.stdout.close()
                if not process.stdin.closed:
                    process.stdin.close()
            errors.seek(0)
            diagnostic = errors.read()[-2000:].strip()
        if rc or not events:
            message = next(
                (e["message"] for e in events if e.get("event") == "error"),
                diagnostic
                or "SSH failed. Check the connection and authenticate from the terminal.",
            )
            raise RuntimeError(message)
        return events[-1]


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def connection_record(connector):
    if hasattr(connector, "connection"):
        return connector.connection()
    return {"host": connector.host, "user": connector.user, "control": connector.control}


def update_observation(plan, result, action, report=None):
    """Invalidate observations before mutations; never reuse a pre-fault green status."""
    if action == "verify":
        result[report["scope"]] = report
        result["status"] = (
            "ready"
            if result.get("preparation", {}).get("status") == "passed"
            and (plan["mode"] == "practice" or result.get("exercise", {}).get("status") == "passed")
            else "failed"
        )
    else:
        result["preparation"] = {"status": "unverified"}
        result["exercise"] = {"status": "unverified"}
        result["status"] = "stopped" if action == "stop" and report else "unverified"
    return result


def gns3_transport_options():
    vm = os.environ.get("NLF_GNS3_GUEST_ID")
    return {"transport": "qga", "guest_id": int(vm)} if vm else {}


def connector_from_record(record, **options):
    values = dict(record)
    backend = values.pop("backend", "eve")
    if backend == "gns3":
        from .gns3 import GNS3SSH

        transport = values.pop("transport", "ssh")
        if transport == "qga":
            from .gns3_qga import GNS3QGA

            return GNS3QGA(**values, **options)
        if transport != "ssh":
            raise ValueError("Unknown GNS3 transport")
        return GNS3SSH(**values, **options)
    if backend != "eve":
        raise ValueError("Unknown platform")
    return EveSSH(**values, **options)


def deploy_plan(connector, plan, out, *, callback=None, quiet=False):
    validate_plan(plan)
    # Final read-only check after confirmation, before creating remote files.
    connector.run("preflight", plan=plan)
    out.mkdir(parents=True, exist_ok=False)
    save_json(out / "plan.json", plan)
    save_json(
        out / "connection.json",
        connection_record(connector),
    )
    (out / "topology.txt").write_text(ascii_preview(plan))
    xml = lab_xml(plan)
    if plan.get("backend") == "gns3":
        from .gns3_render import native_graph

        save_json(out / "gns3-request.json", native_graph(plan))
    else:
        (out / (plan["name"] + ".unl")).write_text(xml)
    configs = {n["name"]: config_lines(plan, n) for n in plan["nodes"]}
    for name, lines in configs.items():
        (out / (name + ".cfg")).write_text("\n".join(lines) + "\n")
    events = []

    def progress(event):
        events.append(event)
        save_json(out / "events.json", events)
        if callback:
            callback(event)
        if quiet:
            return
        kind = event.get("event")
        if kind in ("created", "started", "waiting", "configured"):
            print(
                "  " + kind.capitalize() + ": " + event.get("node", event.get("path", "")),
                flush=True,
            )
        elif kind == "verified":
            print("  Preparation checks: " + event["status"], flush=True)
        elif kind == "error":
            print("  Stopped: " + event["message"], flush=True)

    try:
        result = connector.run("deploy", callback=progress, plan=plan, xml=xml, configs=configs)
    except BaseException as exc:
        save_json(
            out / "result.json",
            {"status": "incomplete", "reason": str(exc), "events_file": "events.json"},
        )
        if not quiet:
            print(f"Partial record: {out}. The remote lab is preserved; do not redeploy over it.")
        raise
    save_json(out / "result.json", result)
    # Host connection details are local convenience data, never a password or cookie.
    save_json(
        out / "connection.json",
        connection_record(connector),
    )
    return result


def practice_menu(connector, plan, result, out):
    names = [n["name"] for n in plan["nodes"]]
    while True:
        heading("Your lab")
        for i, name in enumerate(names, 1):
            print(f"  {i}  Open console {name}")
        print("  C  Check preparation\n  E  Check exercise\n  T  Topology and objective")
        if plan.get("actions"):
            print("  F  Inject fault\n  R  Restore link")
        print("  0  Exit and keep lab")
        choice = ask("Choose", "0").upper()
        if choice == "0":
            return
        try:
            if choice.isdigit() and 1 <= int(choice) <= len(names):
                if hasattr(connector, "open_console"):
                    connector.open_console(plan, names[int(choice) - 1])
                    continue
                port = int(result["ports"][names[int(choice) - 1]])
                print("To return: Ctrl+], then quit.")
                subprocess.run(
                    connector.ssh_args()[:-1]
                    + ["-tt", connector.ssh_args()[-1], "telnet -K -c 127.0.0.1 " + str(port)],
                    check=False,
                )
            elif choice in ("C", "E"):
                report = connector.run(
                    "verify", plan=plan, ports=result["ports"], exercise=choice == "E"
                )
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                save_json(out / f"check-{stamp}.json", report)
                save_json(
                    out / "latest-result.json", update_observation(plan, result, "verify", report)
                )
                print(f"{report['scope']}: {report['status']}")
            elif choice in ("F", "R") and plan.get("actions"):
                action = "fault" if choice == "F" else "restore"
                print(english(plan["actions"][0]["label"]), "· device", plan["actions"][0]["node"])
                if ask("Type the lab name to confirm") != plan["name"]:
                    continue
                save_json(out / "latest-result.json", update_observation(plan, result, action))
                report = connector.run(action, plan=plan, ports=result["ports"])
                save_json(
                    out / (action + "-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".json"),
                    report,
                )
                print(report["status"])
            elif choice == "T":
                print(ascii_preview(plan))
                print(
                    english(
                        plan.get("exercise", "Configure OSPF area 0 and advertise both loopbacks.")
                    )
                )
            else:
                print("Choose an option from the list.")
        except (RuntimeError, KeyError) as exc:
            print("Could not complete: " + str(exc))


def run_wizard():
    from .catalog import CATALOG, PROFILES
    from .recipes import make_catalog_plan

    heading("NETWORK LAB FACTORY  /  Workshop wizard")
    print("Prepare a connected, configured and labeled lab.\n")
    backend = ask("Platform: eve / gns3", "eve").lower()
    if backend not in ("eve", "gns3"):
        print("Unknown platform.")
        return 2
    host = ask(
        "SSH server", os.environ.get("NLF_GNS3_HOST" if backend == "gns3" else "NLF_EVE_HOST")
    )
    user = ask(
        "SSH user",
        ("root" if gns3_transport_options() else "gns3admin")
        if backend == "gns3"
        else os.environ.get("NLF_EVE_USER", "root"),
    )
    record = {
        "backend": backend,
        "host": host,
        "user": user,
        "control": os.environ.get(
            "NLF_GNS3_SSH_CONTROL" if backend == "gns3" else "NLF_SSH_CONTROL"
        ),
    }
    if backend == "gns3":
        record.update(gns3_transport_options())
        record["auth_file"] = os.environ.get("NLF_GNS3_AUTH_FILE", "/etc/gns3/nexo-admin.json")
    connector = connector_from_record(record)
    inv = connector.run("inventory")
    print(f"Server: {inv['profile']} · Available RAM: {inv['memory_mib']} MiB")
    while True:
        try:
            for sid, scenario in CATALOG.items():
                print(f"  {sid}  {scenario['level']:<12} {scenario['title']}")
            sid = ask("Scenario", "B01").upper()
            if sid not in CATALOG:
                raise ValueError("Choose an identifier from the catalog.")
            print(CATALOG[sid]["purpose"])
            name = ask("Name", sid.lower() + "-practice-" + datetime.now().strftime("%m%d-%H%M%S"))
            folder = ask("Lab folder", "Network-Lab-Factory")
            print("  1  Practice · configure it yourself\n  2  Reference · completed exercise")
            mode_choice = ask("Mode", "1")
            if mode_choice not in ("1", "2"):
                raise ValueError("Choose 1 or 2.")
            mode = "practice" if mode_choice == "1" else "reference"
            sample = make_catalog_plan(sid, name, backend=backend)
            images = {}
            for family in sorted({n["profile"] for n in sample["nodes"]}):
                if family == "vpcs":
                    if not inv.get("vpcs"):
                        raise ValueError("VPCS is missing on the server.")
                    continue
                options = sorted(
                    {
                        p["image"]
                        for p in PROFILES.values()
                        if p["template"] == PROFILES[family]["template"]
                        and p["image"] in inv["images"]
                    }
                )
                if not options:
                    raise ValueError("No compatible image for " + family)
                for i, image in enumerate(options, 1):
                    print(f"  {i}  {family}: {image}")
                default = (
                    options.index(PROFILES[family]["image"]) + 1
                    if PROFILES[family]["image"] in options
                    else 1
                )
                image_choice = ask("Version " + family, str(default))
                if not image_choice.isdigit() or not 1 <= int(image_choice) <= len(options):
                    raise ValueError("Choose a version from the list.")
                images[family] = options[int(image_choice) - 1]
            transit = ask(
                "Link subnet" if sid == "B01" and backend == "eve" else "Link pool",
                "10.240.0.0/30" if sid == "B01" and backend == "eve" else "10.240.0.0/16",
            )
            loops = ask("Loopback pool", "10.241.0.0/24")
            if sid == "B01" and backend == "eve":
                plan = make_plan(name, images["iosv"], transit, loops, mode, folder)
            else:
                lans = ask("LAN pool", "10.242.0.0/16")
                plan = make_catalog_plan(
                    sid,
                    name,
                    mode=mode,
                    folder=folder,
                    backend=backend,
                    images=images,
                    transit=transit,
                    loopbacks=loops,
                    lans=lans,
                )
            connector.run("preflight", plan=plan)
        except (ValueError, RuntimeError) as exc:
            print("Check: " + str(exc))
            if ask("Choose again? y/n", "y").lower() not in ("y", "yes", "s", "si", "sí"):
                return 2
            continue
        heading("Review")
        print(ascii_preview(plan))
        print(
            f"GNS3 · VM {connector.guest_id} · Proxmox access: {connector.host}"
            if hasattr(connector, "guest_id")
            else f"{'GNS3' if backend == 'gns3' else 'EVE-NG'}: {connector.host}"
        )
        print(
            f"Destination: {folder}/{name}{'.unl' if backend == 'eve' else ''} · Devices: {len(plan['nodes'])}"
        )
        print("Preparation: " + CATALOG[sid]["prepare"])
        print("Exercise: " + CATALOG[sid]["exercise"])
        decision = ask("Type DEPLOY to create, E to edit or Enter to cancel")
        if decision.upper() == "E":
            continue
        if decision != "DEPLOY":
            print("Cancelled. No lab was created.")
            return 0
        out = Path("build/workshops") / (name + "-" + plan["uuid"][:8])
        result = deploy_plan(connector, plan, out)
        heading("Result: " + result["status"])
        print(result["path"])
        print(
            "Preparation: "
            + result["preparation"]["status"]
            + " · Exercise: "
            + result["exercise"]["status"]
        )
        print("Recipe and evidence: " + str(out.resolve()))
        practice_menu(connector, plan, result, out)
        return 0 if result["status"] == "ready" else 1


def resume_workshop(path):
    plan = validate_plan(json.loads((path / "plan.json").read_text()))
    current = path / "latest-result.json"
    result = json.loads((current if current.exists() else path / "result.json").read_text())
    connection = json.loads((path / "connection.json").read_text())
    practice_menu(connector_from_record(connection), plan, result, path)
    return 0
