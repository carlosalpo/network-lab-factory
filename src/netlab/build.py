"""Deterministic EVE-NG XML, IOS intent and Ansible inventory generation."""

import hashlib
import ipaddress
import json
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

from .model import validate


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def interface(port):
    return f"GigabitEthernet0/{port}"


def host_data(data):
    hosts = {}
    for node in data["nodes"]:
        hosts[node["name"]] = {
            "ansible_host": node["management_ip"],
            "loopback": node["loopback"],
            "lab_interfaces": [],
            "expected_neighbors": [],
            "probe_targets": [n["loopback"] for n in data["nodes"] if n != node],
        }
    for link in data["links"]:
        net = ipaddress.IPv4Network(link["subnet"])
        for index, ep in enumerate(link["endpoints"]):
            peer = link["endpoints"][1 - index]
            hosts[ep["node"]]["lab_interfaces"].append(
                {
                    "name": interface(ep["port"]),
                    "ip": ep["ip"],
                    "mask": str(net.netmask),
                    "cost": link["cost"],
                    "description": f"NLF {link['name']} to {peer['node']}",
                }
            )
            hosts[ep["node"]]["expected_neighbors"].append(hosts[peer["node"]]["loopback"])
    return hosts


def eve_xml(data):
    lab_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "network-lab-factory/" + data["name"]))
    root = ET.Element(
        "lab",
        {
            "name": data["name"],
            "id": lab_id,
            "version": "1",
            "scripttimeout": "300",
            "lock": "0",
            "sat": "-1",
        },
    )
    ET.SubElement(root, "description").text = "Network Lab Factory synthetic IOSv lab"
    ET.SubElement(root, "author").text = "Network Lab Factory"
    ET.SubElement(root, "body").text = (
        "Bootstrap SSH on Gi0/0, then use the generated Ansible inventory. "
        "Management is excluded from OSPF. No images or credentials are included."
    )
    topology = ET.SubElement(root, "topology")
    nodes = ET.SubElement(topology, "nodes")
    networks = ET.SubElement(topology, "networks")
    ET.SubElement(
        networks,
        "network",
        {
            "id": "1",
            "type": data["management"]["bridge"],
            "name": "NLF-MGMT",
            "left": "450",
            "top": "550",
            "visibility": "1",
        },
    )
    wiring = {}
    for index, link in enumerate(data["links"], start=2):
        ET.SubElement(
            networks,
            "network",
            {
                "id": str(index),
                "type": "bridge",
                "name": link["name"],
                "left": str(250 + index * 40),
                "top": "250",
                "visibility": "0",
            },
        )
        for ep in link["endpoints"]:
            wiring[(ep["node"], ep["port"])] = index
    for index, node in enumerate(data["nodes"], start=1):
        element = ET.SubElement(
            nodes,
            "node",
            {
                "id": str(index),
                "name": node["name"],
                "type": "qemu",
                "template": "vios",
                "image": data["image"],
                "console": "telnet",
                "cpu": "1",
                "ram": "512",
                "ethernet": "4",
                "config": "0",
                "delay": "0",
                "icon": "Router.png",
                "uuid": str(uuid.uuid5(uuid.UUID(lab_id), node["name"])),
                "left": str(node["x"]),
                "top": str(node["y"]),
            },
        )
        for port in range(4):
            # EVE rejects network_id=0; omit disconnected interface records.
            if port != 0 and (node["name"], port) not in wiring:
                continue
            ET.SubElement(
                element,
                "interface",
                {
                    "id": str(port),
                    "name": f"Gi0/{port}",
                    "type": "ethernet",
                    "network_id": str(1 if port == 0 else wiring[(node["name"], port)]),
                },
            )
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode() + "\n"


def routing_config(host):
    lines = [
        "interface Loopback0",
        " description NLF verification endpoint",
        f" ip address {host['loopback']} 255.255.255.255",
        " ip ospf 1 area 0",
        "!",
    ]
    for port in host["lab_interfaces"]:
        lines.extend(
            [
                f"interface {port['name']}",
                f" description {port['description']}",
                f" ip address {port['ip']} {port['mask']}",
                " ip ospf network point-to-point",
                f" ip ospf cost {port['cost']}",
                " ip ospf 1 area 0",
                " no shutdown",
                "!",
            ]
        )
    lines.extend(["router ospf 1", f" router-id {host['loopback']}", " passive-interface default"])
    lines.extend(f" no passive-interface {p['name']}" for p in host["lab_interfaces"])
    return "\n".join(lines) + "\n"


def build(data, destination):
    validate(data)
    out = Path(destination)
    # Refuse reuse: stale inventories and evidence must not survive a new build.
    out.mkdir(parents=True, exist_ok=False)
    (out / "configs").mkdir()
    hosts = host_data(data)
    lab_file = f"{data['name']}.unl"
    files = {lab_file: eve_xml(data)}
    files["scenario.yml"] = yaml.safe_dump(data, sort_keys=False)
    variables = {
        "ansible_connection": "ansible.netcommon.network_cli",
        "ansible_network_os": "cisco.ios.ios",
        "ansible_network_cli_ssh_type": "paramiko",
        "ansible_user": "{{ lookup('ansible.builtin.env', 'LAB_USERNAME') }}",
        "ansible_password": "{{ lookup('ansible.builtin.env', 'LAB_PASSWORD') }}",
        "ansible_command_timeout": 60,
    }
    files["inventory.yml"] = yaml.safe_dump(
        {"all": {"children": {"routers": {"vars": variables, "hosts": hosts}}}}, sort_keys=False
    )
    manifest = {
        "schema_version": 1,
        "lab": data["name"],
        "scenario_sha256": fingerprint(data),
        "lab_file": lab_file,
        "image": data["image"],
        "management_bridge": data["management"]["bridge"],
        "expected": {
            n: {"neighbors": h["expected_neighbors"], "targets": h["probe_targets"]}
            for n, h in hosts.items()
        },
    }
    for name, host in hosts.items():
        files[f"configs/{name}.cfg"] = routing_config(host)
    manifest["artifacts"] = {
        name: hashlib.sha256(content.encode()).hexdigest() for name, content in files.items()
    }
    for name, content in files.items():
        (out / name).write_text(content, encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return out


def check_build(path):
    out = Path(path).resolve()
    manifest = json.loads((out / "manifest.json").read_text())
    for name, expected in manifest["artifacts"].items():
        file = (out / name).resolve()
        if (
            not file.is_relative_to(out)
            or hashlib.sha256(file.read_bytes()).hexdigest() != expected
        ):
            raise ValueError(
                f"Build artifact changed: {name}; create a new build from the scenario"
            )
    return manifest


def bootstrap(data, username, password, destination):
    """Write local console snippets with caller-provided credentials, never to build output."""
    import os
    import re

    validate(data)
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,31}", username):
        raise ValueError("Invalid lab username")
    if not re.fullmatch(r"[A-Za-z0-9_!@%+=.,:-]{12,25}", password):
        raise ValueError("Use a 12-25 character lab password: letters, numbers or _!@%+=.,:-")
    out = Path(destination)
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    mask = str(ipaddress.IPv4Network(data["management"]["network"]).netmask)
    for node in data["nodes"]:
        text = (
            f"enable\nconfigure terminal\nhostname {node['name']}\n"
            "ip domain-name lab.example\n"
            f"username {username} privilege 15 secret 0 {password}\n"
            "crypto key generate rsa general-keys modulus 2048\nip ssh version 2\n"
            f"interface GigabitEthernet0/0\n ip address {node['management_ip']} {mask}\n"
            " no shutdown\nexit\nline vty 0 4\n login local\n transport input ssh\n"
            "end\nwrite memory\n"
        )
        file = out / f"{node['name']}.txt"
        fd = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(text)
    return out
