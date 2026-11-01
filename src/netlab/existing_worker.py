"""Appended to the portable worker and addressing core; executes on the SSH server.

Only authenticated API discovery and local Telnet IOS consoles are used. Device
configuration and backup contents are never emitted in the worker event stream.
"""

# ruff: noqa: F821
# PortableAPI, NoRedirect, emit and the addressing core are injected above this file.

import contextlib
import fcntl
import http.cookiejar
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


class ExistingEveAPI:
    def __init__(self, settings):
        self.origin = settings["api_url"].rstrip("/")
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            NoRedirect(),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )
        self.request(
            "POST",
            "/auth/login",
            {"username": settings["api_user"], "password": settings["api_password"], "html5": "0"},
        )

    def request(self, method, path, data=None):
        req = urllib.request.Request(
            self.origin + "/api" + path,
            method=method,
            headers={"Content-Type": "application/json"},
            data=json.dumps(data).encode() if data is not None else None,
        )
        try:
            with self.opener.open(req, timeout=20) as response:
                body = response.read(4 * 1024 * 1024 + 1)
                if len(body) > 4 * 1024 * 1024:
                    raise ValueError("EVE response too large")
                result = json.loads(body)
        except (urllib.error.URLError, TimeoutError, ValueError):
            raise RuntimeError(
                "EVE API failed. Check credentials, API address and trusted TLS certificates."
            ) from None
        if result.get("status") != "success" or result.get("code", 500) >= 400:
            raise RuntimeError(
                "EVE API refused this operation. Check the account and lab permissions."
            )
        return result.get("data", {})


def safe_lab_path(value):
    value = "/" + value.strip("/")
    if any(part in (".", "..") for part in value.split("/")) or any(ord(c) < 32 for c in value):
        raise ValueError("Invalid lab path")
    return value


def api_lab_path(value):
    return urllib.parse.quote(safe_lab_path(value), safe="/")


def existing_list(api, backend, folder="/"):
    if backend == "gns3":
        return {
            "folders": [],
            "labs": [
                {"id": p["project_id"], "name": p["name"], "state": p["status"]}
                for p in api.request("GET", "/projects")
            ],
        }
    data = api.request("GET", "/folders" + api_lab_path(folder))
    return {
        "folders": [f["path"] for f in data.get("folders", []) if f["name"] != ".."],
        "labs": [
            {"id": p["path"], "name": p.get("file", p["path"]), "state": "existing"}
            for p in data.get("labs", [])
        ],
    }


def local_console(value, host):
    p = urllib.parse.urlsplit(value)
    if (
        p.scheme != "telnet"
        or p.hostname not in (host.lower(), "127.0.0.1", "localhost", "::1", "0.0.0.0")
        or p.username
        or p.password
        or p.path not in ("", "/")
        or p.query
        or p.fragment
    ):
        raise ValueError("Only local Telnet consoles on the SSH server are supported.")
    if not p.port or not 1 <= p.port <= 65535:
        raise ValueError("Invalid console port")
    return p.port


def existing_topology(api, settings, lab_id):
    backend, host = settings["backend"], settings["host"]
    nodes, segments = [], []
    if backend == "gns3":
        lab_id = str(uuid.UUID(lab_id))
        base = "/projects/" + lab_id
        project = api.request("GET", base)
        if project["status"] != "opened":
            raise ValueError(
                "Open this project in GNS3 first. The assistant never opens or starts it automatically."
            )
        raw_nodes = api.request("GET", base + "/nodes")
        ports = {}
        for raw in raw_nodes:
            nid = str(uuid.UUID(raw["node_id"]))
            node = {
                "id": nid,
                "name": raw["name"],
                "console": None,
                "error": None,
                "identity": {k: raw.get(k) for k in ("node_type", "template_id", "compute_id")},
            }
            node["identity"]["properties_hash"] = digest(raw.get("properties", {}))
            try:
                if (
                    raw.get("compute_id") != "local"
                    or raw.get("node_type") != "qemu"
                    or raw.get("console_type") != "telnet"
                    or raw.get("status") != "started"
                ):
                    raise ValueError("Requires a running local QEMU device with Telnet console")
                node["console"] = local_console(
                    "telnet://" + raw["console_host"] + ":" + str(raw["console"]), host
                )
            except (ValueError, KeyError):
                node["error"] = "Not a running local QEMU/Telnet device"
            for port in raw.get("ports", []):
                ports[(nid, port["adapter_number"], port["port_number"])] = port["name"]
            nodes.append(node)
        for link in api.request("GET", base + "/links"):
            endpoints, error = [], None
            for ep in link["nodes"]:
                name = ports.get(
                    (ep["node_id"], ep["adapter_number"], ep["port_number"]), "unknown"
                )
                try:
                    name = interface_name(name)
                except ValueError:
                    pass  # Require a user-confirmed mapping to an observed IOS interface.
                endpoints.append({"node": ep["node_id"], "interface": name})
            segments.append(
                {
                    "id": link["link_id"],
                    "name": " ↔ ".join(
                        next(n["name"] for n in nodes if n["id"] == e["node"])
                        + " "
                        + e["interface"]
                        for e in endpoints
                    ),
                    "endpoints": endpoints,
                    "shared": False,
                    "blocked": error,
                }
            )
        lab = {"id": lab_id, "name": project["name"], "backend": backend}
    else:
        lab_id = safe_lab_path(lab_id)
        if not lab_id.endswith(".unl"):
            raise ValueError("Select an EVE .unl laboratory")
        base = "/labs" + api_lab_path(lab_id)
        project = api.request("GET", base)
        networks = api.request("GET", base + "/networks")
        networks = networks if isinstance(networks, dict) else {}
        by_network = {}
        raw_nodes = api.request("GET", base + "/nodes")
        if not isinstance(raw_nodes, dict):
            raw_nodes = {}
        for nid, raw in raw_nodes.items():
            if not str(nid).isdigit():
                raise ValueError("Unexpected EVE node identity")
            node = {
                "id": str(nid),
                "name": raw["name"],
                "console": None,
                "error": None,
                "identity": {k: raw.get(k) for k in ("uuid", "template", "image")},
            }
            try:
                if (
                    raw.get("template") != "vios"
                    or raw.get("console") != "telnet"
                    or raw.get("status") != 2
                ):
                    raise ValueError("Requires running IOSv router")
                node["console"] = local_console(raw["url"], host)
            except (ValueError, KeyError):
                node["error"] = "Not a running IOSv router with local Telnet console"
            nodes.append(node)
            interfaces = api.request("GET", base + "/nodes/" + str(nid) + "/interfaces")
            ethernet = interfaces.get("ethernet", {})
            for ep in ethernet.values() if isinstance(ethernet, dict) else ethernet:
                if not ep.get("network_id"):
                    continue
                try:
                    name = interface_name(ep["name"])
                except ValueError:
                    name = ep["name"]
                by_network.setdefault(str(ep["network_id"]), []).append(
                    {"node": str(nid), "interface": name}
                )
        for net_id, endpoints in by_network.items():
            net = networks.get(net_id, {})
            segments.append(
                {
                    "id": net_id,
                    "name": net.get("name", "Network " + net_id),
                    "endpoints": endpoints,
                    "shared": len(endpoints) > 2,
                    "blocked": None
                    if net.get("type") == "bridge"
                    else "External, OVS or unknown network: not eligible for automatic configuration",
                }
            )
        lab = {"id": lab_id, "name": project["name"], "uuid": project["id"], "backend": backend}
    if len(nodes) > 64 or len(segments) > 256:
        raise ValueError("This preview supports at most 64 nodes and 256 segments per lab.")
    return {
        "lab": lab,
        "nodes": sorted(nodes, key=lambda n: n["id"]),
        "segments": sorted(segments, key=lambda s: s["id"]),
    }


class IOSConsole:
    def __init__(self, port, credentials):
        import pexpect

        self.child = pexpect.spawn(
            "telnet",
            ["-E", "-K", "-c", "127.0.0.1", str(port)],
            encoding="utf-8",
            codec_errors="strict",
            timeout=12,
        )
        self.prompt = r"(?m)^[A-Za-z0-9_.-]+(?:\(config[^)]*\))?[>#]\s*$"
        c = self.child
        try:
            c.send("\r")
            for _ in range(8):
                matched = c.expect(
                    [
                        self.prompt,
                        r"(?i)username:\s*$",
                        r"(?i)password:\s*$",
                        r"(?i)initial configuration dialog",
                        r"Press RETURN to get started",
                    ]
                )
                if matched == 0:
                    if "(config" in c.after:
                        raise ValueError(
                            "Console is already in configuration mode; close other sessions first."
                        )
                    if c.after.strip().endswith(">"):
                        c.sendline("enable")
                        m = c.expect([self.prompt, r"(?i)password:\s*$"])
                        if m == 1:
                            if not credentials.get("enable"):
                                raise ValueError("Enable password required")
                            c.sendline(credentials["enable"])
                            c.expect(self.prompt)
                        if not c.after.strip().endswith("#"):
                            raise ValueError("Privileged IOS access required")
                    break
                if matched == 3:
                    raise ValueError("Finish the initial IOS setup before preparing this device.")
                if matched == 4:
                    c.send("\r")
                    continue
                key = "user" if matched == 1 else "password"
                if not credentials.get(key):
                    raise ValueError("Device login credentials required")
                c.sendline(credentials[key])
            else:
                raise ValueError("Device login did not reach an IOS prompt")
            self.command("terminal length 0")
            version = self.command("show version")
            if (
                not re.search(r"Cisco IOS Software|Cisco IOS XE Software", version)
                or "IOS XR" in version
            ):
                raise ValueError("Only recognized Cisco IOS/IOS XE devices are supported")
        except ValueError:
            self.close()
            raise
        except Exception:  # noqa: BLE001 — pexpect exceptions include secret console buffers.
            self.close()
            raise RuntimeError(
                "IOS login did not complete. Check console access and device credentials."
            ) from None

    def close(self):
        self.child.close(force=True)

    def command(self, command):
        try:
            self.child.sendline(command)
            self.child.expect(self.prompt, timeout=35)
        except Exception:  # noqa: BLE001 — never serialize pexpect buffers or device configuration.
            raise RuntimeError(
                "IOS console response was not confirmed. Inspect the device before retrying."
            ) from None
        output = self.child.before.replace("\r", "")
        if re.search(r"(?mi)^\s*%.*(?:Invalid|Error|Incomplete|Ambiguous|denied|overlap)", output):
            raise ValueError("IOS rejected a command; inspect the device before retrying.")
        return output

    def read(self):
        raw = self.command("show running-config")
        start = re.search(r"(?m)^version ", raw)
        end = re.search(r"(?m)^end\s*$", raw)
        if not start or not end:
            raise ValueError("Incomplete running configuration")
        config = raw[start.start() : end.end()].strip() + "\n"
        return config, parse_ios_config(config)


def existing_observe(topology, credentials, driver=IOSConsole):
    observed = json.loads(json.dumps(topology))
    for node in observed["nodes"]:
        if node["error"]:
            continue
        try:
            with contextlib.closing(driver(node["console"], credentials)) as device:
                config, node["interfaces"] = device.read()
                node["config_hash"] = digest(config)
        except Exception:  # noqa: BLE001 — never expose console output or device secrets.
            node["error"] = (
                "Could not read a complete supported IOS configuration. Check login and console state."
            )
    return observed


def private_state():
    path = Path.home() / ".local/state/network-lab-factory/existing"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise ValueError("Private backup directory must be owned by the SSH user with mode 0700.")
    return path


def private_json(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(data, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def existing_apply(api, settings, snapshot, intent, credentials, driver=IOSConsole):
    planned = compile_addressing(snapshot, intent)
    current_topology = existing_topology(api, settings, snapshot["lab"]["id"])
    expected_topology = {
        "lab": snapshot["lab"],
        "segments": snapshot["segments"],
        "nodes": [
            {k: v for k, v in n.items() if k not in ("interfaces", "config_hash")}
            for n in snapshot["nodes"]
        ],
    }
    # Observation errors may differ from metadata errors. Any unread node blocks apply.
    if any(n.get("error") for n in snapshot["nodes"]):
        raise ValueError(
            "Application requires every lab node to be read. Remove unsupported/unreachable nodes from the lab or export only."
        )
    if digest(current_topology) != digest(expected_topology):
        raise ValueError("The lab topology or console identity changed. Read and review again.")
    root = private_state()
    lock_fd = os.open(
        root / (digest(snapshot["lab"]) + ".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(lock_fd, "w") as lock, contextlib.ExitStack() as stack:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another addressing operation is active for this lab.") from None
        devices, configs = {}, {}
        for node in snapshot["nodes"]:
            device = stack.enter_context(contextlib.closing(driver(node["console"], credentials)))
            config, interfaces = device.read()
            if digest(config) != node["config_hash"] or interfaces != node["interfaces"]:
                raise ValueError(
                    "Configuration changed on " + node["name"] + ". Read and review again."
                )
            devices[node["id"]], configs[node["id"]] = device, config
        run_id = str(uuid.uuid4())
        directory = root / run_id
        directory.mkdir(mode=0o700)
        journal = {
            "run_id": run_id,
            "lab": snapshot["lab"],
            "topology": current_topology,
            "status": "backed-up",
            "attempted": [],
            "verified": [],
            "after_hashes": {},
            "changes": planned["changes"],
        }
        for index, (nid, config) in enumerate(configs.items()):
            private_json(
                directory / f"device-{index:03d}.json", {"node": nid, "running_config": config}
            )
        private_json(directory / "journal.json", journal)
        if digest(existing_topology(api, settings, snapshot["lab"]["id"])) != digest(
            current_topology
        ):
            raise ValueError(
                "Topology changed while preparing backups. No changes applied; read again."
            )
        try:
            for nid, device in devices.items():
                changes = [c for c in planned["changes"] if c["node"] == nid]
                commands = config_commands(changes)
                if not commands:
                    continue
                journal["attempted"].append(nid)
                journal["status"] = "applying"
                private_json(directory / "journal.json", journal)
                for command_text in commands:
                    device.command(command_text)
                config, interfaces = device.read()
                if any(
                    interfaces[c["interface"]]["address"] != c["after"]
                    or interfaces[c["interface"]]["shutdown"] != c["shutdown"]
                    for c in changes
                ):
                    raise ValueError("Addressing verification failed")
                journal["verified"].append(nid)
                journal["after_hashes"][nid] = digest(config)
                private_json(directory / "journal.json", journal)
            journal["status"] = "verified"
        except Exception:  # noqa: BLE001 — partial mutations must be journaled without console secrets.
            journal["status"] = "incomplete"
        private_json(directory / "journal.json", journal)
        return {
            "status": journal["status"],
            "run_id": run_id,
            "backup_path": str(directory),
            "attempted": journal["attempted"],
            "verified": journal["verified"],
            "saved": False,
            "verification": "Configured addresses and shutdown state only; connectivity is not certified.",
        }


def _existing_save_locked(api, settings, run_id, credentials, driver=IOSConsole):
    directory = private_state() / str(uuid.UUID(run_id))
    journal = json.loads((directory / "journal.json").read_text())
    if journal["status"] != "verified":
        raise ValueError(
            "Only a fully verified, unsaved operation can be saved. Inspect partial operations manually."
        )
    if digest(existing_topology(api, settings, journal["lab"]["id"])) != digest(
        journal["topology"]
    ):
        raise ValueError("Lab topology changed since application; permanent save blocked.")
    # Read every changed node before any permanent write; never retry uncertain writes.
    with contextlib.ExitStack() as stack:
        devices = {}
        for node in journal["topology"]["nodes"]:
            if node["id"] not in journal["after_hashes"]:
                continue
            device = stack.enter_context(contextlib.closing(driver(node["console"], credentials)))
            config, _ = device.read()
            if digest(config) != journal["after_hashes"][node["id"]]:
                raise ValueError(
                    "Configuration changed after verification. Permanent save blocked."
                )
            devices[node["id"]] = device
        for nid, device in devices.items():
            startup = device.command("show startup-config")
            if (
                not re.search(r"(?m)^end\s*$", startup)
                and "startup-config is not present" not in startup
            ):
                raise ValueError("Could not back up startup configuration; permanent save blocked.")
            private_json(
                directory / ("startup-" + digest(nid)[:16] + ".json"),
                {"node": nid, "startup_config": startup},
            )
        journal["status"], journal["saved_nodes"] = "saving", []
        private_json(directory / "journal.json", journal)
        try:
            for nid, device in devices.items():
                output = device.command("write memory")
                if "[OK]" not in output:
                    raise ValueError("IOS did not acknowledge permanent save")
                journal["saved_nodes"].append(nid)
                private_json(directory / "journal.json", journal)
            journal["status"] = "saved"
        except Exception:  # noqa: BLE001 — avoid secret console diagnostics and automatic retries.
            journal["status"] = "save-incomplete"
        private_json(directory / "journal.json", journal)
    return {
        "status": journal["status"],
        "saved_nodes": journal["saved_nodes"],
        "backup_path": str(directory),
    }


def existing_save(api, settings, run_id, credentials, driver=IOSConsole):
    root = private_state()
    directory = root / str(uuid.UUID(run_id))
    if directory.is_symlink() or directory.stat().st_mode & 0o077:
        raise ValueError("Unsafe operation directory")
    journal = json.loads((directory / "journal.json").read_text())
    fd = os.open(
        root / (digest(journal["lab"]) + ".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(fd, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another addressing operation is active for this lab.") from None
        return _existing_save_locked(api, settings, run_id, credentials, driver)


def existing_main(payload):
    settings = payload["settings"]
    # Settings arrive through encrypted SSH stdin, never command-line arguments.
    p = urllib.parse.urlsplit(settings["api_url"])
    if (
        p.hostname not in (settings["host"].lower(), "127.0.0.1", "localhost", "::1")
        or p.username
        or p.password
        or p.query
        or p.fragment
        or p.path not in ("", "/")
        or p.scheme not in ("http", "https")
        or (p.scheme == "http" and p.hostname not in ("127.0.0.1", "localhost", "::1"))
    ):
        raise ValueError("Unsafe API origin")
    api = PortableAPI(settings) if settings["backend"] == "gns3" else ExistingEveAPI(settings)
    action = payload["action"]
    try:
        if action == "existing-list":
            result = existing_list(api, settings["backend"], payload.get("folder", "/"))
        elif action == "existing-read":
            result = {
                "snapshot": existing_observe(
                    existing_topology(api, settings, payload["lab_id"]), payload["credentials"]
                )
            }
        elif action == "existing-apply":
            if payload.get("confirm") != payload["snapshot"]["lab"]["name"]:
                raise ValueError("Type the exact lab name before applying.")
            result = existing_apply(
                api, settings, payload["snapshot"], payload["intent"], payload["credentials"]
            )
        elif action == "existing-save":
            if payload.get("confirm") != "SAVE":
                raise ValueError("Type SAVE to persist the verified running configuration.")
            result = existing_save(api, settings, payload["run_id"], payload["credentials"])
        else:
            raise ValueError("Unknown existing-lab action")
        emit("existing-result", **result)
    finally:
        if settings["backend"] == "eve":
            with contextlib.suppress(Exception):
                api.request("GET", "/auth/logout")


if __name__ == "__main__":
    try:
        existing_main(json.load(sys.stdin))
    except Exception as exc:  # noqa: BLE001 — exception texts here contain no API bodies or console data.
        emit("error", message=str(exc), status="incomplete")
        sys.exit(1)
