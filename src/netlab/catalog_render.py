"""Render the same resolved graph to terminal, EVE-NG and a portable bundle."""

import base64
import html
import ipaddress
import json
import re
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from .catalog import commands
from .language import english
from .recipes import validate_catalog_plan


def interface_annotations(node, mode):
    """Resolved addresses include subinterfaces, SVIs and manually addressed hosts."""
    result = {i["name"]: [] for i in node["interfaces"]}
    streams = [(node["base"], False), (node["solution"], mode == "practice")]
    for lines, pending in streams:
        current = None
        for line in lines:
            if line.startswith("interface "):
                current = line.split(" ", 1)[1]
            elif line in ("exit", "end"):
                current = None
            value = None
            if current and line.startswith("ip address "):
                fields = line.split()
                address = fields[2] + (
                    "/" + fields[3] if "/" not in fields[2] and len(fields) > 3 else ""
                )
                value = str(ipaddress.IPv4Interface(address))
            elif current and line.startswith("ipv6 address "):
                value = line.split()[2]
            elif node["profile"] == "vpcs" and re.match(r"ip \d", line):
                current = node["interfaces"][0]["name"]
                value = line.split()[1]
            if value:
                note = value + (" [exercise]" if pending else "")
                bucket = result.setdefault(current, [])
                if note not in bucket and value not in bucket:
                    bucket.append(note)
    return result


def ascii_topology(plan, width=80, details=True):
    nodes = plan["nodes"]
    width = max(45, min(width, 100))
    height = min(16, max(4, len({n["y"] for n in nodes}) * 3))
    minx, miny = min(n["x"] for n in nodes), min(n["y"] for n in nodes)
    spanx = max(n["x"] for n in nodes) - minx or 1
    spany = max(n["y"] for n in nodes) - miny or 1
    coords = {
        n["name"]: (
            min(width - 12, 6 + int((n["x"] - minx) / spanx * (width - 20))),
            1 + int((n["y"] - miny) / spany * (height - 3)),
        )
        for n in nodes
    }
    canvas = [[" "] * width for _ in range(height + 1)]
    for net in plan["networks"]:
        a, b = [coords[e["node"]] for e in net["endpoints"]]
        steps = max(abs(b[0] - a[0]), abs(b[1] - a[1]), 1)
        char = (
            "-"
            if a[1] == b[1]
            else "|"
            if a[0] == b[0]
            else "/"
            if (b[0] - a[0]) * (b[1] - a[1]) < 0
            else "\\"
        )
        for t in range(steps + 1):
            x = round(a[0] + (b[0] - a[0]) * t / steps)
            y = round(a[1] + (b[1] - a[1]) * t / steps)
            canvas[y][x] = char
    for name, (x, y) in coords.items():
        label = "[" + name + "]"
        start = max(0, x - len(label) // 2)
        for j, c in enumerate(label):
            if start + j < width:
                canvas[y][start + j] = c
    lines = ["".join(row).rstrip() for row in canvas]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    if not details:
        return "\n".join(lines)
    lines += ["", "CONNECTIONS"]
    for net in plan["networks"]:
        ep = net["endpoints"]
        lines += [f"{ep[0]['node']} {ep[0]['interface']} -- {ep[1]['node']} {ep[1]['interface']}"]
        if "subnet" in net:
            lines += ["  " + net["subnet"]]
    lines += ["", "ADDRESSES"]
    for n in nodes:
        notes = interface_annotations(n, plan["mode"])
        values = [
            name + " " + ", ".join(addresses) for name, addresses in notes.items() if addresses
        ]
        if values:
            lines += [n["name"] + ": " + ", ".join(values)]
    return "\n".join(lines)


def short_interface(name):
    for full, short in (
        ("GigabitEthernet", "Gi"),
        ("Ethernet", "Eth"),
        ("Loopback", "Lo"),
        ("Port-channel", "Po"),
    ):
        if name.startswith(full):
            return short + name[len(full) :]
    return name


def eve_xml(plan):
    validate_catalog_plan(plan)
    root = ET.Element(
        "lab",
        name=plan["name"],
        id=plan["uuid"],
        version="1",
        scripttimeout="900",
        lock="0",
        sat="-1",
    )
    ET.SubElement(root, "description").text = (
        plan["scenario"] + " " + english(plan["title"]) + " · " + plan["mode"]
    )
    ET.SubElement(root, "author").text = "Network Lab Factory"
    ET.SubElement(root, "body").text = ascii_topology(plan)
    topology = ET.SubElement(root, "topology")
    nodes = ET.SubElement(topology, "nodes")
    lookup = {n["name"]: n for n in plan["nodes"]}
    labels = [
        (70, 25, plan["scenario"] + " | " + english(plan["title"]) + " | " + plan["mode"], 16),
        (70, 55, "Exercise: " + english(plan["exercise"]), 12),
    ]
    for n in plan["nodes"]:
        p = n["device"]
        notes = interface_annotations(n, plan["mode"])
        vpcs = p["console"] == "vpcs"
        attrs = {
            "id": str(n["id"]),
            "name": n["name"],
            "type": "vpcs" if vpcs else "qemu",
            "template": p["template"],
            "console": "telnet",
            "ethernet": str(p["ports"]),
            "config": "0",
            "left": str(n["x"] + 60),
            "top": str(n["y"] + 120),
            "delay": "0",
            "icon": "Desktop.png"
            if vpcs or n.get("role") == "endpoint"
            else "Firewall.png"
            if p["console"] == "asa"
            else "Switch.png"
            if n["profile"] in ("iosvl2", "nxos", "nxos105")
            else "Router.png",
        }
        if not vpcs:
            attrs.update(
                image=p["image"],
                cpu=str(p["cpu"]),
                ram=str(p["ram"]),
                uuid=str(uuid.uuid5(uuid.UUID(plan["uuid"]), n["name"])),
            )
        node = ET.SubElement(nodes, "node", **attrs)
        for iface in n["interfaces"]:
            ET.SubElement(
                node,
                "interface",
                id=str(iface["id"]),
                name=iface["name"],
                type="ethernet",
                network_id=str(iface["network"]),
            )
            net = plan["networks"][iface["network"] - 1]
            peer = lookup[next(e["node"] for e in net["endpoints"] if e["node"] != n["name"])]
            dx, dy = peer["x"] - n["x"], peer["y"] - n["y"]
            # Label near the local port, offset per interface to preserve distinct parallel links.
            y = n["y"] + 120 + (30 if dy >= 0 else -40) + iface["id"] * 17
            text = short_interface(iface["name"])
            if notes.get(iface["name"]):
                text += " " + ", ".join(notes[iface["name"]])
            if "vlan" in iface:
                text += " V" + str(iface["vlan"])
            if "vrf" in iface:
                text += " VRF " + iface["vrf"]
            x = n["x"] + 60 + (85 if dx >= 0 else -max(155, len(text) * 6 + 12))
            labels.append((x, y, text, 10))
        physical = {i["name"] for i in n["interfaces"]}
        logical = [
            (name, addresses)
            for name, addresses in notes.items()
            if name not in physical and addresses
        ]
        for j, (name, addresses) in enumerate(logical):
            text = short_interface(name) + " " + ", ".join(addresses)
            midpoint = (
                min(node["x"] for node in plan["nodes"]) + max(node["x"] for node in plan["nodes"])
            ) / 2
            # Logical interfaces sit outside the fan of physical links, beside the node.
            x = n["x"] + 60 + (-len(text) * 6 - 20 if n["x"] < midpoint else 90)
            labels.append((x, n["y"] + 148 + j * 14, text, 10))
    networks = ET.SubElement(topology, "networks")
    for net in plan["networks"]:
        ET.SubElement(
            networks,
            "network",
            id=str(net["id"]),
            name=net["name"],
            type="bridge",
            visibility="0",
            left="0",
            top="0",
        )
    objects = ET.SubElement(ET.SubElement(root, "objects"), "textobjects")
    for j, (x, y, text, size) in enumerate(labels, 1):
        obj = ET.SubElement(objects, "textobject", id=str(j), name=f"NLF {j}", type="text")
        markup = f'<div style="position:absolute;left:{x}px;top:{y}px"><p style="margin:0;font-size:{size}px;color:#202830;background:#fff">{html.escape(text)}</p></div>'
        ET.SubElement(obj, "data").text = base64.b64encode(markup.encode()).decode()
    ET.indent(root)
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def write_bundle(plan, output):
    validate_catalog_plan(plan)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
    if plan.get("backend") == "gns3":
        from .gns3_render import native_graph

        (output / "gns3-request.json").write_text(json.dumps(native_graph(plan), indent=2))
    else:
        (output / (plan["name"] + ".unl")).write_text(eve_xml(plan))
    (output / "topology.txt").write_text(ascii_topology(plan) + "\n")
    for n in plan["nodes"]:
        (output / (n["name"] + ".base.cfg")).write_text("\n".join(commands(n)) + "\n")
        (output / (n["name"] + ".reference.cfg")).write_text(
            "\n".join(commands(n, "reference")) + "\n"
        )
    (output / "checks.json").write_text(
        json.dumps(plan["checks"], ensure_ascii=False, indent=2) + "\n"
    )
    return output
