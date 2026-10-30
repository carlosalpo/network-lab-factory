# ruff: noqa: F821
# This source is appended to eve_worker.py and uses its protocol and imports.
"""Appended to the legacy worker for schema-2 deployment; standard-library transport.

All mutations target the newly created lab identity, never host networking.
"""

from concurrent.futures import ThreadPoolExecutor

legacy_preflight = preflight
legacy_deploy = deploy
legacy_verify = verify
legacy_main = main
legacy_console = console
legacy_command = command
PROMPT = r"(?m)^[\r ]*[A-Za-z0-9_.-]+(?:\[\d+\])?(?:\([^\r\n]*\))?[>#]\s*$"
LAB_PASSWORD = "Nlf-Workshop!2026"


def nxos_boot_image(output, node):
    suffix = {
        "nxosv9k-9300v-9.3.9": ".9.3.9.bin",
        "nxosv9k-9300v-10.5.3.F": ".10.5.3.F.bin",
    }.get(node["device"]["image"])
    candidates = set(re.findall(r"\bnxos[A-Za-z0-9_.-]*\.bin\b", output))
    candidates = {name for name in candidates if suffix and name.endswith(suffix)}
    if len(candidates) != 1:
        raise RuntimeError(
            "No se identificó una única imagen de arranque compatible en " + node["name"]
        )
    return candidates.pop()


def inventory():
    images = []
    for p in Path("/opt/unetlab/addons/qemu").iterdir():
        if p.is_dir() and any(p.glob("*.qcow2")):
            images.append(p.name)
    memory = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    return {
        "images": sorted(images),
        "vpcs": Path("/opt/vpcsu/bin/vpcs").is_file(),
        "memory_mib": int(memory["MemAvailable"].split()[0]) // 1024,
        "free_gib": shutil.disk_usage("/opt/unetlab/labs").free // 1024**3,
        "profile": "EVE admin tenant 0 via SSH",
        "version": Path("/opt/unetlab/html/VERSION").read_text().strip()[:80],
    }


def preflight(plan):
    if plan.get("schema") != 2:
        return legacy_preflight(plan)
    inv = inventory()
    for n in plan["nodes"]:
        p = n["device"]
        if p["console"] == "vpcs":
            if not inv["vpcs"]:
                raise ValueError("VPCS no está instalado")
        elif p["image"] not in inv["images"]:
            raise ValueError("Falta la imagen " + p["image"])
        elif not (Path("/opt/unetlab/addons/qemu") / p["image"] / p["disk"]).is_file():
            raise ValueError("Falta el disco esperado para " + p["image"])
    if inv["memory_mib"] < plan["ram_mib"] + 1024 or inv["free_gib"] < max(2, len(plan["nodes"])):
        raise ValueError(
            f"Recursos insuficientes: {plan['ram_mib'] + 1024} MiB y {max(2, len(plan['nodes']))} GiB libres requeridos"
        )
    if destination(plan).exists():
        raise ValueError("El laboratorio ya existe; elegí otro nombre.")
    return inv


def node_console(node, port, boot=False):
    import pexpect

    if node["device"]["console"] == "ios":
        return legacy_console(port, boot)
    child = pexpect.spawn(
        "telnet",
        ["-E", "-K", "-c", "127.0.0.1", str(port)],
        encoding="utf-8",
        codec_errors="replace",
        timeout=5,
    )
    child.nlf_boot = boot
    deadline = time.monotonic() + (900 if boot else 60)
    patterns = [
        PROMPT,
        r"(?i)enforce secure password standard[^\r\n]*:",
        r"(?i)Enter the password for.*admin.*:",
        r"(?i)Confirm.*password.*:",
        r"(?i)(?:basic configuration dialog|enter.*configuration dialog)[^\r\n]*:",
        r"(?i)(?:login|username):\s*$",
        r"(?i)password:\s*$",
        r"(?i)Would you like to enable.*anonymous.*reporting.*",
        pexpect.TIMEOUT,
        pexpect.EOF,
        r"(?i)Abort Power On Auto Provisioning[^\r\n]*:",
        r"(?m)^[\r ]*loader\s*>",
    ]
    child.send("\r")
    boot_attempted = False
    while time.monotonic() < deadline:
        match = child.expect(patterns)
        if match == 0:
            return child
        if match == 11:
            if not boot or node["device"]["console"] != "nxos" or boot_attempted:
                child.close()
                raise RuntimeError("El equipo quedó en el cargador de arranque: " + node["name"])
            child.send("dir\r")
            child.expect(patterns[11], timeout=30)
            image = nxos_boot_image(child.before, node)
            child.send("boot " + image + "\r")
            boot_attempted = True
            continue
        if match in (1, 2, 3, 4, 7, 10) and not boot:
            child.close()
            raise RuntimeError("El equipo requiere configuración inicial; no se cambió nada.")
        if match in (1, 4, 7):
            child.send("no\r")
        elif match in (2, 3):
            child.send(LAB_PASSWORD + "\r")
        elif match == 5:
            child.send("admin\r")
        elif match == 6:
            child.send(
                (LAB_PASSWORD if node["device"]["console"] in ("nxos", "asa") else "") + "\r"
            )
        elif match == 10:
            child.send("yes\r")
        elif match == 9:
            child.close()
            raise RuntimeError("Consola desconectada: " + node["name"])
        else:
            child.send("\r")
    child.close()
    raise RuntimeError("Tiempo de arranque agotado: " + node["name"])


def node_command(child, text, dialect, timeout=90):
    # ASA rejects `enable` when a reconnected console is already privileged.
    if (
        dialect == "asa"
        and text == "enable"
        and re.fullmatch(r"[\r\n ]*[A-Za-z0-9_.-]+#\s*", str(getattr(child, "after", "")))
    ):
        return ""
    if dialect == "ios":
        return legacy_command(child, text, timeout)
    import pexpect

    # A reconnect can queue an extra prompt. It must not complete the next command.
    drain_deadline = time.monotonic() + 1
    while time.monotonic() < drain_deadline:
        try:
            child.read_nonblocking(4096, timeout=0.1)
        except pexpect.TIMEOUT:
            break
    child.send(text + "\r")
    output = ""
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("Tiempo agotado esperando el comando: " + text)
        match = child.expect(
            [
                PROMPT,
                r"(?i)password:\s*$",
                r"Destination filename.*\?",
                r"\[confirm\]",
                r"--More--",
                pexpect.EOF,
                r"(?i)(?:enter[^\r\n]*new|repeat|confirm)[^\r\n]*password:\s*$",
            ],
            timeout=remaining,
        )
        output += child.before
        if match == 0:
            break
        if match == 1:
            child.send((LAB_PASSWORD if dialect == "asa" else "") + "\r")
        elif match in (2, 3):
            child.send("\r")
        elif match == 4:
            child.send(" ")
        elif (
            match == 6
            and dialect == "asa"
            and text == "enable"
            and getattr(child, "nlf_boot", False)
        ):
            child.send(LAB_PASSWORD + "\r")
        else:
            raise RuntimeError("La consola se desconectó")
    if re.search(
        r"%\s*(?:Invalid|Incomplete|Ambiguous|Error)|ERROR:|Invalid command|Bad command|Invalid address",
        output,
        re.I,
    ):
        raise RuntimeError("Comando rechazado: " + text + "\n" + output[-400:])
    return output


def reply_sequences(output):
    ipv4 = re.findall(r"bytes from[^\r\n]*?(?:icmp_seq[= ]|seq=)(\d+)", output, re.I)
    ipv6 = re.findall(r"(?m)^[\r ]*[0-9a-fA-F:%._]+\s+icmp6_seq=(\d+)\s+ttl=\d+\s+time=", output)
    return set(ipv4 + ipv6)


def evaluate_check(check, output):
    if re.search(r"%\s*(?:Invalid|Incomplete|Ambiguous|Error)|ERROR:|Bad command", output, re.I):
        return False
    kind = check["kind"]
    if kind == "regex":
        return bool(re.search(check["pattern"], output, re.M))
    if kind == "ping":
        return (
            bool(
                re.search(
                    r"Success rate is 100 percent|(?<![\d.])0(?:\.0+)?% packet loss|3 packets received",
                    output,
                    re.I,
                )
            )
            or len(reply_sequences(output)) >= 3
        )
    if kind == "unreachable":
        # No replies and explicit failure. Command syntax errors never count as isolation.
        success = re.search(
            r"bytes from|Success rate is [1-9]|\b[1-9]\d* packets received", output, re.I
        )
        failure = re.search(
            r"Success rate is 0 percent|100(?:\.0+)?% packet loss|not reachable|timeout|unreachable|administratively prohibited",
            output,
            re.I,
        )
        return bool(failure and not success and not reply_sequences(output))
    raise ValueError("Unknown check kind")


def verify(plan, ports, exercise=False):
    if plan.get("schema") != 2:
        return legacy_verify(plan, ports, exercise)
    scope = "exercise" if exercise else "preparation"
    results = []
    nodes = {n["name"]: n for n in plan["nodes"]}
    # Preserve probe ordering: positive control probes precede isolation probes and counters.
    sessions = {}
    try:
        for c in plan["checks"][scope]:
            n = nodes[c["node"]]
            dialect = n["device"]["console"]
            if n["name"] not in sessions:
                child = node_console(n, ports[n["name"]])
                sessions[n["name"]] = child
                if dialect in ("ios", "asa"):
                    node_command(child, "enable", dialect)
                if dialect != "vpcs":
                    node_command(
                        child,
                        "terminal pager 0" if dialect == "asa" else "terminal length 0",
                        dialect,
                    )
            child = sessions[n["name"]]
            passed = False
            output = ""
            # A new OSPF adjacency may still be electing a DR or exchanging its
            # database after 30 seconds, especially on virtual routers.
            budget = 120 if "ospf neighbor" in c["command"] else (50 if exercise else 90)
            deadline = time.monotonic() + budget
            while True:
                output = node_command(child, c["command"], dialect)
                passed = evaluate_check(c, output)
                if passed or time.monotonic() >= deadline:
                    break
                time.sleep(3)
            results.append(dict(**c, passed=passed, output=output))
            emit("check", node=n["name"], label=c["label"], passed=passed, scope=scope)
    finally:
        for child in sessions.values():
            child.close()
    result = {
        "status": "passed" if results and all(c["passed"] for c in results) else "failed",
        "scope": scope,
        "checks": results,
    }
    if plan.get("comparison_groups"):
        result["versions"] = {
            g: all(c["passed"] for c in results if c["node"] in names)
            for g, names in plan["comparison_groups"].items()
        }
    return result


def identity(plan):
    path = destination(plan)
    if ET.parse(path).getroot().get("id") != plan["uuid"]:
        raise ValueError("La identidad del laboratorio cambió; no se modificó nada.")
    return path


def catalog_deploy(payload):
    plan = payload["plan"]
    preflight(plan)
    path = destination(plan)
    tree = ET.fromstring(payload["xml"])
    if tree.get("id") != plan["uuid"] or tree.get("name") != plan["name"]:
        raise ValueError("Lab identity mismatch")
    owner = pwd.getpwnam("www-data")
    missing = []
    parent = path.parent
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for folder in reversed(missing):
        folder.mkdir()
        os.chown(folder, owner.pw_uid, owner.pw_gid)
        os.chmod(folder, 0o775)
    with path.open("x") as f:
        f.write(payload["xml"])
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
            capture_output=True,
            text=True,
            timeout=120,
        )
        match = re.search(
            r"will start node\s+\d+\s+\d+\s+\d+\s+\d+\s+(\d+)", run.stdout + run.stderr
        )
        if run.returncode or not match:
            raise RuntimeError("No inició " + n["name"] + "; laboratorio conservado")
        ports[n["name"]] = int(match[1])
        emit("started", node=n["name"], port=ports[n["name"]])

    finish_deployment(payload, ports, str(path))


def finish_deployment(payload, ports, path):
    plan = payload["plan"]

    def configure(n):
        emit("waiting", node=n["name"])
        child = node_console(n, ports[n["name"]], True)
        try:
            for line in payload["configs"][n["name"]]:
                node_command(child, line, n["device"]["console"])
            if n["device"]["console"] == "nxos":
                # Persist the observed image: otherwise 9000v can return to loader on reload.
                image = nxos_boot_image(node_command(child, "show version", "nxos"), n)
                for line in (
                    "configure terminal",
                    "boot nxos bootflash:" + image,
                    "end",
                    "copy running-config startup-config",
                ):
                    node_command(
                        child, line, "nxos", timeout=300 if line.startswith("boot nxos ") else 90
                    )
        finally:
            child.close()
        emit("configured", node=n["name"])

    with ThreadPoolExecutor(max_workers=4) as pool:
        # All nodes start before console waits; configure independent nodes concurrently.
        futures = [pool.submit(configure, n) for n in plan["nodes"]]
        for f in futures:
            f.result()
    for step in plan.get("post_config", []) if plan["mode"] == "reference" else []:
        n = next(n for n in plan["nodes"] if n["name"] == step["node"])
        child = node_console(n, ports[n["name"]])
        try:
            for line in step["commands"]:
                node_command(child, line, n["device"]["console"])
        finally:
            child.close()
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


def catalog_main(payload):
    action = payload["action"]
    plan = payload.get("plan", {})
    if plan.get("schema") != 2 and action not in ("inventory", "stop"):
        return legacy_main(payload)
    if action == "inventory":
        emit("inventory", **inventory())
    elif action == "preflight":
        emit("preflight", **preflight(plan))
    elif action == "deploy":
        catalog_deploy(payload)
    elif action == "verify":
        identity(plan)
        emit("verification", **verify(plan, payload["ports"], payload.get("exercise", False)))
    elif action in ("fault", "restore"):
        identity(plan)
        step = next(
            (s for s in plan["actions"] if s["id"] == payload.get("action_id", "fault")), None
        )
        if not step:
            raise ValueError("Esta receta no define una falla reversible")
        affected = []
        for part in [step] + ([step["peer"]] if "peer" in step else []):
            n = next(n for n in plan["nodes"] if n["name"] == part["node"])
            child = node_console(n, payload["ports"][n["name"]])
            try:
                if n["device"]["console"] == "ios":
                    node_command(child, "enable", "ios")
                for line in part["commands" if action == "fault" else "inverse"]:
                    node_command(child, line, n["device"]["console"])
            finally:
                child.close()
            affected.append(n["name"])
        emit("action", status="applied", action=action, node=step["node"], nodes=affected)
    elif action == "stop":
        path = identity(plan)
        for n in plan["nodes"]:
            subprocess.run(
                [
                    "/opt/unetlab/wrappers/unl_wrapper",
                    "-a",
                    "stop",
                    "-m",
                    "1",
                    "-T",
                    "0",
                    "-F",
                    str(path),
                    "-D",
                    str(n["id"]),
                    "-U",
                    "admin",
                ],
                check=True,
                capture_output=True,
                timeout=120,
            )
        deadline = time.monotonic() + 15
        while running_lab_processes(plan):
            if time.monotonic() >= deadline:
                raise RuntimeError("EVE-NG no confirmó el apagado completo del laboratorio")
            time.sleep(1)
        emit("stopped", path=str(path), status="stopped")
    else:
        raise ValueError("Operación desconocida")


def running_lab_processes(plan):
    """Count live emulator processes only inside this tenant/lab's runtime directory."""
    root = Path("/opt/unetlab/tmp/0") / plan["uuid"]
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cwd = (entry / "cwd").resolve()
            name = (entry / "comm").read_text().strip()
            state = (entry / "stat").read_text().split(")", 1)[1].split()[0]
            if cwd.is_relative_to(root) and name.startswith(("qemu", "vpcs")) and state != "Z":
                found.append(int(entry.name))
        except (OSError, IndexError):
            continue
    return found


if __name__ == "__main__":
    try:
        catalog_main(json.load(sys.stdin))
    except Exception as exc:  # noqa: BLE001 — worker protocol boundary reports partial state.
        emit("error", message=str(exc), status="incomplete")
        sys.exit(1)
