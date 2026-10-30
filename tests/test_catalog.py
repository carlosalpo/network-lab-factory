"""Contract tests for the catalog and observation-based acceptance."""

import copy
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from netlab.catalog import CATALOG, commands
from netlab.catalog_render import eve_xml, write_bundle
from netlab.cli import main
from netlab.recipes import make_catalog_plan, validate_catalog_plan


@pytest.mark.parametrize("case", list(CATALOG))
@pytest.mark.parametrize("mode", ["practice", "reference"])
def test_every_recipe_is_reproducible_and_has_connected_valid_ports(case, mode):
    p = make_catalog_plan(case, "case-" + case.lower(), mode=mode)
    assert validate_catalog_plan(json.loads(json.dumps(p))) == p
    root = ET.fromstring(eve_xml(p))
    assert len(root.findall(".//node")) == len(p["nodes"])
    assert len(root.findall(".//network")) == len(p["networks"])
    assert all(n.get("type") == "bridge" for n in root.findall(".//network"))
    endpoints = []
    for net in p["networks"]:
        assert len(net["endpoints"]) == 2
        endpoints += [(e["node"], e["port"]) for e in net["endpoints"]]
    assert len(endpoints) == len(set(endpoints)), "An interface cannot connect to two networks"
    for n in p["nodes"]:
        assert all(i["id"] < n["device"]["ports"] for i in n["interfaces"])
        assert commands(n, "practice")
    assert p["checks"]["preparation"] and p["checks"]["exercise"]


def test_practice_routing_does_not_include_solution_and_reference_does():
    for sid, keyword in [
        ("B01", "router ospf"),
        ("B02", "ip route "),
        ("I02", "router ospf"),
        ("I05", "router bgp"),
        ("I06", "ip vrf "),
        ("A01", "vpc domain"),
    ]:
        p = make_catalog_plan(sid, "exercise")
        base = "\n".join(line for n in p["nodes"] for line in commands(n))
        ref = "\n".join(line for n in p["nodes"] for line in commands(n, "reference"))
        assert keyword not in base
        assert keyword in ref


def test_capabilities_pools_and_plan_tampering_are_rejected():
    for params in [
        {"transit": "8.8.0.0/16"},
        {"transit": "10.242.0.0/16"},
        {"transit": "10.240.0.0/30"},
        {"images": {"iosv": "unreviewed-image"}},
        {"folder": "../existing"},
        {"name": "bad; echo nope"},
    ]:
        with pytest.raises(ValueError):
            make_catalog_plan("I02", **({"name": "valid"} | params))
    p = make_catalog_plan("B03", "valid")
    changed = copy.deepcopy(p)
    changed["nodes"][0]["base"].append("reload")
    with pytest.raises(ValueError):
        validate_catalog_plan(changed)


def test_reference_comparison_has_no_cross_version_links():
    p = make_catalog_plan("A08", "versions")
    for net in p["networks"]:
        assert len({e["node"][0] for e in net["endpoints"]}) == 1
    assert len({n["device"]["image"] for n in p["nodes"]}) == 2
    with pytest.raises(ValueError, match="different"):
        make_catalog_plan("A08", "versions", images={"nxos105": "nxosv9k-9300v-9.3.9"})


def worker_namespace():
    source = Path(__file__).parents[1] / "src/netlab"
    ns = {"__name__": "worker_test"}
    exec(compile((source / "eve_worker.py").read_text(), str(source / "eve_worker.py"), "exec"), ns)  # noqa: S102 — test the bundled worker source in its shared namespace.
    exec(  # noqa: S102 — test the bundled worker source in its shared namespace.
        compile(
            (source / "catalog_worker.py").read_text(), str(source / "catalog_worker.py"), "exec"
        ),
        ns,
    )
    return ns


def test_ping_failures_and_syntax_errors_are_not_false_success():
    evaluate = worker_namespace()["evaluate_check"]
    for output in [
        "100% packet loss",
        "100.00% packet loss",
        "Success rate is 0 percent (0/3)",
        "% Invalid input detected",
        "Bad command: ping",
    ]:
        assert not evaluate({"kind": "ping"}, output)
    assert evaluate({"kind": "ping"}, "Success rate is 100 percent (3/3)")
    assert evaluate({"kind": "ping"}, "0.00% packet loss")
    assert not evaluate({"kind": "unreachable"}, "% Invalid input detected")
    assert not evaluate({"kind": "unreachable"}, "timeout\n64 bytes from 10.0.0.1 seq=1")
    assert evaluate({"kind": "unreachable"}, "Success rate is 0 percent (0/3)")


def test_vpcs_prompt_with_carriage_return_is_recognized():
    prompt = worker_namespace()["PROMPT"]
    assert re.search(prompt, "Welcome\r\n\rVPCS> ")
    assert re.search(prompt, "\r\nh01> ")
    assert not re.search(prompt, "User supplied text > is not a prompt")


def test_catalog_cli_bundle_and_confirmation_do_not_deploy(tmp_path, capsys):
    assert main(["catalog"]) == 0
    assert "A08" in capsys.readouterr().out
    out = tmp_path / "plan"
    assert main(["plan", "B03", "--name", "vlan-test", "--output", str(out)]) == 0
    assert len(list(out.glob("*.base.cfg"))) == 6
    assert (
        main(
            [
                "deploy",
                str(out / "plan.json"),
                "--host",
                "never-connect.example",
                "--confirm",
                "wrong-name",
                "--output",
                str(tmp_path / "run"),
            ]
        )
        == 2
    )
    assert not (tmp_path / "run").exists()
    with pytest.raises(FileExistsError):
        write_bundle(make_catalog_plan("B03", "vlan-test"), out)


def test_faults_have_explicit_inverse_and_are_not_in_initial_configuration():
    p = make_catalog_plan("A07", "fault-test")
    assert p["mode"] == "reference"
    action = p["actions"][0]
    assert "shutdown" in action["commands"] and "no shutdown" in action["inverse"]
    assert all("shutdown" not in commands(n, "reference") for n in p["nodes"])


def test_mutation_invalidates_both_observations_even_if_remote_operation_fails(
    tmp_path, monkeypatch
):
    from netlab.wizard import save_json

    p = make_catalog_plan("A07", "fault-record")
    save_json(tmp_path / "plan.json", p)
    original = {
        "status": "ready",
        "ports": {},
        "preparation": {"status": "passed"},
        "exercise": {"status": "passed"},
    }
    save_json(tmp_path / "result.json", original)
    save_json(tmp_path / "connection.json", {"host": "qa.example"})

    class Connector:
        def run(self, *args, **kwargs):
            raise RuntimeError("Lost connection after applying part of the change")

    monkeypatch.setattr("netlab.wizard.connector_from_record", lambda *a, **kw: Connector())
    assert main(["lab-action", str(tmp_path), "fault", "--confirm", p["name"]]) == 2
    latest = json.loads((tmp_path / "latest-result.json").read_text())
    assert latest["status"] == "unverified"
    assert latest["preparation"]["status"] == latest["exercise"]["status"] == "unverified"
    assert json.loads((tmp_path / "result.json").read_text()) == original


def test_asa_initial_enable_handles_password_creation_once(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setitem(
        __import__("sys").modules, "pexpect", SimpleNamespace(EOF=EOFError, TIMEOUT=TimeoutError)
    )
    ns = worker_namespace()

    class Console:
        nlf_boot = True
        before = ""

        def __init__(self):
            self.sent = []
            self.prompts = iter(
                ["Password:", "Enter a new password:", "Repeat password:", "ciscoasa#"]
            )

        def send(self, value):
            self.sent.append(value)

        def read_nonblocking(self, *args, **kwargs):
            raise TimeoutError

        def expect(self, patterns, timeout):
            text = next(self.prompts)
            matches = [
                (m.start(), i)
                for i, p in enumerate(patterns)
                if isinstance(p, str) and (m := re.search(p, text))
            ]
            return min(matches)[1]

    child = Console()
    ns["node_command"](child, "enable", "asa")
    assert child.sent == ["enable\r"] + [ns["LAB_PASSWORD"] + "\r"] * 3


def test_labels_cover_subinterfaces_and_distinguish_exercise_addresses():
    from netlab.catalog_render import ascii_topology, interface_annotations

    p = make_catalog_plan("B08", "routing-vlans")
    router = next(n for n in p["nodes"] if n["name"] == "r01")
    notes = interface_annotations(router, "practice")
    subinterfaces = {k: v for k, v in notes.items() if "." in k}
    assert len(subinterfaces) == 2
    assert all("[exercise]" in value for values in subinterfaces.values() for value in values)
    preview = ascii_topology(p)
    assert all(name in preview for name in subinterfaces)
    reference = interface_annotations(router, "reference")
    assert all("[exercise]" not in value for values in reference.values() for value in values)


def test_firewall_hosts_and_ipv6_addresses_have_labels():
    from netlab.catalog_render import ascii_topology

    p = make_catalog_plan("A06", "firewall-labels", mode="reference")
    text = ascii_topology(p)
    assert all(n["ip"] in text for n in p["nodes"] if n["profile"] == "vpcs")
    p6 = make_catalog_plan("I08", "ipv6-labels", mode="reference")
    assert "fd42:" in ascii_topology(p6)


def test_vpcs_ipv6_replies_and_explicit_acl_denial_are_recognized():
    evaluate = worker_namespace()["evaluate_check"]
    replies = "\n".join(f"fd42:4e4c:4600:4::2 icmp6_seq={i} ttl=58 time=9.1 ms" for i in (1, 2, 3))
    assert evaluate({"kind": "ping"}, replies)
    assert not evaluate({"kind": "ping"}, replies.splitlines()[0])
    denied = "*10.242.0.1 icmp_seq=1 ttl=255 time=9 ms (ICMP type:3, code:13, Communication administratively prohibited)"
    assert evaluate({"kind": "unreachable"}, denied)
    assert not evaluate({"kind": "ping"}, denied)
    assert not evaluate({"kind": "unreachable"}, replies + "\ntimeout")


def test_asa_enable_is_not_reissued_on_privileged_reconnected_console():
    from types import SimpleNamespace

    worker = worker_namespace()
    child = SimpleNamespace(after="\r\nfw01# ")
    assert worker["node_command"](child, "enable", "asa") == ""


@pytest.mark.parametrize("schema", [1, 2])
def test_eve_stop_requests_poweroff_and_observes_process_exit(monkeypatch, schema):

    ns = worker_namespace()
    calls, events = [], []
    running = iter([[123], []])
    ns["identity"] = lambda plan: Path("/owned/lab.unl")
    ns["running_lab_processes"] = lambda plan: next(running)
    ns["emit"] = lambda event, **values: events.append((event, values))
    monkeypatch.setattr(ns["subprocess"], "run", lambda argv, **kw: calls.append(argv))
    monkeypatch.setattr(ns["time"], "sleep", lambda seconds: None)
    ns["catalog_main"]({"action": "stop", "plan": {"schema": schema, "nodes": [{"id": 1}]}})
    assert calls[0][calls[0].index("-m") + 1] == "1"
    assert calls[0][calls[0].index("-D") + 1] == "1"
    assert events[-1][1]["status"] == "stopped"


def test_nxos_boot_image_matches_profile_and_rejects_ambiguity():
    select = worker_namespace()["nxos_boot_image"]
    node = {"name": "nx01", "device": {"image": "nxosv9k-9300v-9.3.9"}}
    assert select("bootflash::\n  nxos.9.3.9.bin\n", node) == "nxos.9.3.9.bin"
    assert select("NXOS image file is: bootflash:///nxos.9.3.9.bin", node) == "nxos.9.3.9.bin"
    with pytest.raises(RuntimeError):
        select("nxos.10.5.3.F.bin", node)
    with pytest.raises(RuntimeError):
        select("nxos.9.3.9.bin nxos64-cs.9.3.9.bin", node)


def test_csr_async_day0_notice_does_not_reject_unrelated_command(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setitem(__import__("sys").modules, "pexpect", SimpleNamespace(TIMEOUT=TimeoutError))
    ns = worker_namespace()

    class Console:
        before = "terminal length 0\r\n% Error: The application: day0guestshell, does not exist\r\n"

        def read_nonblocking(self, *args, **kwargs):
            raise TimeoutError

        def send(self, text):
            pass

        def expect(self, *args, **kwargs):
            pass

    child = Console()
    assert "day0guestshell" in ns["legacy_command"](child, "terminal length 0")
    child.before = "% Error: rejected configuration"
    with pytest.raises(RuntimeError):
        ns["legacy_command"](child, "configure terminal")


def test_lacp_cable_action_changes_and_restores_both_endpoints():
    from types import SimpleNamespace

    ns = worker_namespace()
    calls = []
    events = []
    ns["identity"] = lambda plan: None
    ns["node_console"] = lambda node, port: SimpleNamespace(name=node["name"], close=lambda: None)
    ns["node_command"] = lambda child, command, dialect: calls.append((child.name, command))
    ns["emit"] = lambda event, **values: events.append(values)
    plan = make_catalog_plan("B04", "two-ended-fault", mode="reference")
    ports = {n["name"]: n["id"] for n in plan["nodes"]}
    for action, expected in [("fault", "shutdown"), ("restore", "no shutdown")]:
        calls.clear()
        ns["catalog_main"]({"action": action, "plan": plan, "ports": ports})
        assert {(name, line) for name, line in calls if line == expected} == {
            ("sw01", expected),
            ("sw02", expected),
        }
        assert events[-1]["nodes"] == ["sw01", "sw02"]


def test_ospf_verification_waits_for_database_exchange_but_remains_bounded():
    from types import SimpleNamespace

    ns = worker_namespace()
    elapsed = [0]
    ns["time"] = SimpleNamespace(
        monotonic=lambda: elapsed[0],
        sleep=lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds),
    )
    ns["node_console"] = lambda *args: SimpleNamespace(close=lambda: None)
    ns["emit"] = lambda *args, **kwargs: None
    check = {
        "node": "r01",
        "command": "show ip ospf neighbor",
        "kind": "regex",
        "pattern": "FULL",
        "label": "OSPF",
    }
    plan = {
        "schema": 2,
        "nodes": [{"name": "r01", "device": {"console": "ios"}}],
        "checks": {"preparation": [check]},
    }
    ns["node_command"] = lambda *args: "FULL" if elapsed[0] >= 45 else "EXSTART"
    assert ns["verify"](plan, {"r01": 1})["status"] == "passed"
    assert elapsed[0] >= 45
    elapsed[0] = 0
    ns["node_command"] = lambda *args: "EXSTART"
    assert ns["verify"](plan, {"r01": 1})["status"] == "failed"
    assert elapsed[0] == 120
