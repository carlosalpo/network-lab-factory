"""Resolved B01 teaching plan. No network access or side effects."""

import base64
import html
import ipaddress
import re
import uuid
import xml.etree.ElementTree as ET

PROFILE = "vios-adventerprisek9-m.spa.159-3"


def make_plan(
    name,
    image=PROFILE,
    transit="10.240.0.0/30",
    loopbacks="10.241.0.0/24",
    mode="practice",
    folder="Network-Lab-Factory",
):
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,47}", name):
        raise ValueError("Use a lowercase lab name, digits and hyphens, maximum 48 characters.")
    if image != PROFILE:
        raise ValueError("B01 currently supports only the validated IOSv 15.9(3) profile.")
    if mode not in ("practice", "reference"):
        raise ValueError("Choose practice or reference mode.")
    if not re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*", folder):
        raise ValueError("Use relative folder names with letters, digits, underscores or hyphens.")
    link = ipaddress.IPv4Network(transit, strict=True)
    loops = ipaddress.IPv4Network(loopbacks, strict=True)
    if link.prefixlen not in (30, 31) or loops.prefixlen > 30:
        raise ValueError(
            "Transit must be /30 or /31; loopback pool needs at least two host addresses."
        )
    private = [ipaddress.IPv4Network(s) for s in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
    if not all(any(n.subnet_of(p) for p in private) for n in (link, loops)):
        raise ValueError("Use RFC1918 pools for this isolated workshop.")
    if link.overlaps(loops):
        raise ValueError("Transit and loopback pools overlap.")
    lh, bh = iter(link.hosts()), iter(loops.hosts())
    nodes = [
        {
            "id": i,
            "name": f"r0{i}",
            "ip": str(next(lh)),
            "loopback": str(next(bh)),
            "x": 180 + (i - 1) * 460,
            "y": 240,
        }
        for i in (1, 2)
    ]
    return {
        "schema": 1,
        "scenario": "B01",
        "name": name,
        "image": image,
        "mode": mode,
        "folder": folder,
        "transit": str(link),
        "loopbacks": str(loops),
        "uuid": str(uuid.uuid4()),
        "nodes": nodes,
        "cpu": 2,
        "ram_mib": 1024,
    }


def validate_plan(plan):
    if plan.get("schema") == 2:
        from .recipes import validate_catalog_plan

        return validate_catalog_plan(plan)
    expected = make_plan(
        **{k: plan[k] for k in ("name", "image", "transit", "loopbacks", "mode", "folder")}
    )
    expected["uuid"] = str(uuid.UUID(plan["uuid"]))
    if expected != plan:
        raise ValueError(
            "Plan differs from the supported B01 schema. Regenerate it with the wizard."
        )
    return plan


def ascii_preview(plan):
    if plan.get("schema") == 2:
        from .catalog_render import ascii_topology

        return ascii_topology(plan)
    a, b = plan["nodes"]
    suffix = ipaddress.IPv4Network(plan["transit"]).prefixlen
    return (
        f"\n  {a['name']}                                           {b['name']}\n"
        f"  Lo0 {a['loopback']}/32                       Lo0 {b['loopback']}/32\n"
        "  +---------+                                 +---------+\n"
        "  |  IOSv   | Gi0/1 ------------------- Gi0/1 |  IOSv   |\n"
        "  +---------+                                 +---------+\n"
        f"    {a['ip']}/{suffix}                            {b['ip']}/{suffix}\n"
        f"\n  Link: {plan['transit']}   |   No external network or management bridge\n"
        f"  Base: IP + loopbacks   |   OSPF: {'your exercise' if plan['mode'] == 'practice' else 'configured reference'}\n"
    )


def config_lines(plan, node):
    if plan.get("schema") == 2:
        from .catalog import commands

        return commands(node, plan["mode"])
    mask = str(ipaddress.IPv4Network(plan["transit"]).netmask)
    lines = [
        "enable",
        "configure terminal",
        f"hostname {node['name']}",
        "no ip domain-lookup",
        "interface GigabitEthernet0/1",
        f"ip address {node['ip']} {mask}",
        "description NLF B01 point-to-point",
        "no shutdown",
        "exit",
        "interface Loopback0",
        f"ip address {node['loopback']} 255.255.255.255",
        "exit",
    ]
    if plan["mode"] == "reference":
        lines += [
            "router ospf 1",
            f"router-id {node['loopback']}",
            "passive-interface default",
            "no passive-interface GigabitEthernet0/1",
            "exit",
            "interface GigabitEthernet0/1",
            "ip ospf network point-to-point",
            "ip ospf 1 area 0",
            "exit",
            "interface Loopback0",
            "ip ospf 1 area 0",
            "exit",
        ]
    return lines + ["end", "write memory"]


def lab_xml(plan):
    if plan.get("schema") == 2:
        from .catalog_render import eve_xml

        return eve_xml(plan)
    validate_plan(plan)
    root = ET.Element(
        "lab",
        name=plan["name"],
        id=plan["uuid"],
        version="1",
        scripttimeout="600",
        lock="0",
        sat="-1",
    )
    ET.SubElement(root, "description").text = "NLF B01 isolated OSPF workshop"
    ET.SubElement(root, "author").text = "Network Lab Factory"
    ET.SubElement(root, "body").text = ascii_preview(plan)
    topology = ET.SubElement(root, "topology")
    nodes = ET.SubElement(topology, "nodes")
    for n in plan["nodes"]:
        node = ET.SubElement(
            nodes,
            "node",
            id=str(n["id"]),
            name=n["name"],
            type="qemu",
            template="vios",
            image=plan["image"],
            console="telnet",
            cpu="1",
            ram="512",
            ethernet="4",
            config="0",
            delay="0",
            icon="Router.png",
            uuid=str(uuid.uuid5(uuid.UUID(plan["uuid"]), n["name"])),
            left=str(n["x"]),
            top=str(n["y"]),
        )
        ET.SubElement(node, "interface", id="1", name="Gi0/1", type="ethernet", network_id="1")
    nets = ET.SubElement(topology, "networks")
    ET.SubElement(
        nets,
        "network",
        id="1",
        name="B01 transit",
        type="bridge",
        left="430",
        top="240",
        visibility="0",
    )
    objects = ET.SubElement(ET.SubElement(root, "objects"), "textobjects")
    labels = [
        (100, 70, "B01 | OSPF point-to-point | " + plan["mode"]),
        (
            100,
            115,
            "Base: interface IPs and loopbacks. "
            + (
                "Exercise: configure OSPF area 0."
                if plan["mode"] == "practice"
                else "Reference: OSPF area 0 configured."
            ),
        ),
    ]
    for n in plan["nodes"]:
        # Centre the compact labels beside EVE's port badge at each link end.
        # The loopback is identified separately because it is a logical interface.
        label_x = n["x"] + (25 if n["id"] == 1 else -152)
        labels += [
            (label_x, 245, n["ip"] + "/" + plan["transit"].split("/")[1]),
            (label_x, 283, "Lo0  " + n["loopback"] + "/32"),
        ]
    labels += [(300, 440, "Isolated lab | No external uplink | Check results in NLF report")]
    for i, (x, y, text) in enumerate(labels, 1):
        obj = ET.SubElement(objects, "textobject", id=str(i), name=f"NLF label {i}", type="text")
        interface_label = 3 <= i <= 6
        font_size = 10 if interface_label else 16
        alignment = "width:180px;text-align:center;" if interface_label else ""
        markup = (
            f'<div style="position:absolute;left:{x}px;top:{y}px;z-index:10;{alignment}">'
            '<p style="margin:0;color:#202830;font-weight:normal;background-color:#ffffff;'
            f'font-size:{font_size}px;">{html.escape(text)}</p></div>'
        )
        ET.SubElement(obj, "data").text = base64.b64encode(markup.encode()).decode()
    ET.indent(root)
    return ET.tostring(root, encoding="unicode", xml_declaration=True)
