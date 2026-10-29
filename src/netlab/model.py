"""Strict, deliberately small IPv4 / IOSv scenario model."""

import ipaddress
import re
from pathlib import Path

import yaml


class ValidationError(ValueError):
    pass


class UniqueLoader(yaml.SafeLoader):
    """Reject duplicate YAML keys instead of silently changing the design."""


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise ValidationError("YAML mapping keys must be strings")
        if key in result:
            raise ValidationError(f"Duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def fields(value, required, optional=(), label="object"):
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a mapping")
    missing = set(required) - value.keys()
    extra = value.keys() - set(required) - set(optional)
    if missing or extra:
        raise ValidationError(
            f"{label}: missing fields {sorted(missing)}, unknown fields {sorted(extra)}"
        )


def name(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,47}", value):
        raise ValidationError(f"{label}: use a lowercase name, digits and hyphens (max 48)")


def integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValidationError(f"{label} must be an integer between {low} and {high}")


def address(value):
    if not isinstance(value, str):
        raise ValidationError("IPv4 addresses must be dotted-decimal strings")
    try:
        ip = ipaddress.IPv4Address(value)
    except (ValueError, TypeError) as exc:
        raise ValidationError(f"Invalid IPv4 address: {value}") from exc
    if ip.is_multicast or ip.is_unspecified or ip.is_loopback or ip.is_reserved:
        raise ValidationError(f"Not a usable unicast address: {value}")
    return ip


def network(value):
    if not isinstance(value, str) or "/" not in value:
        raise ValidationError("Networks must be CIDR strings")
    try:
        return ipaddress.IPv4Network(value, strict=True)
    except (ValueError, TypeError) as exc:
        raise ValidationError(f"Invalid aligned IPv4 network: {value}") from exc


def usable(ip, net):
    return ip in net and (
        net.prefixlen >= 31 or ip not in (net.network_address, net.broadcast_address)
    )


def validate(data):
    fields(data, ("schema_version", "name", "image", "management", "nodes", "links"))
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValidationError("Only schema_version: 1 is supported")
    name(data["name"], "name")
    if not isinstance(data["image"], str) or not re.fullmatch(
        r"vios-[A-Za-z0-9._-]+", data["image"]
    ):
        raise ValidationError("image must be an EVE-NG vios- directory name")
    mgmt = data["management"]
    fields(mgmt, ("network", "bridge"), label="management")
    mgmt_net = network(mgmt["network"])
    if not 16 <= mgmt_net.prefixlen <= 29:
        raise ValidationError("management.network must have a /16 through /29 prefix")
    if not isinstance(mgmt["bridge"], str) or not re.fullmatch(r"pnet[1-9]", mgmt["bridge"]):
        raise ValidationError(
            "Use an isolated pnet1..pnet9 management bridge; pnet0 is not allowed"
        )
    nodes = data["nodes"]
    if not isinstance(nodes, list) or not 2 <= len(nodes) <= 20:
        raise ValidationError("nodes must contain between 2 and 20 routers")
    names, addresses = set(), set()
    loopbacks = []
    for node in nodes:
        fields(node, ("name", "management_ip", "loopback", "x", "y"), label="node")
        name(node["name"], "node.name")
        if node["name"] in names:
            raise ValidationError(f"Duplicate node: {node['name']}")
        names.add(node["name"])
        integer(node["x"], 0, 2000, "node.x")
        integer(node["y"], 0, 2000, "node.y")
        for key in ("management_ip", "loopback"):
            ip = address(node[key])
            if ip in addresses:
                raise ValidationError(f"Duplicate IP address: {ip}")
            addresses.add(ip)
        if not usable(address(node["management_ip"]), mgmt_net):
            raise ValidationError(
                f"{node['name']}: management IP is not a host in management.network"
            )
        if address(node["loopback"]) in mgmt_net:
            raise ValidationError("Loopbacks must not overlap management.network")
        loopbacks.append(address(node["loopback"]))
    links = data["links"]
    if not isinstance(links, list) or not links:
        raise ValidationError("links must be a non-empty list")
    used_ports, link_names, nets = set(), set(), [mgmt_net]
    graph = {n: set() for n in names}
    for link in links:
        fields(link, ("name", "subnet", "cost", "endpoints"), label="link")
        name(link["name"], "link.name")
        if link["name"] in link_names:
            raise ValidationError(f"Duplicate link: {link['name']}")
        link_names.add(link["name"])
        net = network(link["subnet"])
        if net.prefixlen not in (30, 31):
            raise ValidationError("Point-to-point links must use /30 or /31 subnets")
        if any(net.overlaps(other) for other in nets) or any(ip in net for ip in loopbacks):
            raise ValidationError(f"Overlapping link subnet: {net}")
        nets.append(net)
        integer(link["cost"], 1, 65535, "link.cost")
        endpoints = link["endpoints"]
        if not isinstance(endpoints, list) or len(endpoints) != 2:
            raise ValidationError("Each link needs exactly two endpoints")
        for ep in endpoints:
            fields(ep, ("node", "port", "ip"), label="endpoint")
            if not isinstance(ep["node"], str) or ep["node"] not in names:
                raise ValidationError(f"Unknown endpoint node: {ep['node']}")
            integer(ep["port"], 1, 3, "endpoint.port (0 is reserved for management)")
            port = (ep["node"], ep["port"])
            if port in used_ports:
                raise ValidationError(f"Interface reused: {port}")
            used_ports.add(port)
            ip = address(ep["ip"])
            if not usable(ip, net) or ip in addresses:
                raise ValidationError(f"Duplicate or invalid endpoint IP: {ip}")
            addresses.add(ip)
        a, b = (e["node"] for e in endpoints)
        if a == b:
            raise ValidationError("A link cannot connect a node to itself")
        graph[a].add(b)
        graph[b].add(a)
    visited, pending = set(), [nodes[0]["name"]]
    while pending:
        current = pending.pop()
        if current not in visited:
            visited.add(current)
            pending.extend(graph[current] - visited)
    if visited != names:
        raise ValidationError("The data-plane topology must be connected")
    return data


def load(path):
    try:
        source = Path(path).read_text(encoding="utf-8")
        if len(source) > 1_000_000:
            raise ValidationError("Scenario exceeds the 1 MB limit")
        data = yaml.load(source, Loader=UniqueLoader)
        return validate(data)
    except yaml.YAMLError as exc:
        raise ValidationError(f"Invalid YAML: {exc}") from exc
