"""Executable minimum variants of the 24 documented workshop scenarios.

Base and exercise are separate command streams; reference includes both.
Checks collect observations, never infer success from generated configuration.
"""

import ipaddress
import re

from .catalog import Recipe


def peer_ip(r, node, iface):
    net = r.plan["networks"][iface["network"] - 1]
    peer = next(e["node"] for e in net["endpoints"] if e["node"] != node)
    return next(i["ip"] for i in r.nodes[peer]["interfaces"] if i["network"] == net["id"])


def lan(r, router, host, subnet, *, x=0, y=0):
    n = r.node(host, "vpcs", x, y, loop=False)
    ri, hi = r.connect(router, host)
    net = ipaddress.IPv4Network(subnet)
    gw = str(net.network_address + 1)
    ip = str(net.network_address + 10)
    ri.update(ip=gw, prefix=net.prefixlen, passive=True)
    hi.update(ip=ip, prefix=net.prefixlen)
    r.interface(router, ri["name"], [f"ip address {gw} {net.netmask}", "no shutdown"])
    n["base"] += [f"ip {ip}/{net.prefixlen} {gw}"]
    n["ip"] = ip
    r.ping(host, gw, "preparation")
    return n, ri


def static_route(r, node, network, next_hop, solution=True):
    net = ipaddress.IPv4Network(network)
    r.nodes[node]["solution" if solution else "base"] += [
        f"ip route {net.network_address} {net.netmask} {next_hop}"
    ]


def bgp(r, node, asn, peers, prefixes, solution=True):
    n = r.nodes[node]
    dest = n["solution" if solution else "base"]
    dest += [f"router bgp {asn}", f"bgp router-id {n['loopback']}", "bgp log-neighbor-changes"]
    for addr, remote in peers:
        dest += [f"neighbor {addr} remote-as {remote}"]
    for prefix in prefixes:
        net = ipaddress.IPv4Network(prefix)
        dest += [f"network {net.network_address} mask {net.netmask}"]
    dest += ["exit"]
    for addr, _ in peers:
        r.check(
            node,
            f"show ip bgp neighbors {addr}",
            r"BGP state = Established",
            "exercise" if solution else "preparation",
        )


def basic_routing(r, sid):
    if sid in ("B01", "A07"):
        for i in (1, 2):
            r.node(f"r0{i}", x=180 + (i - 1) * 460, y=220)
        r.connect("r01", "r02", routed=True)
        r.ospf()
        for a, b in (("r01", "r02"), ("r02", "r01")):
            r.ping(a, r.nodes[b]["loopback"])
        if sid == "A07":
            # A fresh reference baseline is deployed. Fault injection is an explicit action.
            r.plan["mode"] = "reference"
            iface = r.nodes["r01"]["interfaces"][0]["name"]
            r.plan["actions"] = [
                {
                    "id": "fault",
                    "label": "Introducir falla en enlace",
                    "node": "r01",
                    "commands": ["configure terminal", "interface " + iface, "shutdown", "end"],
                    "inverse": ["configure terminal", "interface " + iface, "no shutdown", "end"],
                }
            ]
            r.plan["exercise"] = "Diagnosticar y reparar una falla después de comprobar la base."
    elif sid == "B02":
        for i in (1, 2):
            r.node(f"r0{i}", x=330 + (i - 1) * 340, y=220)
        a, b = r.connect("r01", "r02", routed=True)
        networks = [str(next(r.lans)) for _ in range(2)]
        for i, network in enumerate(networks, 1):
            lan(r, f"r0{i}", f"h0{i}", network, x=100 + (i - 1) * 800, y=220)
        static_route(r, "r01", networks[1], b["ip"])
        static_route(r, "r02", networks[0], a["ip"])
        r.ping("h01", r.nodes["h02"]["ip"])
        r.ping("h02", r.nodes["h01"]["ip"])
        for a, b in (("r01", networks[1]), ("r02", networks[0])):
            r.check(a, "show ip route static", r"S\s+" + re.escape(b.split("/")[0]))


def switching(r, sid):
    count = 3 if sid == "B06" else 4 if sid == "B07" else 2
    coords = {
        2: [(200, 180), (700, 180)],
        3: [(450, 100), (150, 380), (750, 380)],
        4: [(180, 130), (720, 130), (720, 430), (180, 430)],
    }
    for i, (x, y) in enumerate(coords[count], 1):
        r.node(f"sw0{i}", "iosvl2", x, y, loop=False)
    names = list(r.nodes)
    r.vlans(names, (100, 101) if sid == "B03" else (100,))
    if sid == "B03":
        a, b = r.connect("sw01", "sw02", label="Trunk VLAN 100,101")
        for n, i in (("sw01", a), ("sw02", b)):
            r.trunk(n, i["name"], solution=True)
        # One IP prefix across separate broadcast domains makes the negative
        # probe detect accidental VLAN merging instead of merely absent routing.
        subnet = str(next(r.lans))
        for i, (sw, vlan, ordinal, x) in enumerate(
            [
                ("sw01", 100, 10, 80),
                ("sw01", 101, 20, 310),
                ("sw02", 100, 11, 590),
                ("sw02", 101, 21, 820),
            ],
            1,
        ):
            r.host(f"h0{i}", sw, vlan, subnet, ordinal, x=x, y=400)
        for a, b in (("h01", "h03"), ("h02", "h04")):
            r.ping(a, r.nodes[b]["ip"])
            r.ping(b, r.nodes[a]["ip"])
        r.ping("h01", r.nodes["h02"]["ip"], negative=True)
        r.check("sw01", "show interfaces trunk", r"100[,-]101")
    else:
        pairs = (
            [("sw01", "sw02"), ("sw01", "sw02")]
            if count == 2
            else [(names[i], names[(i + 1) % count]) for i in range(count)]
        )
        for a, b in pairs:
            ia, ib = r.connect(a, b, label="Po1" if sid == "B04" else "STP VLAN 100")
            for node, i in ((a, ia), (b, ib)):
                if sid == "B04":
                    r.interface(node, i["name"], ["shutdown"])
                    r.interface(
                        node,
                        i["name"],
                        [
                            "switchport trunk encapsulation dot1q",
                            "switchport mode trunk",
                            "switchport trunk allowed vlan 100",
                            "channel-group 1 mode active",
                            "no shutdown",
                        ],
                        True,
                    )
                else:
                    r.trunk(node, i["name"], "100")
        if sid == "B04":
            for node in names:
                r.trunk(node, "Port-channel1", "100", True)
                r.check(node, "show etherchannel summary", r"Po1\(SU\).*LACP.*\(P\).*\(P\)")
            i = r.nodes["sw01"]["interfaces"][0]["name"]
            r.plan["actions"] = [
                {
                    "id": "fault",
                    "label": "Cortar un enlace de Po1 en ambos extremos",
                    "node": "sw01",
                    "commands": ["configure terminal", "interface " + i, "shutdown", "end"],
                    "inverse": ["configure terminal", "interface " + i, "no shutdown", "end"],
                    "peer": {
                        "node": "sw02",
                        "commands": [
                            "configure terminal",
                            "interface " + r.nodes["sw02"]["interfaces"][0]["name"],
                            "shutdown",
                            "end",
                        ],
                        "inverse": [
                            "configure terminal",
                            "interface " + r.nodes["sw02"]["interfaces"][0]["name"],
                            "no shutdown",
                            "end",
                        ],
                    },
                }
            ]
        else:
            r.nodes["sw01"]["solution"] += ["spanning-tree vlan 100 priority 4096"]
            for node in names[1:]:
                r.nodes[node]["solution"] += ["spanning-tree vlan 100 priority 32768"]
            r.check("sw01", "show spanning-tree vlan 100", r"This bridge is the root")
            # At least one alternate is expected across the graph, not on every switch.
            r.check(names[-1], "show spanning-tree vlan 100", r"(?:Altn\s+BLK|Root\s+FWD)")
            for node in names:
                r.check(
                    node, "show spanning-tree vlan 100", r"Spanning tree enabled", "preparation"
                )
        network = str(next(r.lans))
        r.host("h01", names[0], 100, network, 10, x=70, y=570)
        r.host("h02", names[-1], 100, network, 11, x=830, y=570)
        r.ping("h01", r.nodes["h02"]["ip"])
        r.ping("h02", r.nodes["h01"]["ip"])


def inter_vlan(r):
    r.node("r01", x=200, y=180)
    r.node("sw01", "iosvl2", 500, 180, loop=False)
    ri, si = r.connect("r01", "sw01", label="Trunk VLAN 100,101")
    r.vlans(["sw01"])
    r.trunk("sw01", si["name"])
    r.interface("r01", ri["name"], ["no shutdown"])
    for i, v in enumerate((100, 101), 1):
        net = next(r.lans)
        gw = str(net.network_address + 1)
        r.host(f"h0{i}", "sw01", v, str(net), gateway=gw, x=800, y=100 + i * 170)
        r.interface(
            "r01",
            ri["name"] + f".{v}",
            [f"encapsulation dot1Q {v}", f"ip address {gw} {net.netmask}"],
            True,
        )
        r.ping(f"h0{i}", gw)
    r.ping("h01", r.nodes["h02"]["ip"])
    r.ping("h02", r.nodes["h01"]["ip"])


def ospf_network(r, sid):
    if sid == "I01":
        r.node("core01", "iosvl2", 450, 60)
        for name, x, y in [
            ("dist01", 200, 240),
            ("dist02", 700, 240),
            ("acc01", 200, 440),
            ("acc02", 700, 440),
        ]:
            r.node(name, "iosvl2", x, y, loop=name.startswith("dist"))
        for a, b in [("core01", "dist01"), ("core01", "dist02"), ("dist01", "dist02")]:
            r.connect(a, b, routed=True)
        r.vlans(["dist01", "dist02", "acc01", "acc02"], (100, 101))
        for a in ("acc01", "acc02"):
            for d in ("dist01", "dist02"):
                ia, id_ = r.connect(a, d, label="Trunk")
                r.trunk(a, ia["name"])
                r.trunk(d, id_["name"])
        # Distinct gateway per LAN; redundancy is a separate scenario I04.
        nets = []
        for i, d in enumerate(("dist01", "dist02")):
            net = next(r.lans)
            nets.append(net)
            gw = str(net.network_address + 1)
            r.interface(d, f"Vlan{100 + i}", [f"ip address {gw} {net.netmask}", "no shutdown"])
            r.nodes[d]["base"] += ["ip routing"]
            r.host(
                f"h0{i + 1}", f"acc0{i + 1}", 100 + i, str(net), gateway=gw, x=200 + i * 500, y=620
            )
        r.ospf(["core01", "dist01", "dist02"])
        for i, d in enumerate(("dist01", "dist02")):
            r.interface(d, f"Vlan{100 + i}", ["ip ospf 1 area 0"], True)
        r.ping("h01", r.nodes["h02"]["ip"])
        r.ping("h02", r.nodes["h01"]["ip"])
        r.plan["exercise"] = (
            "Configurar OSPF entre distribución y núcleo; las VLAN y gateways ya están preparados."
        )
    else:
        positions = (
            [(100, 250), (380, 250), (660, 250), (940, 250)]
            if sid == "I02"
            else [(130, 260), (500, 100), (500, 440), (870, 260)]
        )
        for i, (x, y) in enumerate(positions, 1):
            r.node(f"r0{i}", x=x, y=y)
        pairs = (
            [("r01", "r02", 10), ("r02", "r03", 0), ("r03", "r04", 20)]
            if sid == "I02"
            else [("r01", "r02", 0), ("r02", "r04", 0), ("r01", "r03", 0), ("r03", "r04", 0)]
        )
        for a, b, area in pairs:
            r.connect(a, b, routed=True, area=area)
        r.ospf()
        if sid == "I02":
            # Loopbacks belong to an attached area; do not create disconnected area 0 islands.
            for n, area in [("r01", 10), ("r04", 20)]:
                lines = r.nodes[n]["solution"]
                pos = len(lines) - 1
                while lines[pos] != "interface Loopback0":
                    pos -= 1
                lines[pos + 1] = f"ip ospf 1 area {area}"
            r.check("r01", "show ip route ospf", r"O IA\s+" + re.escape(r.nodes["r04"]["loopback"]))
        else:
            for name, n in r.nodes.items():
                for iface in n["interfaces"]:
                    endpoints = r.plan["networks"][iface["network"] - 1]["endpoints"]
                    backup = any(e["node"] == "r03" for e in endpoints)
                    r.interface(n, iface["name"], [f"ip ospf cost {100 if backup else 10}"], True)
            i = r.nodes["r01"]["interfaces"][0]["name"]
            r.plan["actions"] = [
                {
                    "id": "fault",
                    "label": "Cortar WAN principal",
                    "node": "r01",
                    "commands": ["configure terminal", "interface " + i, "shutdown", "end"],
                    "inverse": ["configure terminal", "interface " + i, "no shutdown", "end"],
                }
            ]
        for a, b in [("r01", "r04"), ("r04", "r01")]:
            r.ping(a, r.nodes[b]["loopback"])


def gateway(r):
    for n, x in [("gw01", 200), ("gw02", 700)]:
        r.node(n, "iosvl2", x, 100, loop=False)
    r.node("sw01", "iosvl2", 450, 320, loop=False)
    r.vlans(list(r.nodes), (100,))
    net = next(r.lans)
    vip = str(net.network_address + 1)
    for j, n in enumerate(("gw01", "gw02"), 2):
        a, b = r.connect(n, "sw01", label="VLAN 100")
        for name, iface in ((n, a), ("sw01", b)):
            r.trunk(name, iface["name"], "100")
        r.nodes[n]["base"] += ["ip routing"]
        r.interface(
            n, "Vlan100", [f"ip address {net.network_address + j} {net.netmask}", "no shutdown"]
        )
        r.interface(
            n,
            "Vlan100",
            [
                f"standby 100 ip {vip}",
                f"standby 100 priority {120 if j == 2 else 100}",
                "standby 100 preempt",
            ],
            True,
        )
        r.check(
            n,
            "show standby brief",
            r"\b" + ("Active" if j == 2 else "Standby") + r"\b.*" + re.escape(vip),
        )
    for j in (1, 2):
        r.host(f"h0{j}", "sw01", 100, str(net), 9 + j, vip, x=200 + (j - 1) * 500, y=520)
    for h in ("h01", "h02"):
        r.ping(h, vip)


def bgp_chain(r):
    for j in (1, 2, 3):
        r.node(f"r0{j}", x=150 + (j - 1) * 350, y=240)
    r.connect("r01", "r02", routed=True)
    r.connect("r02", "r03", routed=True)
    for name, n in r.nodes.items():
        peers = []
        for iface in n["interfaces"]:
            net = r.plan["networks"][iface["network"] - 1]
            peer = next(e["node"] for e in net["endpoints"] if e["node"] != name)
            peers.append((peer_ip(r, name, iface), 65000 + int(peer[-1])))
        bgp(r, name, 65000 + int(name[-1]), peers, [n["loopback"] + "/32"])
    for a, b in [("r01", "r03"), ("r03", "r01")]:
        r.ping(a, r.nodes[b]["loopback"], source="Loopback0")


def vrf(r):
    for j in (1, 2):
        r.node(f"r0{j}", x=300 + (j - 1) * 400, y=250, loop=False)
    a, b = r.connect("r01", "r02", label="VRF A / B · dot1Q 100/101")
    nets = [next(r.lans) for _ in range(2)]
    transit = next(r.transits)  # Reused only inside independent VRFs.
    for j, n in enumerate(("r01", "r02")):
        trunk = (a, b)[j]
        r.interface(n, trunk["name"], ["no shutdown"])
        for k, vrf_name in enumerate(("A", "B")):
            r.nodes[n]["solution"] += [f"ip vrf {vrf_name}", f"rd 65001:{100 + k}", "exit"]
            r.interface(
                n,
                trunk["name"] + f".{100 + k}",
                [
                    f"encapsulation dot1Q {100 + k}",
                    f"ip vrf forwarding {vrf_name}",
                    f"ip address {transit.network_address + j + 1} {transit.netmask}",
                ],
                True,
            )
            host = f"h0{j * 2 + k + 1}"
            h = r.node(host, "vpcs", 80 + j * 840, 120 + k * 260, loop=False)
            ri, hi = r.connect(n, host, label="VRF " + vrf_name)
            net = nets[j]
            gw = str(net.network_address + 1)
            addr = str(net.network_address + 10)
            h["base"] += [f"ip {addr}/24 {gw}"]
            h["ip"] = addr
            hi.update(ip=addr, prefix=24, vrf=vrf_name)
            ri.update(ip=gw, prefix=24, vrf=vrf_name)
            r.interface(
                n,
                ri["name"],
                [f"ip vrf forwarding {vrf_name}", f"ip address {gw} {net.netmask}", "no shutdown"],
                True,
            )
            other = nets[1 - j]
            r.nodes[n]["solution"] += [
                f"ip route vrf {vrf_name} {other.network_address} {other.netmask} {transit.network_address + 2 - j}"
            ]
            r.check(n, f"show ip route vrf {vrf_name}", re.escape(str(other.network_address)))
    # Same addresses in each VRF intentionally: verify isolation by interface/table membership.
    r.ping("h01", r.nodes["h03"]["ip"])
    r.ping("h02", r.nodes["h04"]["ip"])
    for n in ("r01", "r02"):
        r.check(n, "show ip vrf interfaces", r"\bA\b[\s\S]*\bB\b")
    for n in ("r01", "r02"):
        addresses = {v: str(next(r.loops)) for v in ("A", "B")}
        for j, v in enumerate(("A", "B"), 100):
            r.interface(
                n,
                f"Loopback{j}",
                [f"ip vrf forwarding {v}", f"ip address {addresses[v]} 255.255.255.255"],
                True,
            )
            r.check(
                n,
                f"ping vrf {v} {addresses[v]} repeat 3 timeout 1",
                "",
                kind="ping",
                label="Control local VRF " + v,
            )
        r.check(
            n,
            f"ping vrf A {addresses['B']} repeat 3 timeout 1",
            "",
            kind="unreachable",
            label="Aislado de VRF B",
        )


def acl_nat(r):
    r.node("sw01", "iosvl2", 250, 260, loop=False)
    r.node("r01", x=480, y=260)
    r.node("r02", x=720, y=260)
    inside = next(r.lans)
    outside = next(r.lans)
    r.vlans(["sw01"], (100,))
    ri, si = r.connect("r01", "sw01")
    r.interface(
        "sw01", si["name"], ["switchport mode access", "switchport access vlan 100", "no shutdown"]
    )
    ri.update(ip=str(inside.network_address + 1), prefix=24)
    r.interface("r01", ri["name"], [f"ip address {ri['ip']} {inside.netmask}", "no shutdown"])
    a, b = r.connect("r01", "r02", routed=True)
    for j in (1, 2):
        r.host(f"h0{j}", "sw01", 100, str(inside), 9 + j, ri["ip"], x=60, y=100 + j * 220)
    h, _external = lan(r, "r02", "srv01", str(outside), x=950, y=260)
    static_route(r, "r01", str(outside), b["ip"], False)
    static_route(r, "r02", str(inside), a["ip"], False)
    for host in ("h01", "h02"):
        r.ping(host, ri["ip"], "preparation")
    r.nodes["r01"]["solution"] += [
        "ip access-list extended LAB-IN",
        f"permit icmp host {r.nodes['h01']['ip']} host {h['ip']}",
        f"deny icmp host {r.nodes['h02']['ip']} host {h['ip']}",
        "permit ip any any",
        "exit",
        f"access-list 10 permit {inside.network_address} {inside.hostmask}",
        f"ip nat inside source list 10 interface {a['name']} overload",
    ]
    r.interface("r01", ri["name"], ["ip nat inside", "ip access-group LAB-IN in"], True)
    r.interface("r01", a["name"], ["ip nat outside"], True)
    r.ping("h01", h["ip"])
    r.ping("h02", h["ip"], negative=True)
    r.check("r01", "show ip nat translations", r"icmp\s+")
    r.plan["exercise"] = (
        "Permitir ICMP de H01, bloquear ICMP de H02 hacia SRV01 y aplicar PAT sobre la interfaz WAN."
    )


def ipv6(r):
    for j in (1, 2, 3):
        r.node(f"r0{j}", x=250 + (j - 1) * 250, y=250)
    r.connect("r01", "r02", routed=True)
    r.connect("r02", "r03", routed=True)
    for j, router in ((1, "r01"), (2, "r03")):
        lan(r, router, f"h0{j}", str(next(r.lans)), x=50 + (j - 1) * 900, y=250)
    for network in r.plan["networks"]:
        subnet = ipaddress.IPv6Network(f"fd42:4e4c:4600:{network['id']}::/64")
        for k, ep in enumerate(network["endpoints"], 1):
            n = r.nodes[ep["node"]]
            addr = str(subnet.network_address + k)
            n.setdefault("ipv6", []).append(addr)
            if n["profile"] == "vpcs":
                n["base"] += [f"ip {addr}/64"]
            else:
                r.nodes[n["name"]]["base"] += ["ipv6 unicast-routing"]
                r.interface(n, ep["interface"], [f"ipv6 address {addr}/64"])
                r.interface(n, ep["interface"], ["ipv6 ospf 1 area 0"], True)
    for n in ("r01", "r02", "r03"):
        r.nodes[n]["solution"] += [
            "ipv6 router ospf 1",
            f"router-id {r.nodes[n]['loopback']}",
            "exit",
        ]
        r.check(n, "show ipv6 ospf neighbor", r"FULL")
    r.ospf(["r01", "r02", "r03"])
    for a, b in [("h01", "h02"), ("h02", "h01")]:
        r.ping(a, r.nodes[b]["ip"])
        r.ping(a, r.nodes[b]["ipv6"][0])
    r.plan["exercise"] = "Configurar OSPFv2 y OSPFv3; verificar IPv4 e IPv6 de forma independiente."


def nexus_vpc(r):
    r.node("nx01", "nxos", 200, 150)
    r.node("nx02", "nxos", 700, 150)
    r.node("sw01", "iosvl2", 450, 450, loop=False)
    a, b = r.connect("nx01", "nx02", routed=True, label="Keepalive dedicado")
    pa, pb = r.connect("nx01", "nx02", label="Peer-link Po10")
    for node, peer, iface in [("nx01", b, pa), ("nx02", a, pb)]:
        n = r.nodes[node]
        n["base"] += ["feature lacp", "vlan 100", "exit"]
        n["solution"] += [
            "feature vpc",
            "vpc domain 10",
            f"peer-keepalive destination {peer['ip']} source {a['ip'] if node == 'nx01' else b['ip']} vrf default",
            "exit",
        ]
        r.interface(
            node,
            iface["name"],
            [
                "switchport",
                "switchport mode trunk",
                "switchport trunk allowed vlan 100",
                "channel-group 10 mode active",
                "no shutdown",
            ],
            True,
        )
        r.interface(
            node,
            "port-channel10",
            [
                "switchport",
                "switchport mode trunk",
                "switchport trunk allowed vlan 100",
                "vpc peer-link",
                "no shutdown",
            ],
            True,
        )
        ni, si = r.connect(node, "sw01", label="vPC1 / Po1")
        r.interface(
            node,
            ni["name"],
            [
                "switchport",
                "switchport mode trunk",
                "switchport trunk allowed vlan 100",
                "channel-group 1 mode active",
                "no shutdown",
            ],
            True,
        )
        r.interface(
            node,
            "port-channel1",
            [
                "switchport",
                "switchport mode trunk",
                "switchport trunk allowed vlan 100",
                "vpc 1",
                "no shutdown",
            ],
            True,
        )
        r.interface("sw01", si["name"], ["shutdown"])
        r.interface(
            "sw01",
            si["name"],
            [
                "switchport trunk encapsulation dot1q",
                "switchport mode trunk",
                "switchport trunk allowed vlan 100",
                "channel-group 1 mode active",
                "no shutdown",
            ],
            True,
        )
        r.check(node, "show vpc brief", r"peer adjacency formed ok")
        r.check(node, "show port-channel summary", r"Po1\(SU\)")
    r.vlans(["sw01"], (100,))
    r.trunk("sw01", "Port-channel1", "100", True)
    net = next(r.lans)
    r.host("h01", "sw01", 100, str(net), 10, x=450, y=640)
    for j, node in enumerate(("nx01", "nx02"), 1):
        r.nodes[node]["base"] += ["feature interface-vlan"]
        r.interface(
            node, "Vlan100", [f"ip address {net.network_address + j}/24", "no shutdown"], True
        )
        r.ping("h01", str(net.network_address + j))


def evpn(r):
    for name, x, y in [
        ("spine01", 220, 90),
        ("spine02", 700, 90),
        ("leaf01", 220, 330),
        ("leaf02", 700, 330),
    ]:
        r.node(name, "nxos", x, y)
    for leaf in ("leaf01", "leaf02"):
        for spine in ("spine01", "spine02"):
            r.connect(leaf, spine, routed=True)
    r.ospf(solution=False)
    # iBGP EVPN with spine route reflectors; ingress replication avoids multicast dependencies.
    for name, n in r.nodes.items():
        n["solution"] += [
            "feature bgp",
            "nv overlay evpn",
            "router bgp 65000",
            f"router-id {n['loopback']}",
        ]
        peers = ["leaf01", "leaf02"] if name.startswith("spine") else ["spine01", "spine02"]
        for peer in peers:
            n["solution"] += [
                f"neighbor {r.nodes[peer]['loopback']}",
                "remote-as 65000",
                "update-source loopback0",
                "address-family l2vpn evpn",
                "send-community both",
            ]
            if name.startswith("spine"):
                n["solution"] += ["route-reflector-client"]
            n["solution"] += ["exit", "exit"]
        n["solution"] += ["exit"]
        r.check(name, "show bgp l2vpn evpn summary", r"\d+\.\d+\.\d+\.\d+\s+4\s+65000.*\s\d+\s*$")
    net = next(r.lans)
    for j, leaf in enumerate(("leaf01", "leaf02"), 1):
        n = r.nodes[leaf]
        n["solution"] += [
            "feature nv overlay",
            "feature vn-segment-vlan-based",
            "vlan 100",
            "vn-segment 10100",
            "exit",
            "interface nve1",
            "no shutdown",
            "host-reachability protocol bgp",
            "source-interface loopback0",
            "member vni 10100",
            "ingress-replication protocol bgp",
            "exit",
            "exit",
            "evpn",
            "vni 10100 l2",
            "rd auto",
            "route-target import auto",
            "route-target export auto",
            "exit",
            "exit",
        ]
        # A full IOS IP stack avoids the observed VPCS/9000v ARP reply mismatch.
        # These endpoints do not route; bidirectional overlay probes remain mandatory.
        host = r.node(f"h0{j}", "iosv", 220 + (j - 1) * 480, 560, loop=False)
        host["role"] = "endpoint"
        host["base"] += ["no ip routing"]
        ni, hi = r.connect(leaf, host["name"], label="VLAN 100 / VNI 10100")
        ip = str(net.network_address + 9 + j)
        r.interface(host, hi["name"], [f"ip address {ip} 255.255.255.0", "no shutdown"])
        host["ip"] = ip
        r.interface(
            leaf,
            ni["name"],
            ["switchport", "switchport mode access", "switchport access vlan 100", "no shutdown"],
            True,
        )
        r.check(leaf, "show nve peers", r"\bUp\b")
    for a, b in [("h01", "h02"), ("h02", "h01")]:
        r.ping(a, r.nodes[b]["ip"])


def mpls(r):
    for name, x in [("ce01", 80), ("pe01", 290), ("p01", 500), ("pe02", 710), ("ce02", 920)]:
        r.node(name, "csr", x, 250)
    r.connect("pe01", "p01", routed=True)
    r.connect("p01", "pe02", routed=True)
    r.ospf(["pe01", "p01", "pe02"], solution=False)
    for name in ("pe01", "p01", "pe02"):
        n = r.nodes[name]
        n["solution"] += [
            "mpls ip",
            "mpls label protocol ldp",
            "mpls ldp router-id Loopback0 force",
        ]
        for iface in list(n["interfaces"]):
            r.interface(name, iface["name"], ["mpls ip"], True)
        r.check(name, "show mpls ldp neighbor", r"Peer LDP Ident:")
    for j in (1, 2):
        pe, ce = f"pe0{j}", f"ce0{j}"
        pi, ci = r.connect(pe, ce, routed=True)
        n = r.nodes[pe]
        n["solution"] += ["ip vrf CUSTOMER", "rd 65000:100", "route-target both 65000:100", "exit"]
        r.interface(
            pe,
            pi["name"],
            ["ip vrf forwarding CUSTOMER", f"ip address {pi['ip']} 255.255.255.252", "no shutdown"],
            True,
        )
        n["solution"] += [
            f"ip route vrf CUSTOMER {r.nodes[ce]['loopback']} 255.255.255.255 {ci['ip']}",
            "router bgp 65000",
            f"neighbor {r.nodes[f'pe0{3 - j}']['loopback']} remote-as 65000",
            f"neighbor {r.nodes[f'pe0{3 - j}']['loopback']} update-source Loopback0",
            "address-family vpnv4",
            f"neighbor {r.nodes[f'pe0{3 - j}']['loopback']} activate",
            f"neighbor {r.nodes[f'pe0{3 - j}']['loopback']} send-community extended",
            "exit-address-family",
            "address-family ipv4 vrf CUSTOMER",
            "redistribute static",
            "exit-address-family",
            "exit",
        ]
        static_route(r, ce, "0.0.0.0/0", pi["ip"], False)
        # Access remains reachable after it moves into a VRF; global ping is not a valid prep probe.
        r.plan["checks"]["preparation"] = [
            c
            for c in r.plan["checks"]["preparation"]
            if not (c["node"] == pe and c["command"].startswith("ping " + ci["ip"]))
        ]
        r.check(pe, "show ip bgp vpnv4 all summary", r"65000.*\s\d+\s*$")
    for a, b in [("ce01", "ce02"), ("ce02", "ce01")]:
        r.check(
            a,
            f"ping {r.nodes[b]['loopback']} source Loopback0 repeat 3 timeout 1",
            "",
            kind="ping",
            label="Alcance entre loopbacks del cliente a través de la VPN",
        )


def redistribution(r):
    for j in range(1, 5):
        r.node(f"r0{j}", x=100 + (j - 1) * 270, y=250)
    r.connect("r01", "r02", routed=True)
    r.connect("r02", "r03", routed=True)
    r.connect("r03", "r04", routed=True)
    # R02 is the sole boundary in the minimum variant. OSPF left, EIGRP right.
    r.ospf(["r01", "r02"], solution=False)
    boundary = r.nodes["r02"]["interfaces"][1]
    r.nodes["r02"]["base"] += ["interface " + boundary["name"], "no ip ospf 1 area 0", "exit"]
    for name in ("r02", "r03", "r04"):
        n = r.nodes[name]
        n["base"] += ["router eigrp 100", "no auto-summary"]
        for i in n["interfaces"]:
            if name == "r02" and i is not boundary:
                continue
            n["base"] += [f"network {i['ip']} 0.0.0.0"]
        if name != "r02":
            n["base"] += [f"network {n['loopback']} 0.0.0.0"]
        n["base"] += ["exit"]
    # Remove the impossible OSPF adjacency check for the EIGRP-facing link (not generated).
    r.nodes["r02"]["solution"] += [
        "route-map EIGRP-TO-OSPF deny 10",
        "match tag 200",
        "exit",
        "route-map EIGRP-TO-OSPF permit 20",
        "set tag 100",
        "exit",
        "route-map OSPF-TO-EIGRP deny 10",
        "match tag 100",
        "exit",
        "route-map OSPF-TO-EIGRP permit 20",
        "set tag 200",
        "exit",
        "router ospf 1",
        "redistribute eigrp 100 subnets route-map EIGRP-TO-OSPF",
        "exit",
        "router eigrp 100",
        "redistribute ospf 1 metric 10000 100 255 1 1500 route-map OSPF-TO-EIGRP",
        "exit",
    ]
    r.check("r01", "show ip route", r"O E2\s+" + re.escape(r.nodes["r04"]["loopback"]))
    r.check("r04", "show ip route", r"D EX\s+" + re.escape(r.nodes["r01"]["loopback"]))
    for a, b in [("r01", "r04"), ("r04", "r01")]:
        r.ping(a, r.nodes[b]["loopback"])


def multihoming(r):
    for name, x, y in [
        ("isp01", 180, 100),
        ("isp02", 750, 100),
        ("edge01", 180, 330),
        ("edge02", 750, 330),
    ]:
        r.node(name, x=x, y=y)
    a, b = r.connect("edge01", "isp01", routed=True)
    c, d = r.connect("edge02", "isp02", routed=True)
    e, f = r.connect("edge01", "edge02", routed=True)
    # Synthetic destination is reachable behind both simulated providers.
    remote = "10.244.0.1"
    for isp in ("isp01", "isp02"):
        r.interface(isp, "Loopback10", [f"ip address {remote} 255.255.255.255"])
    r.node("sw01", "iosvl2", 450, 530, loop=False)
    r.vlans(["sw01"], (100,))
    net = next(r.lans)
    vip = str(net.network_address + 1)
    for j, edge in enumerate(("edge01", "edge02"), 2):
        ri, si = r.connect(edge, "sw01", label="LAN compartida")
        r.interface(
            "sw01",
            si["name"],
            ["switchport mode access", "switchport access vlan 100", "no shutdown"],
        )
        r.interface(
            edge,
            ri["name"],
            [
                f"ip address {net.network_address + j} {net.netmask}",
                f"standby 100 ip {vip}",
                f"standby 100 priority {120 if j == 2 else 100}",
                "standby 100 preempt",
                "no shutdown",
            ],
        )
    r.host("h01", "sw01", 100, str(net), 10, vip, x=750, y=620)
    for edge, iface, internal, provider in [("edge01", b, f, 65101), ("edge02", d, e, 65102)]:
        bgp(
            r,
            edge,
            65000,
            [(iface["ip"], provider), (internal["ip"], 65000)],
            [r.nodes[edge]["loopback"] + "/32", str(net)],
            False,
        )
        r.nodes[edge]["base"] += [
            "router bgp 65000",
            f"neighbor {internal['ip']} next-hop-self",
            "exit",
        ]
    for isp, iface, asn in [("isp01", a, 65101), ("isp02", c, 65102)]:
        bgp(r, isp, asn, [(iface["ip"], 65000)], [remote + "/32"], False)
    r.nodes["edge01"]["solution"] += [
        "route-map PREFER-ISP1 permit 10",
        "set local-preference 200",
        "exit",
        "router bgp 65000",
        f"neighbor {b['ip']} route-map PREFER-ISP1 in",
        "exit",
    ]
    # A route refresh is an exec operation, performed after configuration by commands().
    r.plan["post_config"] = [{"node": "edge01", "commands": [f"clear ip bgp {b['ip']} soft in"]}]
    for edge in ("edge01", "edge02"):
        r.check(edge, "show ip bgp " + remote, r"localpref 200.*best", label="Preferencia de ISP01")
        r.ping(edge, remote, source="Loopback0")
    r.ping("h01", remote)
    r.plan["actions"] = [
        {
            "id": "fault",
            "label": "Retirar ISP01",
            "node": "edge01",
            "commands": ["configure terminal", "interface " + a["name"], "shutdown", "end"],
            "inverse": ["configure terminal", "interface " + a["name"], "no shutdown", "end"],
        }
    ]
    r.plan["exercise"] = (
        "Preferir ISP01 con local-preference y comprobar cambio de salida en los routers de borde."
    )


def firewall(r):
    r.node("fw01", "asa", 500, 260, loop=False)
    for j, (zone, security, x, y) in enumerate(
        [("inside", 100, 120, 260), ("dmz", 50, 850, 120), ("outside", 0, 850, 440)], 1
    ):
        host = r.node(f"h0{j}", "vpcs", x, y, loop=False)
        fi, _hi = r.connect("fw01", host["name"], label=zone)
        net = next(r.lans)
        gw = str(net.network_address + 1)
        ip = str(net.network_address + 10)
        r.interface(
            "fw01",
            fi["name"],
            [
                f"nameif {zone}",
                f"security-level {security}",
                f"ip address {gw} {net.netmask}",
                "no shutdown",
            ],
        )
        host["base"] += [f"ip {ip}/24 {gw}"]
        host["ip"] = ip
        r.nodes["fw01"]["base"] += [f"icmp permit {net.network_address} {net.netmask} {zone}"]
        r.ping(host, gw, "preparation")
    a, b, c = [r.nodes[f"h0{i}"]["ip"] for i in (1, 2, 3)]
    r.nodes["fw01"]["solution"] += [
        f"access-list INSIDE extended permit icmp host {a} host {b}",
        f"access-list INSIDE extended deny ip host {a} host {c}",
        "access-group INSIDE in interface inside",
        f"access-list DMZ extended permit icmp host {b} host {a} echo-reply",
        "access-group DMZ in interface dmz",
    ]
    r.ping("h01", b)
    r.ping("h01", c, negative=True)
    r.check("fw01", "show access-list INSIDE", r"hitcnt=[1-9]")
    r.plan["exercise"] = (
        "Permitir ICMP desde LAN a DMZ y su respuesta; bloquear LAN hacia la zona exterior."
    )


def comparison(r):
    if r.images.get("nxos", "nxosv9k-9300v-9.3.9") == r.images.get(
        "nxos105", "nxosv9k-9300v-10.5.3.F"
    ):
        raise ValueError("La comparación necesita dos versiones diferentes.")
    for group, profile, y in [("a", "nxos", 180), ("b", "nxos105", 470)]:
        for j in (1, 2):
            r.node(f"{group}-r0{j}", profile, 200 + (j - 1) * 500, y)
        r.connect(f"{group}-r01", f"{group}-r02", routed=True, label="Versión " + group.upper())
        r.ospf([f"{group}-r01", f"{group}-r02"])
        for j in (1, 2):
            r.ping(f"{group}-r0{j}", r.nodes[f"{group}-r0{3 - j}"]["loopback"])
    r.plan["exercise"] = (
        "Comparar la misma prueba OSPF en Nexus 9.3.9 y 10.5.3.F, en dos componentes aislados."
    )
    r.plan["comparison_groups"] = {"A": ["a-r01", "a-r02"], "B": ["b-r01", "b-r02"]}


def make_catalog_plan(scenario, name, **kwargs):
    try:
        r = Recipe(scenario, name, **kwargs)
        if scenario in ("B01", "B02", "A07"):
            basic_routing(r, scenario)
        elif scenario in ("B03", "B04", "B05", "B06", "B07"):
            switching(r, scenario)
        elif scenario == "B08":
            inter_vlan(r)
        elif scenario in ("I01", "I02", "I03"):
            ospf_network(r, scenario)
        else:
            {
                "I04": gateway,
                "I05": bgp_chain,
                "I06": vrf,
                "I07": acl_nat,
                "I08": ipv6,
                "A01": nexus_vpc,
                "A02": evpn,
                "A03": mpls,
                "A04": redistribution,
                "A05": multihoming,
                "A06": firewall,
                "A08": comparison,
            }[scenario](r)
        return r.finish()
    except StopIteration as exc:
        raise ValueError(
            "El pool no alcanza para todos los enlaces o equipos de esta receta."
        ) from exc


def validate_catalog_plan(plan):
    expected = make_catalog_plan(
        plan["scenario"],
        plan["name"],
        mode=plan["mode"],
        folder=plan["folder"],
        instance=plan["uuid"],
        backend=plan.get("backend", "eve"),
        **plan["parameters"],
    )
    # Editorial changes do not invalidate a saved, otherwise identical recipe.
    # Commands, allocations, checks and graph must still match exactly.
    for key in ("title", "prepare", "exercise"):
        if not isinstance(plan.get(key), str) or len(plan[key]) > 2000:
            raise ValueError("Descripción de receta inválida")
        expected[key] = plan[key]
    if expected != plan:
        raise ValueError("La receta fue modificada o pertenece a otra versión; regenerala.")
    return plan
