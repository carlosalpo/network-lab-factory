"""Native GNS3 nodes, isolated point-to-point links and readable drawing objects."""

import base64
import html
import re
import uuid
import xml.etree.ElementTree as ET

from .catalog_render import eve_xml
from .gns3_profiles import GNS3_PROFILES
from .recipes import validate_catalog_plan


def resource_id(plan, key):
    return str(uuid.uuid5(uuid.UUID(plan["uuid"]), key))


def native_graph(plan):
    validate_catalog_plan(plan)
    if plan.get("backend") != "gns3":
        raise ValueError("Se necesita una receta para GNS3.")
    nodes = []
    for n in plan["nodes"]:
        p = GNS3_PROFILES[n["gns3_profile"]]
        vpcs = n["profile"] == "vpcs"
        node = {
            "node_id": resource_id(plan, n["name"]),
            "compute_id": "local",
            "name": n["name"],
            "node_type": "vpcs" if vpcs else "qemu",
            "console_type": "telnet",
            "x": n["x"] + 60,
            "y": n["y"] + 120,
            "label": {"text": n["name"], "style": "font-size: 10px;", "x": 0, "y": -25},
            "symbol": ":/symbols/classic/vpcs_guest.svg"
            if vpcs or n.get("role") == "endpoint"
            else ":/symbols/classic/multilayer_switch.svg"
            if n["profile"] in ("iosvl2", "nxos", "nxos105")
            else ":/symbols/classic/router.svg",
            "properties": {},
        }
        if not vpcs:
            props = {
                "hda_disk_image": p["image"],
                "hda_disk_interface": p["disk_interface"],
                "linked_clone": True,
                "qemu_path": "/opt/nexo-qemu7/bin/qemu-system-x86_64",
                "ram": n["device"]["ram"],
                "cpus": n["device"]["cpu"],
                "adapters": n["device"]["ports"],
                "adapter_type": p["adapter_type"],
                "platform": "x86_64",
                "options": "-cpu qemu64 -machine pc-i440fx-2.4"
                if n["profile"] in ("iosv", "iosvl2")
                else "-cpu host,vmx=off,svm=off -machine pc-i440fx-4.1",
            }
            if p.get("bios"):
                props["bios_image"] = p["bios"]
            node["properties"] = props
        nodes.append(node)
    links = [
        {
            "link_id": resource_id(plan, "link-" + str(net["id"])),
            "nodes": [
                {
                    "node_id": resource_id(plan, e["node"]),
                    "adapter_number": e["port"],
                    "port_number": 0,
                }
                for e in net["endpoints"]
            ],
        }
        for net in plan["networks"]
    ]
    drawings = []
    root = ET.fromstring(eve_xml(plan))
    for i, obj in enumerate(root.findall("./objects/textobjects/textobject"), 1):
        markup = base64.b64decode(obj.findtext("data")).decode()
        element = ET.fromstring(markup)
        text = "".join(element.itertext())
        x = int(re.search(r"left:(-?\d+)px", markup)[1])
        y = int(re.search(r"top:(-?\d+)px", markup)[1])
        size = int(re.search(r"font-size:(\d+)px", markup)[1])
        width = max(80, int(len(text) * size * 0.65) + 8)
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{size + 8}"><text x="0" y="{size + 3}" font-family="monospace" font-size="{size}" fill="#444444">'
            + html.escape(text)
            + "</text></svg>"
        )
        drawings.append(
            {"drawing_id": resource_id(plan, "label-" + str(i)), "x": x, "y": y, "z": 1, "svg": svg}
        )
    return {"nodes": nodes, "links": links, "drawings": drawings}
