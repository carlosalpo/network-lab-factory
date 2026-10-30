"""Small EVE admin-profile worker, sent over authenticated SSH; no stored credentials.

Only a fresh B01 lab in tenant 0 is deployed. Does not change host networking.
The caller supplies this source and a validated plan over SSH stdin.
"""

import json
import os
import pwd
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path


def emit(kind, **values):
    print(json.dumps({"event": kind, **values}), flush=True)


def inventory():
    import pexpect  # noqa: F401 - preflight dependency

    images = [
        p.name
        for p in Path("/opt/unetlab/addons/qemu").glob("vios-*")
        if (p / "virtioa.qcow2").is_file()
    ]
    memory = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    return {
        "images": sorted(images),
        "memory_mib": int(memory["MemAvailable"].split()[0]) // 1024,
        "free_gib": shutil.disk_usage("/opt/unetlab/labs").free // (1024**3),
        "profile": "EVE admin tenant 0 via SSH",
        "version": Path("/opt/unetlab/html/VERSION").read_text().strip()[:80],
    }


def destination(plan):
    root = Path("/opt/unetlab/labs").resolve()
    folder = plan["folder"]
    if not re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*", folder):
        raise ValueError("Invalid lab folder")
    name = plan["name"]
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,47}", name):
        raise ValueError("Invalid lab name")
    path = root / folder / (name + ".unl")
    if not path.resolve().is_relative_to(root):
        raise ValueError("Lab destination escapes the allowed root")
    return path


def preflight(plan):
    inv = inventory()
    if plan["image"] not in inv["images"]:
        raise ValueError("Selected image is no longer installed")
    if inv["memory_mib"] < 1536 or inv["free_gib"] < 2:
        raise ValueError("Insufficient available resources for two IOSv routers plus headroom")
    if destination(plan).exists():
        raise ValueError("Lab already exists. Choose another name; nothing was overwritten.")
    if not Path("/opt/unetlab/wrappers/unl_wrapper").is_file():
        raise ValueError("EVE wrapper is unavailable")
    return inv


def console(port, boot=False):
    import pexpect

    child = pexpect.spawn(
        "telnet",
        ["-E", "-K", "-c", "127.0.0.1", str(port)],
        encoding="utf-8",
        codec_errors="replace",
        timeout=8,
    )
    deadline = time.monotonic() + (480 if boot else 40)
    prompt = r"(?m)^[\r ]*[A-Za-z0-9_-]+(?:\(config[^)]*\))?[>#]\s*$"
    child.send("\r")
    while time.monotonic() < deadline:
        match = child.expect(
            [
                prompt,
                r"initial configuration dialog\?\s*\[yes/no\]:",
                r"Press RETURN to get started",
                r"terminate autoinstall\?\s*\[yes\]:",
                pexpect.TIMEOUT,
                pexpect.EOF,
            ]
        )
        if match == 0:
            return child
        if match in (1, 3) and not boot:
            child.close()
            raise RuntimeError("Node is not prepared; no configuration was applied")
        if match == 1:
            child.send("no\r")
        elif match == 3:
            child.send("yes\r")
        elif match == 5:
            child.close()
            raise RuntimeError("Console disconnected")
        else:
            child.send("\r")
    child.close()
    raise RuntimeError("Router did not become ready within the boot deadline")


def command(child, text, timeout=90):
    import pexpect

    # Console reconnection can leave multiple prompts queued after Return.
    # Discard them before issuing a command so each result belongs to that command.
    drain_deadline = time.monotonic() + 1
    while time.monotonic() < drain_deadline:
        try:
            child.read_nonblocking(4096, timeout=0.1)
        except pexpect.TIMEOUT:
            break
    child.send(text + "\r")
    child.expect(r"(?m)^[\r ]*[A-Za-z0-9_-]+(?:\(config[^)]*\))?[>#]\s*$", timeout=timeout)
    out = child.before
    # CSR's asynchronous Day-0 app notice can arrive after an unrelated command echo.
    # It is not a CLI rejection; retain it in evidence but exclude only this exact notice.
    errors = re.sub(r"% Error: The application: day0guestshell, does not exist", "", out)
    if re.search(
        r"% (?:Invalid|Incomplete command|Ambiguous command|Error)|%Error", errors, re.IGNORECASE
    ):
        raise RuntimeError("IOS rejected command: " + text + "\n" + out[-400:])
    return out


def verify(plan, ports, exercise=False):
    results = []
    for n, peer in zip(plan["nodes"], reversed(plan["nodes"])):
        child = console(ports[n["name"]])
        try:
            command(child, "enable")
            command(child, "terminal length 0")
            interfaces = command(child, "show ip interface brief")
            good = all(
                re.search(rf"(?m)^{interface}\s+{re.escape(ip)}\s+.*\bup\s+up\s*$", interfaces)
                for interface, ip in [("GigabitEthernet0/1", n["ip"]), ("Loopback0", n["loopback"])]
            )
            target = peer["loopback"] if exercise else peer["ip"]
            neighbors = ""
            deadline = time.monotonic() + 90
            passed = False
            while time.monotonic() < deadline:
                if exercise:
                    neighbors = command(child, "show ip ospf neighbor")
                ping = command(child, f"ping {target} repeat 5 timeout 1")
                neighbor_ok = not exercise or bool(
                    re.search(rf"(?m)^{re.escape(peer['loopback'])}\s+\d+\s+FULL[/\w-]*", neighbors)
                )
                passed = bool(good and "Success rate is 100 percent (5/5)" in ping and neighbor_ok)
                if passed:
                    break
                time.sleep(3)
            results.append(
                {
                    "node": n["name"],
                    "passed": passed,
                    "interfaces": interfaces,
                    "ping": ping,
                    "neighbors": neighbors,
                }
            )
        finally:
            child.close()
    return {
        "status": "passed" if all(r["passed"] for r in results) else "failed",
        "scope": "exercise" if exercise else "preparation",
        "checks": results,
    }


def deploy(payload):
    plan = payload["plan"]
    preflight(plan)
    path = destination(plan)
    xml = payload["xml"]
    tree = ET.fromstring(xml)
    if tree.get("id") != plan["uuid"] or tree.get("name") != plan["name"]:
        raise ValueError("Lab identity mismatch")
    owner = pwd.getpwnam("www-data")
    # New user-requested folder only; existing ancestor ownership is untouched.
    missing = []
    parent = path.parent
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for folder in reversed(missing):
        folder.mkdir()
        os.chown(folder, owner.pw_uid, owner.pw_gid)
        os.chmod(folder, 0o775)
    with path.open("x", encoding="utf-8") as file:
        file.write(xml)
    os.chown(path, owner.pw_uid, owner.pw_gid)
    os.chmod(path, 0o664)
    emit("created", path=str(path))
    ports = {}
    for n in plan["nodes"]:
        run = subprocess.run(
            [
                "/opt/unetlab/wrappers/unl_wrapper",
                "-a",
                "start",
                "-T",
                "0",
                "-F",
                str(path),
                "-D",
                str(n["id"]),
                "-U",
                "admin",
            ],
            check=False,
            text=True,
            capture_output=True,
            timeout=120,
        )
        match = re.search(
            r"will start node\s+\d+\s+\d+\s+\d+\s+\d+\s+(\d+)", run.stdout + run.stderr
        )
        if run.returncode or not match:
            raise RuntimeError(f"Could not start {n['name']}; the created lab is preserved")
        ports[n["name"]] = int(match[1])
        emit("started", node=n["name"], port=ports[n["name"]])
    for n in plan["nodes"]:
        emit("waiting", node=n["name"])
        child = console(ports[n["name"]], boot=True)
        try:
            for line in payload["configs"][n["name"]]:
                command(child, line)
        finally:
            child.close()
        emit("configured", node=n["name"])
    prep = verify(plan, ports)
    emit("verified", **prep)
    exercise = verify(plan, ports, True) if plan["mode"] == "reference" else {"status": "pending"}
    emit(
        "result",
        path=str(path),
        ports=ports,
        preparation=prep,
        exercise=exercise,
        status="ready"
        if prep["status"] == "passed" and exercise["status"] in ("pending", "passed")
        else "failed",
    )


def main(payload):
    action = payload["action"]
    if action == "inventory":
        emit("inventory", **inventory())
    elif action == "preflight":
        emit("preflight", **preflight(payload["plan"]))
    elif action == "deploy":
        deploy(payload)
    elif action == "verify":
        path = destination(payload["plan"])
        if ET.parse(path).getroot().get("id") != payload["plan"]["uuid"]:
            raise ValueError("Deployment identity no longer matches")
        emit("verification", **verify(payload["plan"], payload["ports"], payload["exercise"]))
    else:
        raise ValueError("Unsupported worker operation")


if __name__ == "__main__":
    try:
        main(json.load(sys.stdin))
    except Exception as exc:  # noqa: BLE001 - remote protocol must report partial failure
        emit("error", message=str(exc), status="incomplete")
        sys.exit(1)
