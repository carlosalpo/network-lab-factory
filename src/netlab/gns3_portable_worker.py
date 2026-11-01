# ruff: noqa: F821
"""Appended remote worker: API v2/v3, existing local templates, no Nexo paths."""

import base64
import hashlib
import shlex
import ssl
from urllib.parse import urlsplit


class APIError(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__(
            f"GNS3 API returned HTTP {status}. Check access and permissions; no mutation was retried."
        )


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise APIError(code)


class PortableAPI:
    def __init__(self, settings):
        self.origin = settings.get("api_url", "http://127.0.0.1:3080").rstrip("/")
        p = urlsplit(self.origin)
        if (
            p.scheme not in ("http", "https")
            or not p.hostname
            or p.username
            or p.password
            or p.query
            or p.fragment
            or p.path
            or (p.scheme == "http" and p.hostname not in ("127.0.0.1", "localhost", "::1"))
        ):
            raise ValueError("Unsafe API address. Use loopback HTTP inside SSH or verified HTTPS.")
        self.user = settings.get("api_user", "")
        self.password = settings.get("api_password") or ""
        self.token = None
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            NoRedirect(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )
        self.version = settings.get("api_version", "auto")
        if self.version == "auto":
            # Probe without sending credentials; only a definite 404 permits v2 fallback.
            self.version = "3"
            try:
                self.request("GET", "/version", authenticate=False)
            except APIError as exc:
                if exc.status == 404:
                    self.version = "2"
                elif exc.status != 401:
                    raise
        if self.version not in ("2", "3"):
            raise ValueError("Unsupported GNS3 API version")
        version = self.request("GET", "/version")["version"]
        if not re.match(r"^(2\.2\.|3\.)", version) or version.split(".")[0] != self.version:
            raise ValueError(
                "Supported server families are GNS3 2.2 and 3.x; capabilities must also pass."
            )
        self.server_version = version

    def request(self, method, path, data=None, missing=False, authenticate=True):
        if not path.startswith("/") or ".." in path or "?" in path:
            raise ValueError("Invalid API request path")
        headers = {"Content-Type": "application/json"}
        if authenticate and self.version == "3" and not self.token:
            if not self.user or not self.password:
                raise ValueError("Enter the GNS3 API username and password in Server settings.")
            self.token = self.request(
                "POST",
                "/access/users/authenticate",
                {"username": self.user, "password": self.password},
                authenticate=False,
            )["access_token"]
        if authenticate and self.version == "3":
            headers["Authorization"] = "Bearer " + self.token
        elif authenticate and self.user:
            headers["Authorization"] = (
                "Basic " + base64.b64encode((self.user + ":" + self.password).encode()).decode()
            )
        req = urllib.request.Request(
            self.origin + "/v" + self.version + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers=headers,
            method=method,
        )
        try:
            with self.opener.open(req, timeout=120) as response:
                body = response.read(4 * 1024 * 1024 + 1)
                if len(body) > 4 * 1024 * 1024:
                    raise ValueError("API response too large")
                return json.loads(body) if body else None
        except urllib.error.HTTPError as exc:
            if missing and method == "GET" and exc.code == 404:
                return None
            raise APIError(exc.code) from None
        except (urllib.error.URLError, TimeoutError, ValueError):
            raise RuntimeError(
                "GNS3 response could not be verified. Check the API address, TLS certificate and server state before retrying."
            ) from None


# Only documented node properties are copied; never serialize account metadata.
QEMU_PROPERTIES = {
    "hda_disk_image",
    "hda_disk_interface",
    "hdb_disk_image",
    "hdb_disk_interface",
    "hdc_disk_image",
    "hdc_disk_interface",
    "hdd_disk_image",
    "hdd_disk_interface",
    "cdrom_image",
    "bios_image",
    "ram",
    "cpus",
    "adapters",
    "adapter_type",
    "platform",
    "qemu_path",
    "boot_priority",
    "linked_clone",
    "options",
    "cpu_throttling",
    "process_priority",
    "mac_address",
    "replicate_network_connection",
    "on_close",
    "kernel_image",
    "initrd",
    "kernel_command_line",
    "legacy_networking",
}


def checked_template(t):
    uuid.UUID(t["template_id"])
    if t.get("template_type") not in ("qemu", "vpcs") or t.get("compute_id") not in (None, "local"):
        raise ValueError("Choose a QEMU or VPCS template on the local compute of this SSH server.")
    if t.get("custom_adapters"):
        raise ValueError(
            "Templates with custom adapter overrides need a separate validated profile."
        )
    if t.get("console_type", "telnet") != "telnet":
        raise ValueError("The selected template needs a Telnet console, carried inside SSH.")
    result = {k: t[k] for k in ("template_id", "name", "template_type")}
    result["properties"] = {k: v for k, v in t.items() if k in QEMU_PROPERTIES and v is not None}
    if t["template_type"] == "qemu":
        p = result["properties"]
        if not p.get("hda_disk_image") or not isinstance(p.get("ram"), int) or p["ram"] < 1:
            raise ValueError("QEMU templates need a disk image and RAM allocation.")
        if not isinstance(p.get("adapters"), int) or p["adapters"] < 1:
            raise ValueError("QEMU templates need network adapters.")
        if p.get("linked_clone") is False:
            raise ValueError(
                "Use a template with linked clones to preserve the original disk image."
            )
        if not isinstance(p.get("cpus", 1), int) or p.get("cpus", 1) < 1:
            raise ValueError("QEMU templates need a positive CPU allocation.")
        options = shlex.split(p.get("options", ""))
        forbidden = (
            "-net",
            "-netdev",
            "-nic",
            "-device",
            "-chardev",
            "-serial",
            "-monitor",
            "-qmp",
            "-readconfig",
        )
        if any(option.split("=", 1)[0] in forbidden for option in options):
            raise ValueError(
                "Template options must not add network devices, external console endpoints or include files."
            )
        p["linked_clone"] = True
    return result


def fingerprint(t):
    return hashlib.sha256(json.dumps(t, sort_keys=True).encode()).hexdigest()


def inventory():
    import pexpect  # noqa: F401 — required for configuration and observed checks.

    if not shutil.which("telnet"):
        raise ValueError("Install a Telnet client on the SSH server for private console access.")
    computes = api.request("GET", "/computes")
    if not any(c.get("compute_id") == "local" and c.get("connected", True) for c in computes):
        raise ValueError("This connector requires a connected local compute on the SSH server.")
    templates = []
    for summary in api.request("GET", "/templates"):
        if summary.get("template_type") not in ("qemu", "vpcs"):
            continue
        try:
            uuid.UUID(summary["template_id"])
            t = checked_template(api.request("GET", "/templates/" + summary["template_id"]))
        except (ValueError, KeyError):
            continue
        templates.append(t)
    root = portable.get("projects_path")
    if not root:
        try:
            settings = api.request("GET", "/settings", missing=True)
        except APIError as exc:
            if exc.status != 403:
                raise
            settings = None
        root = ((settings or {}).get("Server") or {}).get("projects_path")
    if (
        not root
        or not Path(root).is_absolute()
        or ".." in Path(root).parts
        or not Path(root).is_dir()
    ):
        raise ValueError(
            "Enter the existing GNS3 projects directory in Server settings (as seen on the SSH server)."
        )
    global GNS3_ROOT
    GNS3_ROOT = Path(root).resolve()
    memory = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    return {
        "backend": "gns3",
        "portable": True,
        "version": api.server_version,
        "api_version": api.version,
        "profile": "GNS3 " + api.server_version + " · local templates over SSH",
        "projects_path": str(GNS3_ROOT),
        "templates": templates,
        "images": [],
        "vpcs": any(t["template_type"] == "vpcs" for t in templates),
        "memory_mib": int(memory["MemAvailable"].split()[0]) // 1024,
        "free_gib": shutil.disk_usage(GNS3_ROOT).free // 1024**3,
        "runtime": True,
    }


def bound_graph(plan, inv, graph):
    by_id = {t["template_id"]: t for t in inv["templates"]}
    bindings, fingerprints, ram = portable.get("template_map", {}), {}, 0
    images = None
    for n, rendered in zip(plan["nodes"], graph["nodes"], strict=True):
        t = by_id.get(bindings.get(n["profile"]))
        if not t:
            raise ValueError("Choose an installed template for " + n["profile"])
        expected = "vpcs" if n["profile"] == "vpcs" else "qemu"
        if t["template_type"] != expected:
            raise ValueError("Wrong emulator for " + n["profile"])
        digest = fingerprint(t)
        previous = portable.get("template_fingerprints", {}).get(n["profile"])
        if previous and previous != digest:
            raise ValueError(
                "A selected template changed after review. Reconnect and review before creating."
            )
        fingerprints[n["profile"]] = digest
        props = dict(t["properties"]) if expected == "qemu" else {}
        if expected == "qemu":
            needed = 1 + max(
                (
                    i["port"]
                    for net in plan["networks"]
                    for i in net["endpoints"]
                    if i["node"] == n["name"]
                ),
                default=0,
            )
            if props["adapters"] < needed:
                raise ValueError(
                    "Template "
                    + t["name"]
                    + " needs at least "
                    + str(needed)
                    + " adapters for "
                    + n["name"]
                )
            # Query controller proxy so image locations and QEMU binaries are server-owned.
            if images is None:
                images = {i["filename"] for i in api.request("GET", "/computes/local/qemu/images")}
            for key in (
                "hda_disk_image",
                "hdb_disk_image",
                "hdc_disk_image",
                "hdd_disk_image",
                "bios_image",
                "cdrom_image",
            ):
                if props.get(key) and props[key] not in images:
                    raise ValueError(
                        "A selected template image is unavailable: " + key + " in " + t["name"]
                    )
            ram += props["ram"]
        else:
            ram += 32
        rendered["properties"] = props
        rendered["compute_id"] = "local"
    return graph, fingerprints, ram


def preflight(plan):
    if plan.get("schema") != 2 or plan.get("backend") != "gns3":
        raise ValueError("A GNS3 catalog recipe is required")
    inv = inventory()
    graph, fingerprints, ram = bound_graph(plan, inv, portable["graph"])
    if inv["memory_mib"] < ram + 1024 or inv["free_gib"] < max(2, len(plan["nodes"])):
        raise ValueError("Insufficient free resources for the selected templates.")
    if destination(plan).exists() or api.request("GET", "/projects/" + plan["uuid"], missing=True):
        raise ValueError("The project already exists. Nothing was overwritten.")
    if any(p["name"] == plan["name"] for p in api.request("GET", "/projects")):
        raise ValueError("A project with this name already exists.")
    return dict(inv, graph=graph, template_fingerprints=fingerprints, required_ram_mib=ram)


legacy_ports = current_ports


def current_ports(plan):
    nodes = api.request("GET", "/projects/" + plan["uuid"] + "/nodes")
    for n in nodes:
        if (
            n.get("compute_id") != "local"
            or n.get("console_type") != "telnet"
            or n.get("console_host") not in ("127.0.0.1", "localhost", "0.0.0.0", "::", "::1")
            or type(n.get("console")) is not int
            or not 1 <= n["console"] <= 65535
        ):
            raise ValueError("Console endpoints do not match the supported local SSH topology.")
    return legacy_ports(plan)


def portable_main(payload):
    global api, portable, GNS3_ROOT
    portable = payload["portable"]
    api = PortableAPI(portable)
    root = portable.get("projects_path")
    if root:
        GNS3_ROOT = Path(root)
    action, plan = payload["action"], payload.get("plan", {})
    if action == "inventory":
        emit("inventory", **inventory())
        return
    if action in ("preflight", "deploy"):
        portable["graph"] = payload["graph"]
        checked = preflight(plan)
        if action == "preflight":
            emit("preflight", **checked)
            return
        # Use the rechecked template graph; the caller cannot supply emulator properties.
        payload["graph"] = checked["graph"]
        # Existing deployment code performs another read-only preflight before creation.
        gns3_deploy(payload)
    elif action in ("verify", "fault", "restore"):
        identity(plan)
        payload["ports"] = current_ports(plan)
        shared_catalog_main(payload)
    elif action == "stop":
        path = identity(plan)
        current_ports(plan)
        api.request("POST", "/projects/" + plan["uuid"] + "/nodes/stop")
        deadline = time.monotonic() + 30
        while True:
            nodes = api.request("GET", "/projects/" + plan["uuid"] + "/nodes")
            if all(n["status"] == "stopped" for n in nodes):
                break
            if time.monotonic() > deadline:
                raise RuntimeError("GNS3 did not confirm that all owned nodes stopped.")
            time.sleep(1)
        emit("stopped", path=path, status="stopped")
    else:
        raise ValueError("Unknown portable GNS3 operation")


if __name__ == "__main__":
    try:
        portable_main(json.load(sys.stdin))
    except Exception as exc:  # noqa: BLE001 — never include HTTP response bodies or credentials.
        emit("error", message=str(exc), status="incomplete")
        sys.exit(1)
