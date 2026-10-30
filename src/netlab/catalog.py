"""Versioned catalog, device contracts and deterministic allocation primitives."""

import ipaddress
import json
import re
import uuid
from pathlib import Path

CATALOG = {
    s["id"]: s
    for s in json.loads(Path(__file__).with_name("data").joinpath("catalog.json").read_text())[
        "scenarios"
    ]
}

# Explicit profiles: an installed image is never inferred to support another family.
PROFILES = {
    "iosv": {
        "template": "vios",
        "image": "vios-adventerprisek9-m.spa.159-3",
        "console": "ios",
        "ram": 512,
        "cpu": 1,
        "ports": 4,
        "first": 1,
        "disk": "virtioa.qcow2",
    },
    "iosvl2": {
        "template": "viosl2",
        "image": "viosl2-adventerprisek9-m.SSA.high_iron_20200929",
        "console": "ios",
        "ram": 1024,
        "cpu": 1,
        "ports": 16,
        "first": 0,
        "disk": "virtioa.qcow2",
    },
    "csr": {
        "template": "csr1000vng",
        "image": "csr1000vng-17.03.05",
        "console": "ios",
        "ram": 4096,
        "cpu": 1,
        "ports": 4,
        "first": 0,
        "disk": "virtioa.qcow2",
    },
    "nxos": {
        "template": "nxosv9k",
        "image": "nxosv9k-9300v-9.3.9",
        "console": "nxos",
        "ram": 8192,
        "cpu": 2,
        "ports": 8,
        "first": 1,
        "disk": "sataa.qcow2",
    },
    "nxos105": {
        "template": "nxosv9k",
        "image": "nxosv9k-9300v-10.5.3.F",
        "console": "nxos",
        "ram": 8192,
        "cpu": 2,
        "ports": 8,
        "first": 1,
        "disk": "sataa.qcow2",
    },
    "asa": {
        "template": "asav",
        "image": "asav-9-18-4",
        "console": "asa",
        "ram": 2048,
        "cpu": 1,
        "ports": 8,
        "first": 1,
        "disk": "virtioa.qcow2",
    },
    "vpcs": {
        "template": "vpcs",
        "image": "",
        "console": "vpcs",
        "ram": 8,
        "cpu": 0,
        "ports": 1,
        "first": 0,
    },
}


def interface_name(profile, port):
    if profile == "iosvl2":
        return f"GigabitEthernet{port // 4}/{port % 4}"
    if profile == "csr":
        return f"GigabitEthernet{port + 1}"
    if profile.startswith("nxos"):
        return f"Ethernet1/{port}"
    if profile == "asa":
        return f"GigabitEthernet0/{port - 1}"
    if profile == "vpcs":
        return "eth0"
    return f"GigabitEthernet0/{port}"


class Recipe:
    """Resolved graph and per-node base / solution, independent of the hypervisor."""

    def __init__(
        self,
        scenario,
        name,
        *,
        mode="practice",
        folder="Network-Lab-Factory",
        images=None,
        transit="10.240.0.0/16",
        loopbacks="10.241.0.0/16",
        lans="10.242.0.0/16",
        instance=None,
        backend="eve",
    ):
        if backend not in ("eve", "gns3"):
            raise ValueError("Unknown platform")
        self.backend = backend
        if scenario not in CATALOG:
            raise ValueError("Unknown scenario")
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,47}", name):
            raise ValueError("Name: lowercase letters, digits and hyphens; maximum 48 characters.")
        if not re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*", folder):
            raise ValueError("Invalid relative folder.")
        if mode not in ("practice", "reference"):
            raise ValueError("Invalid mode")
        nets = [ipaddress.IPv4Network(p, strict=True) for p in (transit, loopbacks, lans)]
        private = [
            ipaddress.IPv4Network(p) for p in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
        ]
        if not all(any(n.subnet_of(p) for p in private) for n in nets):
            raise ValueError("Pools must use private RFC1918 addresses.")
        if any(a.overlaps(b) for i, a in enumerate(nets) for b in nets[i + 1 :]):
            raise ValueError("Transit, loopback and LAN pools overlap.")
        if nets[0].prefixlen > 30 or nets[1].prefixlen > 30 or nets[2].prefixlen > 24:
            raise ValueError(
                "Pools too small: transit /30, loopbacks /30 and LAN /24 or larger required."
            )
        self.transits = iter(nets[0].subnets(new_prefix=30))
        self.loops = iter(nets[1].hosts())
        self.lans = iter(nets[2].subnets(new_prefix=24))
        self.images = images or {}
        if any(k not in PROFILES for k in self.images):
            raise ValueError("Unknown image profile")
        for family, image in self.images.items():
            if image not in [
                v["image"]
                for k, v in PROFILES.items()
                if v["template"] == PROFILES[family]["template"]
            ]:
                raise ValueError(f"Image has no explicit profile: {image}")
        self.plan = {
            "schema": 2,
            "scenario": scenario,
            "name": name,
            "mode": mode,
            "folder": folder,
            "uuid": str(uuid.UUID(instance)) if instance else str(uuid.uuid4()),
            "title": CATALOG[scenario]["title"],
            "exercise": CATALOG[scenario]["exercise"],
            "prepare": CATALOG[scenario]["prepare"],
            "nodes": [],
            "networks": [],
            "checks": {"preparation": [], "exercise": []},
            "actions": [],
            "parameters": {
                "images": self.images,
                "transit": transit,
                "loopbacks": loopbacks,
                "lans": lans,
            },
            "image": "Por perfil",
            "cpu": 0,
            "ram_mib": 0,
        }
        self.nodes = {}
        if backend == "gns3":
            self.plan["backend"] = backend

    def node(self, name, profile="iosv", x=0, y=0, loop=True):
        p = dict(PROFILES[profile])
        p["image"] = self.images.get(profile, p["image"])
        gns3_profile = None
        if self.backend == "gns3":
            from .gns3_profiles import GNS3_PROFILES

            gns3_profile = next(k for k, v in PROFILES.items() if v["image"] == p["image"])
            p.update({k: GNS3_PROFILES[gns3_profile][k] for k in ("ram", "cpu")})
        n = {
            "id": len(self.nodes) + 1,
            "name": name,
            "profile": profile,
            "device": p,
            "x": x,
            "y": y,
            "interfaces": [],
            "base": [],
            "solution": [],
            "loopback": None,
        }
        if p["console"] == "vpcs":
            n["base"] = [f"set pcname {name}"]
        else:
            n["base"] = [f"hostname {name}"]
            if p["console"] == "ios":
                n["base"] += ["no ip domain lookup" if profile == "csr" else "no ip domain-lookup"]
            if profile == "iosvl2":
                n["base"] += ["spanning-tree mode rapid-pvst"]
            if loop and p["console"] not in ("asa",):
                n["loopback"] = str(next(self.loops))
                self.interface(
                    n,
                    "Loopback0",
                    ["ip address " + n["loopback"] + " 255.255.255.255"]
                    if p["console"] == "ios"
                    else ["ip address " + n["loopback"] + "/32"],
                )
        self.nodes[name] = n
        if gns3_profile:
            n["gns3_profile"] = gns3_profile
        self.plan["nodes"].append(n)
        self.plan["cpu"] += p["cpu"]
        self.plan["ram_mib"] += p["ram"]
        return n

    def interface(self, node, interface, lines, solution=False):
        n = self.nodes[node] if isinstance(node, str) else node
        n["solution" if solution else "base"] += ["interface " + interface, *lines, "exit"]

    def check(self, node, command, pattern, scope="exercise", *, label="", kind="regex"):
        name = node if isinstance(node, str) else node["name"]
        self.plan["checks"][scope].append(
            {
                "node": name,
                "command": command,
                "pattern": pattern,
                "kind": kind,
                "label": label or command,
            }
        )

    def ping(self, node, address, scope="exercise", negative=False, source=None):
        n = self.nodes[node] if isinstance(node, str) else node
        dialect = n["device"]["console"]
        cmd = (
            f"ping {address} -c 3"
            if dialect == "vpcs"
            else f"ping {address} count 3"
            if dialect == "nxos"
            else f"ping {address} repeat 3 timeout 1"
            if dialect == "ios"
            else f"ping {address}"
        )
        if source:
            if dialect not in ("ios", "nxos"):
                raise ValueError("This profile does not support an explicit ping source")
            cmd += " source " + source
        self.check(
            n,
            cmd,
            "",
            scope,
            kind="unreachable" if negative else "ping",
            label=("Aislamiento a " if negative else "Alcance a ") + address,
        )

    def connect(self, a, b, *, routed=False, label="", subnet=None, area=0):
        net = {
            "id": len(self.plan["networks"]) + 1,
            "name": label or f"{a} — {b}",
            "endpoints": [],
            "area": area,
        }
        if routed:
            network = ipaddress.IPv4Network(subnet) if subnet else next(self.transits)
            addresses = iter(network.hosts())
            net["subnet"] = str(network)
        for name in (a, b):
            n = self.nodes[name]
            profile = n["profile"]
            p = n["device"]
            port = p["first"] + len(n["interfaces"])
            if port >= p["ports"]:
                raise ValueError(f"{name}: not enough interfaces in profile {profile}")
            iface = {"id": port, "name": interface_name(profile, port), "network": net["id"]}
            if routed:
                iface["ip"] = str(next(addresses))
                iface["prefix"] = network.prefixlen
                lines = []
                if profile == "iosvl2" or profile.startswith("nxos"):
                    lines += ["no switchport"]
                lines += [
                    "ip address "
                    + iface["ip"]
                    + (
                        f"/{network.prefixlen}"
                        if profile.startswith("nxos")
                        else " " + str(network.netmask)
                    ),
                    "no shutdown",
                ]
                self.interface(n, iface["name"], lines)
            n["interfaces"].append(iface)
            net["endpoints"].append({"node": name, "port": port, "interface": iface["name"]})
        self.plan["networks"].append(net)
        if routed:
            for name, peer in ((a, b), (b, a)):
                self.ping(name, self.nodes[peer]["interfaces"][-1]["ip"], "preparation")
        return tuple(self.nodes[n]["interfaces"][-1] for n in (a, b))

    def host(
        self, name, switch, vlan, subnet, ordinal=10, gateway=None, x=0, y=0, configure_access=True
    ):
        n = self.node(name, "vpcs", x, y, loop=False)
        hi, si = self.connect(name, switch, label=f"VLAN {vlan}")
        network = ipaddress.IPv4Network(subnet)
        address = str(network.network_address + ordinal)
        n["base"] += [f"ip {address}/{network.prefixlen}" + (" " + gateway if gateway else "")]
        n["ip"] = address
        hi.update(ip=address, prefix=network.prefixlen, vlan=vlan)
        si["vlan"] = vlan
        self.interface(
            switch,
            si["name"],
            [
                "switchport mode access",
                f"switchport access vlan {vlan}",
                "spanning-tree portfast",
                "no shutdown",
            ],
            solution=not configure_access,
        )
        self.check(n, "show ip", re.escape(address), "preparation")
        return n

    def vlans(self, names, ids=(100, 101)):
        for name in names:
            for v in ids:
                self.nodes[name]["base"] += [f"vlan {v}", f"name LAB-{v}", "exit"]

    def trunk(self, node, interface, vlans="100,101", solution=False):
        n = self.nodes[node]
        lines = []
        if n["profile"] == "iosvl2":
            lines += ["switchport trunk encapsulation dot1q"]
        lines += ["switchport mode trunk", f"switchport trunk allowed vlan {vlans}", "no shutdown"]
        self.interface(node, interface, lines, solution)

    def ospf(self, names=None, solution=True, process=1):
        for name in names or list(self.nodes):
            n = self.nodes[name]
            if not n["loopback"]:
                continue
            dest = n["solution" if solution else "base"]
            nx = n["device"]["console"] == "nxos"
            if nx:
                dest += ["feature ospf"]
            if n["profile"] == "iosvl2":
                dest += ["ip routing"]
            dest += [f"router ospf {process}", f"router-id {n['loopback']}"]
            if not nx:
                dest += ["passive-interface default"]
                dest += [
                    "no passive-interface " + i["name"]
                    for i in n["interfaces"]
                    if "ip" in i and not i.get("passive")
                ]
            dest += ["exit"]
            for iface in n["interfaces"]:
                if "ip" not in iface:
                    continue
                area = self.plan["networks"][iface["network"] - 1].get("area", 0)
                self.interface(
                    n,
                    iface["name"],
                    [
                        f"ip router ospf {process} area {area}"
                        if nx
                        else f"ip ospf {process} area {area}"
                    ],
                    solution,
                )
            self.interface(
                n,
                "Loopback0",
                [f"ip router ospf {process} area 0" if nx else f"ip ospf {process} area 0"],
                solution,
            )
        selected = set(names or self.nodes)
        for network in self.plan["networks"]:
            if "subnet" not in network:
                continue
            a, b = [e["node"] for e in network["endpoints"]]
            if a not in selected or b not in selected:
                continue
            for node, peer in ((a, b), (b, a)):
                self.check(
                    node,
                    "show ip ospf neighbor",
                    re.escape(self.nodes[peer]["loopback"]) + r"\s+\d+\s+FULL",
                    "exercise" if solution else "preparation",
                )

    def finish(self):
        for n in self.plan["nodes"]:
            if n["device"]["console"] != "vpcs":
                self.check(
                    n,
                    "show running-config | include ^hostname",
                    r"hostname\s+" + re.escape(n["name"]),
                    "preparation",
                    label="Identidad y acceso a consola",
                )
        if not self.plan["checks"]["exercise"]:
            raise ValueError("The recipe has no exercise checks")
        return self.plan


def commands(node, mode="practice"):
    lines = node["base"] + (node["solution"] if mode == "reference" else [])
    dialect = node["device"]["console"]
    if dialect == "vpcs":
        return [*lines, "save"]
    prefix = ["enable"] if dialect in ("ios", "asa") else []
    return (
        prefix
        + ["configure terminal", *lines, "end"]
        + (["copy running-config startup-config"] if dialect == "nxos" else ["write memory"])
    )


def available_profiles(inventory):
    return {
        k: p
        for k, p in PROFILES.items()
        if p["image"] in inventory.get("images", [])
        or (k == "vpcs" and inventory.get("vpcs", False))
    }
