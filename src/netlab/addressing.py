"""Deterministic IPv4 planning for an observed lab; no network or device writes."""

import hashlib
import ipaddress
import json
import re


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def interface_name(value):
    aliases = {
        "Gi": "GigabitEthernet",
        "Fa": "FastEthernet",
        "Eth": "Ethernet",
        "Et": "Ethernet",
        "Te": "TenGigabitEthernet",
        "Se": "Serial",
    }
    for short, full in aliases.items():
        if re.match(re.escape(short) + r"\d", value):
            value = full + value[len(short) :]
            break
    if not re.fullmatch(
        r"(?:GigabitEthernet|FastEthernet|Ethernet|TenGigabitEthernet|Serial)\d+(?:/\d+){0,3}",
        value,
    ):
        raise ValueError("Only physical IOS routed interfaces are supported: " + value)
    return value


def ipv4_network(value):
    try:
        net = ipaddress.IPv4Network(value, strict=True)
    except ValueError:
        raise ValueError(
            "Enter an IPv4 network with its prefix, for example 10.10.30.0/24."
        ) from None
    if (
        net.is_multicast
        or net.is_loopback
        or net.is_link_local
        or net.is_unspecified
        or int(net.broadcast_address) >= 0xE0000000
    ):
        raise ValueError("Use a unicast lab network, preferably RFC1918 private space.")
    return net


def endpoint_key(endpoint):
    return endpoint["node"] + "|" + endpoint["interface"]


def parse_ios_config(text):
    """Extract addressing only. Full configuration never goes into public reports."""
    text = text.replace("\r", "")
    if not re.search(r"(?m)^version \S+", text) or not re.search(r"(?m)^end\s*$", text):
        raise ValueError("Incomplete IOS configuration; no addressing changes are allowed.")
    result = {}
    for match in re.finditer(r"(?m)^interface (\S+)\n((?:[ \t].*\n|\n)*)", text + "\n"):
        name, body = match.groups()
        addresses = re.findall(
            r"(?m)^ ip address (\d+\.\d+\.\d+\.\d+) (\d+\.\d+\.\d+\.\d+)(.*)$", body
        )
        parsed = [str(ipaddress.IPv4Interface(a + "/" + mask)) for a, mask, _ in addresses]
        blocked = None
        try:
            interface_name(name)
        except ValueError:
            blocked = "Only physical routed interfaces are supported"
        if re.search(
            r"(?m)^ (?:switchport(?:\s|$)|(?:ip )?vrf |channel-group |ip unnumbered |encapsulation |ip address (?:dhcp|negotiated))",
            body,
        ):
            blocked = "Switchport, VRF, port-channel, dynamic or encapsulated interface"
        if len(parsed) > 1 or any(tail.strip() for _, _, tail in addresses):
            blocked = "Secondary or extended addressing is outside this preview"
        # Fail closed for any unparsed ip address command.
        if len(re.findall(r"(?m)^ ip address ", body)) != len(addresses):
            blocked = "Unrecognized IP configuration"
        result[name] = {
            "address": parsed[0] if parsed else None,
            "addresses": parsed,
            "shutdown": bool(re.search(r"(?m)^ shutdown\s*$", body)),
            "blocked": blocked,
        }
    if not result:
        raise ValueError("No IOS interfaces could be read")
    return result


def compile_addressing(snapshot, intent):
    """Preserve observed addresses; reserve every fixed subnet before filling gaps."""
    nodes = {n["id"]: n for n in snapshot["nodes"]}
    segments = {s["id"]: s for s in snapshot["segments"]}
    groups = intent.get("groups", {})
    choices = intent.get("segments", {})
    if not groups or not choices:
        raise ValueError("Add a group and select at least one segment.")
    pools = {}
    excluded = []
    for name, group in groups.items():
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,47}", name):
            raise ValueError(
                "Use a short group name containing letters, numbers, spaces or hyphens."
            )
        pool = ipv4_network(group["pool"])
        if any(pool.overlaps(other) for other in pools.values()):
            raise ValueError("Group pools overlap. Separate routing domains are not supported yet.")
        pools[name] = pool
        for value in group.get("exclude", []):
            net = ipv4_network(value)
            if not net.subnet_of(pool):
                raise ValueError("Reserved ranges must be inside their group pool.")
            excluded.append(net)
    observed = []
    for node in nodes.values():
        for name, current in node.get("interfaces", {}).items():
            for address in current.get("addresses", [current.get("address")]):
                if address:
                    observed.append((node["id"] + "|" + name, ipaddress.IPv4Interface(address)))
    rows, used_endpoints = [], set()
    for sid, choice in sorted(choices.items()):
        if sid not in segments:
            raise ValueError("A selected segment no longer exists. Read the lab again.")
        seg = segments[sid]
        if seg.get("blocked"):
            raise ValueError(seg["name"] + ": " + seg["blocked"])
        if seg.get("shared") and not choice.get("confirm_shared"):
            raise ValueError("Confirm the shared broadcast segment: " + seg["name"])
        if choice["group"] not in pools:
            raise ValueError("Select an existing group for each segment.")
        mapping = choice.get("interfaces", {})
        discovered_keys = {endpoint_key(ep) for ep in seg["endpoints"]}
        if set(mapping) - discovered_keys:
            raise ValueError("Interface mapping refers to an endpoint outside this segment.")
        endpoints = sorted(
            [
                {**ep, "interface": mapping.get(endpoint_key(ep), ep["interface"])}
                for ep in seg["endpoints"]
            ],
            key=endpoint_key,
        )
        if len(endpoints) < 2:
            raise ValueError("A segment needs at least two routed endpoints.")
        currents, keys = {}, set()
        for ep in endpoints:
            key = endpoint_key(ep)
            if key in used_endpoints or key in keys:
                raise ValueError("An interface cannot belong to two planned segments.")
            keys.add(key)
            node = nodes[ep["node"]]
            if node.get("error") or not node.get("config_hash"):
                raise ValueError(node["name"] + ": read a supported running IOS device first.")
            name = interface_name(ep["interface"])
            current = node.get("interfaces", {}).get(name)
            if current is None or current.get("blocked"):
                raise ValueError(
                    node["name"] + " " + name + ": interface is unavailable or unsupported."
                )
            currents[key] = current
        used_endpoints |= keys
        fixed = choice.get("fixed", {})
        if set(fixed) - keys:
            raise ValueError("A fixed address refers to an endpoint outside the segment.")
        preserved = [
            ipaddress.IPv4Interface(c["address"]).network
            for c in currents.values()
            if c.get("address")
        ]
        net = (
            ipv4_network(choice["subnet"])
            if choice.get("subnet")
            else (preserved[0] if preserved else None)
        )
        if any(old != net for old in preserved):
            raise ValueError(
                "Existing endpoint subnets disagree. This preview never renumbers them."
            )
        prefix = int(choice.get("prefix", 30))
        if not 1 <= prefix <= 31:
            raise ValueError("Choose a subnet prefix between /1 and /31.")
        if prefix == 31 and len(endpoints) != 2:
            raise ValueError("/31 is only available for two-endpoint links.")
        if net is not None and net.prefixlen == 31 and len(endpoints) != 2:
            raise ValueError("/31 cannot address a shared segment.")
        rows.append(
            {
                "segment": sid,
                "name": seg["name"],
                "group": choice["group"],
                "network": net,
                "prefix": prefix,
                "endpoints": endpoints,
                "currents": currents,
                "fixed": fixed,
                "keys": keys,
            }
        )
    reserved = list(excluded)
    # Fixed and preserved subnets get priority over automatic allocation.
    for row in rows:
        net = row["network"]
        if net is None:
            continue
        if not net.subnet_of(pools[row["group"]]):
            raise ValueError("Fixed or existing subnet is outside the selected group pool.")
        if any(net.overlaps(other) for other in reserved):
            raise ValueError("Fixed subnets overlap another segment or a reserved range.")
        if any(net.overlaps(ip.network) for key, ip in observed if key not in row["keys"]):
            raise ValueError("Subnet conflicts with an observed interface outside this segment.")
        reserved.append(net)
    for row in rows:
        if row["network"] is not None:
            continue
        pool = pools[row["group"]]
        prefix = row["prefix"]
        if prefix < pool.prefixlen:
            raise ValueError("The requested subnet is larger than its group pool.")
        size = 1 << (32 - prefix)
        candidate = int(pool.network_address)
        obstacles = reserved + [ip.network for _, ip in observed]
        for obstacle in sorted(obstacles, key=lambda n: int(n.network_address)):
            if int(obstacle.broadcast_address) < candidate:
                continue
            if candidate + size - 1 < int(obstacle.network_address):
                break
            candidate = ((int(obstacle.broadcast_address) + 1 + size - 1) // size) * size
        if candidate + size - 1 > int(pool.broadcast_address):
            raise ValueError(
                "Pool exhausted for group "
                + row["group"]
                + ". Use a larger pool or smaller subnet."
            )
        row["network"] = ipaddress.IPv4Network((candidate, prefix))
        reserved.append(row["network"])
    result, changes = [], []
    for row in rows:
        net, assigned = row["network"], {}
        low = int(net.network_address) + (0 if net.prefixlen == 31 else 1)
        high = int(net.broadcast_address) - (0 if net.prefixlen == 31 else 1)
        if high - low + 1 < len(row["endpoints"]):
            raise ValueError("Subnet is too small for " + row["name"])
        for ep in row["endpoints"]:
            key = endpoint_key(ep)
            old = row["currents"][key].get("address")
            pinned = row["fixed"].get(key)
            if pinned:
                pinned = ipaddress.IPv4Address(pinned)
            if old:
                address = ipaddress.IPv4Interface(old).ip
                if pinned and pinned != address:
                    raise ValueError(
                        "Existing IP addresses are preserved; renumbering is not supported."
                    )
            else:
                address = pinned
            if address is not None:
                if not low <= int(address) <= high or address in assigned.values():
                    raise ValueError(
                        "Fixed IP is duplicated, outside the subnet, or not a usable host."
                    )
                assigned[key] = address
        candidate = low
        for ep in row["endpoints"]:
            key = endpoint_key(ep)
            if key not in assigned:
                while ipaddress.IPv4Address(candidate) in assigned.values():
                    candidate += 1
                assigned[key] = ipaddress.IPv4Address(candidate)
            before = row["currents"][key]
            after = str(assigned[key]) + "/" + str(net.prefixlen)
            changes.append(
                {
                    **ep,
                    "device": nodes[ep["node"]]["name"],
                    "segment": row["segment"],
                    "group": row["group"],
                    "before": before.get("address"),
                    "after": after,
                    "shutdown": before["shutdown"],
                    "change": not bool(before.get("address")),
                }
            )
        result.append(
            {"id": row["segment"], "name": row["name"], "group": row["group"], "subnet": str(net)}
        )
    return {
        "schema": "nlf-existing-addressing-v1",
        "lab": snapshot["lab"],
        "snapshot_hash": digest(snapshot),
        "intent": intent,
        "segments": result,
        "changes": changes,
    }


def config_commands(changes):
    """Only additive address commands; shutdown state remains untouched."""
    commands = []
    for change in changes:
        if change["change"]:
            ip = ipaddress.IPv4Interface(change["after"])
            commands += [
                "interface " + interface_name(change["interface"]),
                "ip address " + str(ip.ip) + " " + str(ip.netmask),
                "exit",
            ]
    return ["configure terminal", *commands, "end"] if commands else []
