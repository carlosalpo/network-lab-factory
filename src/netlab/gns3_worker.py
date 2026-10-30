# ruff: noqa: F821
"""GNS3 3.0.6 Nexo-host profile, appended to the shared console worker.

API calls stay on server loopback. The remote credentials file is never copied,
printed or stored in the lab. Only newly allocated NLF projects are mutated.
"""

import urllib.error
import urllib.request
import uuid

shared_catalog_main = catalog_main
GNS3_ROOT = Path("/srv/gns3/projects")
GNS3_IMAGES = Path("/srv/gns3/images/QEMU")
GNS3_RUNTIME = Path("/opt/nexo-qemu7/bin/qemu-system-x86_64")


class GNS3API:
    def __init__(self, auth_file):
        self.token = None
        self.auth_file = Path(auth_file)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, method, path, data=None, missing=False, authenticate=True):
        if not path.startswith("/") or ".." in path or "?" in path:
            raise ValueError("Invalid API path")
        if authenticate and self.token is None:
            try:
                credentials = json.loads(self.auth_file.read_text())
                login = {"username": credentials["username"], "password": credentials["password"]}
            except (OSError, ValueError, KeyError):
                raise RuntimeError(
                    "Cannot read the private GNS3 server configuration; check its path and permissions."
                ) from None
            self.token = self.request(
                "POST", "/access/users/authenticate", login, authenticate=False
            )["access_token"]
        headers = {"Content-Type": "application/json"}
        if authenticate:
            headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(
            "http://127.0.0.1:3080/v3" + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers=headers,
            method=method,
        )
        try:
            with self.opener.open(req, timeout=120) as response:
                body = response.read(4 * 1024 * 1024)
                return json.loads(body) if body else None
        except urllib.error.HTTPError as exc:
            if missing and exc.code == 404:
                return None
            raise RuntimeError(
                f"GNS3 rejected {method} {path}: HTTP {exc.code}. No automatic retry."
            ) from None
        except (urllib.error.URLError, TimeoutError, ValueError):
            raise RuntimeError(
                f"GNS3 did not confirm {method} {path}. Check the project before repeating the operation."
            ) from None


def inventory():
    version = api.request("GET", "/version")["version"]
    if version != "3.0.6":
        raise ValueError("This profile requires GNS3 3.0.6; the server reports " + version)
    available = []
    for family, p in GNS3_PROFILES.items():
        if (
            family != "vpcs"
            and (GNS3_IMAGES / p["image"]).is_file()
            and (not p.get("bios") or (GNS3_IMAGES / p["bios"]).is_file())
        ):
            available.append(IMAGE_ALIASES[family])
    memory = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    return {
        "images": sorted(available),
        "vpcs": bool(shutil.which("vpcs")),
        "memory_mib": int(memory["MemAvailable"].split()[0]) // 1024,
        "free_gib": shutil.disk_usage(GNS3_ROOT).free // 1024**3,
        "runtime": GNS3_RUNTIME.is_file(),
        "version": version,
        "profile": "GNS3 3.0.6 · Nexo host · local API over SSH",
        "backend": "gns3",
    }


def destination(plan):
    if not re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*", plan["folder"]):
        raise ValueError("Invalid GNS3 folder")
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,47}", plan["name"]):
        raise ValueError("Invalid GNS3 name")
    path = GNS3_ROOT / plan["folder"] / plan["name"]
    if not path.resolve().is_relative_to(GNS3_ROOT.resolve()):
        raise ValueError("Destination is outside the projects directory")
    return path


def preflight(plan):
    if plan.get("schema") != 2 or plan.get("backend") != "gns3":
        raise ValueError("The recipe must be prepared for GNS3")
    inv = inventory()
    if not inv["runtime"]:
        raise ValueError("The GNS3 profile QEMU executable is missing")
    for n in plan["nodes"]:
        if n["profile"] == "vpcs":
            if not inv["vpcs"]:
                raise ValueError("VPCS is not installed")
        elif n["device"]["image"] not in inv["images"]:
            raise ValueError("Missing compatible image or BIOS: " + n["device"]["image"])
    if inv["memory_mib"] < plan["ram_mib"] + 1024 or inv["free_gib"] < max(2, len(plan["nodes"])):
        raise ValueError("Insufficient resources for this lab")
    if destination(plan).exists() or api.request("GET", "/projects/" + plan["uuid"], missing=True):
        raise ValueError(
            "The project already exists; choose another name. Nothing was overwritten."
        )
    if any(p["name"] == plan["name"] for p in api.request("GET", "/projects")):
        raise ValueError("A project with this name already exists")
    return inv


def identity(plan):
    project = api.request("GET", "/projects/" + plan["uuid"])
    if (
        project["name"] != plan["name"]
        or Path(project["path"]).resolve() != destination(plan).resolve()
    ):
        raise ValueError("The project identity changed; nothing was modified")
    return project["path"]


def current_ports(plan):
    expected = {
        str(uuid.uuid5(uuid.UUID(plan["uuid"]), n["name"])): n["name"] for n in plan["nodes"]
    }
    actual = api.request("GET", "/projects/" + plan["uuid"] + "/nodes")
    if {n["node_id"] for n in actual} != set(expected):
        raise ValueError("The project composition changed; review its nodes before continuing")
    return {expected[n["node_id"]]: n["console"] for n in actual}


def gns3_deploy(payload):
    plan = payload["plan"]
    preflight(plan)
    graph = payload["graph"]
    project = api.request(
        "POST",
        "/projects",
        {
            "project_id": plan["uuid"],
            "name": plan["name"],
            "path": str(destination(plan)),
            "auto_close": False,
            "auto_open": False,
        },
    )
    emit("created", path=project["path"], project_id=plan["uuid"])
    base = "/projects/" + plan["uuid"]
    api.request("POST", base + "/open")
    for node in graph["nodes"]:
        api.request("POST", base + "/nodes", node)
    for link in graph["links"]:
        api.request("POST", base + "/links", link)
    for drawing in graph["drawings"]:
        api.request("POST", base + "/drawings", drawing)
    api.request("POST", base + "/nodes/start")
    ports = current_ports(plan)
    for name, port in ports.items():
        emit("started", node=name, port=port)
    finish_deployment(payload, ports, project["path"])


def gns3_main(payload):
    global api
    api = GNS3API(payload.get("auth_file", "/etc/gns3/nexo-admin.json"))
    action = payload["action"]
    plan = payload.get("plan", {})
    if action == "inventory":
        emit("inventory", **inventory())
    elif action == "preflight":
        emit("preflight", **preflight(plan))
    elif action == "deploy":
        gns3_deploy(payload)
    elif action == "stop":
        path = identity(plan)
        current_ports(plan)
        api.request("POST", "/projects/" + plan["uuid"] + "/nodes/stop")
        deadline = time.monotonic() + 30
        while True:
            nodes = api.request("GET", "/projects/" + plan["uuid"] + "/nodes")
            if all(node["status"] == "stopped" for node in nodes):
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("GNS3 did not confirm that the entire project stopped")
            time.sleep(1)
        emit("stopped", path=path, status="stopped")
    elif action in ("verify", "fault", "restore"):
        identity(plan)
        payload["ports"] = current_ports(plan)
        shared_catalog_main(payload)
    else:
        raise ValueError("Unknown GNS3 operation")


if __name__ == "__main__":
    try:
        gns3_main(json.load(sys.stdin))
    except Exception as exc:  # noqa: BLE001 — report partial state across the worker protocol.
        emit("error", message=str(exc), status="incomplete")
        sys.exit(1)
