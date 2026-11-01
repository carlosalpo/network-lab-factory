"""Address planning invariants and remote mutation gates; no live lab is contacted."""

import json
import stat
from typing import ClassVar

import pytest

from netlab.addressing import compile_addressing, config_commands, digest, parse_ios_config
from netlab.existing import ExistingLabSSH, export_review
from netlab.wizard import EveSSH


def ios_config(address=None, extra="", interface="GigabitEthernet0/0"):
    address_line = " ip address " + address if address else " no ip address"
    return f"version 15.9\nhostname Router\ninterface {interface}\n{address_line}\n shutdown\n{extra}!\nend\n"


def topology():
    return {
        "lab": {"id": "fixture", "name": "Study lab", "backend": "gns3"},
        "nodes": [
            {"id": str(i), "name": f"R{i}", "console": 5000 + i, "error": None, "identity": {}}
            for i in range(1, 5)
        ],
        "segments": [
            {
                "id": sid,
                "name": name,
                "shared": False,
                "blocked": None,
                "endpoints": [{"node": str(n), "interface": "GigabitEthernet0/0"} for n in pair],
            }
            for sid, name, pair in (("a", "R1-R2", (1, 2)), ("b", "R3-R4", (3, 4)))
        ],
    }


def snapshot():
    snap = topology()
    for node in snap["nodes"]:
        node["interfaces"] = parse_ios_config(ios_config())
        node["config_hash"] = digest(ios_config())
    return snap


def intent():
    return {
        "groups": {"Internal": {"pool": "10.10.30.0/24", "exclude": []}},
        "segments": {
            sid: {"group": "Internal", "prefix": 30, "subnet": "", "fixed": {}}
            for sid in ("a", "b")
        },
    }


@pytest.fixture
def worker():
    ns = {"__name__": "existing_worker_fixture"}
    exec(compile(ExistingLabSSH(EveSSH("fixture.example")).worker_source(), "worker", "exec"), ns)  # noqa: S102 — execute bundled worker under test.
    return ns


def test_fixed_subnet_is_reserved_before_automatic_with_pinned_host():
    spec = intent()
    spec["segments"]["b"].update(
        subnet="10.10.30.0/30", fixed={"3|GigabitEthernet0/0": "10.10.30.2"}
    )
    plan = compile_addressing(snapshot(), spec)
    assert [s["subnet"] for s in plan["segments"]] == ["10.10.30.4/30", "10.10.30.0/30"]
    assert [c["after"] for c in plan["changes"]] == [
        "10.10.30.5/30",
        "10.10.30.6/30",
        "10.10.30.2/30",
        "10.10.30.1/30",
    ]
    assert plan == compile_addressing(snapshot(), spec)
    assert not any("shutdown" in c or "write" in c for c in config_commands(plan["changes"]))


def test_groups_and_exclusions_and_pool_exhaustion():
    spec = intent()
    spec["groups"]["External"] = {"pool": "10.20.0.0/24"}
    spec["groups"]["Internal"]["exclude"] = ["10.10.30.0/28"]
    spec["segments"]["b"]["group"] = "External"
    assert [s["subnet"] for s in compile_addressing(snapshot(), spec)["segments"]] == [
        "10.10.30.16/30",
        "10.20.0.0/30",
    ]
    spec = intent()
    spec["groups"]["Internal"]["pool"] = "10.10.30.0/30"
    with pytest.raises(ValueError, match="exhausted"):
        compile_addressing(snapshot(), spec)


def test_preserves_existing_ips_and_reserves_unselected_interfaces():
    snap, spec = snapshot(), intent()
    snap["nodes"][2]["interfaces"] = parse_ios_config(ios_config("10.10.30.1 255.255.255.252"))
    plan = compile_addressing(snap, spec)
    assert plan["segments"][0]["subnet"] == "10.10.30.4/30"
    assert plan["changes"][2]["change"] is False
    assert plan["changes"][3]["after"] == "10.10.30.2/30"
    del spec["segments"]["b"]
    assert compile_addressing(snap, spec)["segments"][0]["subnet"] == "10.10.30.4/30"


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda s, i: i["groups"].update(Other={"pool": "10.10.30.0/25"}), "overlap"),
        (lambda s, i: i["segments"]["a"].update(subnet="10.20.0.0/30"), "outside"),
        (lambda s, i: i["segments"]["a"].update(subnet="10.10.30.1/30"), "IPv4"),
        (
            lambda s, i: i["segments"]["a"].update(fixed={"1|GigabitEthernet0/0": "10.10.30.0"}),
            "usable",
        ),
        (
            lambda s, i: i["segments"]["a"].update(
                fixed={"1|GigabitEthernet0/0": "10.10.30.1", "2|GigabitEthernet0/0": "10.10.30.1"}
            ),
            "duplicated",
        ),
        (
            lambda s, i: i["segments"]["a"].update(fixed={"9|GigabitEthernet0/0": "10.10.30.1"}),
            "outside",
        ),
        (lambda s, i: s["nodes"][0].update(error="unreachable"), "supported"),
        (lambda s, i: s["segments"][0].update(blocked="External network"), "External"),
        (lambda s, i: s["segments"][0].update(shared=True), "Confirm"),
        (lambda s, i: i["groups"]["Internal"].update(exclude=["192.168.0.0/24"]), "inside"),
    ],
)
def test_invalid_or_unsafe_plans_rejected(mutation, message):
    snap, spec = snapshot(), intent()
    mutation(snap, spec)
    with pytest.raises(ValueError, match=message):
        compile_addressing(snap, spec)


def test_existing_renumbering_and_outside_overlap_blocked():
    snap, spec = snapshot(), intent()
    snap["nodes"][0]["interfaces"] = parse_ios_config(ios_config("10.10.30.1 255.255.255.252"))
    spec["segments"]["a"]["fixed"] = {"1|GigabitEthernet0/0": "10.10.30.2"}
    with pytest.raises(ValueError, match="preserved"):
        compile_addressing(snap, spec)
    spec = intent()
    spec["segments"]["b"]["subnet"] = "10.10.30.0/30"
    with pytest.raises(ValueError, match="overlap|conflicts"):
        compile_addressing(snap, spec)


def test_shared_segment_capacity_and_31():
    snap, spec = snapshot(), intent()
    del spec["segments"]["b"]
    snap["segments"][0]["shared"] = True
    snap["segments"][0]["endpoints"].append({"node": "3", "interface": "GigabitEthernet0/0"})
    spec["segments"]["a"].update(confirm_shared=True, prefix=29)
    assert len(compile_addressing(snap, spec)["changes"]) == 3
    spec["segments"]["a"]["prefix"] = 30
    with pytest.raises(ValueError, match="too small"):
        compile_addressing(snap, spec)
    spec["segments"]["a"]["prefix"] = 31
    with pytest.raises(ValueError, match="two-endpoint"):
        compile_addressing(snap, spec)
    snap["segments"][0]["endpoints"].pop()
    assert [c["after"] for c in compile_addressing(snap, spec)["changes"]] == [
        "10.10.30.0/31",
        "10.10.30.1/31",
    ]


def test_interface_mapping_must_resolve_to_observed_physical_interface():
    snap, spec = snapshot(), intent()
    snap["segments"][0]["endpoints"][0]["interface"] = "port0"
    spec["segments"]["a"]["interfaces"] = {"1|port0": "GigabitEthernet0/0"}
    assert compile_addressing(snap, spec)["changes"][0]["interface"] == "GigabitEthernet0/0"
    spec["segments"]["a"]["interfaces"] = {"1|port0": "GigabitEthernet0/0\nreload"}
    with pytest.raises(ValueError, match="physical"):
        compile_addressing(snap, spec)


@pytest.mark.parametrize(
    "extra",
    [
        " switchport\n",
        " ip address dhcp\n",
        " ip vrf forwarding RED\n",
        " channel-group 1 mode active\n",
        " ip unnumbered Loopback0\n",
        " ip address 10.0.0.1 255.255.255.0 secondary\n",
    ],
)
def test_ios_parser_rejects_ambiguous_or_non_routed_interfaces(extra):
    assert parse_ios_config(ios_config(extra=extra))["GigabitEthernet0/0"]["blocked"]


def test_parser_requires_complete_output():
    with pytest.raises(ValueError, match="Incomplete"):
        parse_ios_config(ios_config().replace("end\n", ""))


def test_private_export_has_no_raw_configs_or_credentials(tmp_path):
    plan = compile_addressing(snapshot(), intent())
    out = export_review(plan, tmp_path)
    assert stat.S_IMODE(out.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in out.iterdir())
    assert "running_config" not in (out / "plan.json").read_text()
    assert "configure terminal" in (out / "device-001.cfg").read_text()


class FakeDevice:
    states: ClassVar = {}
    calls: ClassVar = []
    fail_port = None

    def __init__(self, port, credentials):
        self.port = port

    def close(self):
        pass

    def read(self):
        config = self.states[self.port]
        return config, parse_ios_config(config)

    def command(self, command):
        self.calls.append((self.port, command))
        if command == "show startup-config":
            return ios_config()
        if self.port == self.fail_port and command.startswith("ip address"):
            raise RuntimeError("fixture device secret must never appear")
        if command.startswith("ip address"):
            self.states[self.port] = self.states[self.port].replace("no ip address", command)
        return "[OK]"


def prepare_apply(worker, tmp_path):
    worker["private_state"] = lambda: tmp_path
    worker["existing_topology"] = lambda *args: topology()
    FakeDevice.states = {5000 + i: ios_config() for i in range(1, 5)}
    FakeDevice.calls = []
    FakeDevice.fail_port = None


def test_apply_backups_before_writes_then_separate_permanent_save(worker, tmp_path):
    prepare_apply(worker, tmp_path)
    result = worker["existing_apply"](None, {}, snapshot(), intent(), {}, FakeDevice)
    assert result["status"] == "verified" and not result["saved"]
    assert not any(command == "write memory" for _, command in FakeDevice.calls)
    directory = tmp_path / result["run_id"]
    backups = list(directory.glob("device-*.json"))
    assert len(backups) == 4
    assert all("no ip address" in p.read_text() for p in backups)
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in directory.iterdir())
    saved = worker["existing_save"](None, {}, result["run_id"], {}, FakeDevice)
    assert saved["status"] == "saved"
    assert sum(command == "write memory" for _, command in FakeDevice.calls) == 4
    with pytest.raises(ValueError, match="unsaved"):
        worker["existing_save"](None, {}, result["run_id"], {}, FakeDevice)


def test_config_or_topology_drift_prevents_every_write(worker, tmp_path):
    prepare_apply(worker, tmp_path)
    FakeDevice.states[5004] = ios_config(extra=" description manually edited\n")
    with pytest.raises(ValueError, match="changed"):
        worker["existing_apply"](None, {}, snapshot(), intent(), {}, FakeDevice)
    assert FakeDevice.calls == []
    prepare_apply(worker, tmp_path)
    different = topology()
    different["nodes"][0]["console"] = 9999
    worker["existing_topology"] = lambda *args: different
    with pytest.raises(ValueError, match="topology"):
        worker["existing_apply"](None, {}, snapshot(), intent(), {}, FakeDevice)
    assert FakeDevice.calls == []


def test_partial_application_is_journaled_without_secrets_and_cannot_save(worker, tmp_path):
    prepare_apply(worker, tmp_path)
    FakeDevice.fail_port = 5002
    result = worker["existing_apply"](None, {}, snapshot(), intent(), {}, FakeDevice)
    assert result["status"] == "incomplete" and result["attempted"] == ["1", "2"]
    assert result["verified"] == ["1"]
    assert "secret" not in json.dumps(result)
    assert not any(port == 5003 for port, _ in FakeDevice.calls)
    with pytest.raises(ValueError, match="fully verified"):
        worker["existing_save"](None, {}, result["run_id"], {}, FakeDevice)


def test_save_blocks_config_drift_before_any_permanent_write(worker, tmp_path):
    prepare_apply(worker, tmp_path)
    result = worker["existing_apply"](None, {}, snapshot(), intent(), {}, FakeDevice)
    FakeDevice.states[5004] += "! Changed\n"
    with pytest.raises(ValueError, match="changed"):
        worker["existing_save"](None, {}, result["run_id"], {}, FakeDevice)
    assert not any(command == "write memory" for _, command in FakeDevice.calls)


def test_no_writes_when_backup_fails(worker, tmp_path):
    prepare_apply(worker, tmp_path)

    def fail(*args):
        raise OSError("disk full")

    worker["private_json"] = fail
    with pytest.raises(OSError):
        worker["existing_apply"](None, {}, snapshot(), intent(), {}, FakeDevice)
    assert FakeDevice.calls == []


@pytest.mark.parametrize(
    "url",
    [
        "telnet://external.example:23",
        "telnet://u:p@127.0.0.1:23",
        "http://127.0.0.1:23",
        "telnet://127.0.0.1:0",
    ],
)
def test_remote_or_malformed_console_refused(worker, url):
    with pytest.raises(ValueError):
        worker["local_console"](url, "fixture.example")


def test_unknown_device_observation_never_implies_empty_config(worker):
    class BadDevice:
        def __init__(self, *args):
            raise ValueError("private password")

    observed = worker["existing_observe"](topology(), {}, BadDevice)
    assert all(n["error"] for n in observed["nodes"])
    assert "private password" not in json.dumps(observed)
    assert not any("interfaces" in n for n in observed["nodes"])


def test_credentials_are_only_in_memory_and_redacted():
    connector = ExistingLabSSH(
        EveSSH("fixture.example", password="ssh-fixture"), eve_password="api-fixture"
    )
    connector.device_credentials = {"password": "router-fixture", "enable": "enable-fixture"}
    assert (
        connector.redact("ssh-fixture api-fixture router-fixture enable-fixture")
        == "[redacted] [redacted] [redacted] [redacted]"
    )
    assert "fixture" not in json.dumps(connector.connection()).replace("fixture.example", "server")


def test_partial_save_is_not_success_and_cannot_be_retried(worker, tmp_path):
    prepare_apply(worker, tmp_path)
    result = worker["existing_apply"](None, {}, snapshot(), intent(), {}, FakeDevice)

    class UnconfirmedSave(FakeDevice):
        def command(self, command):
            if self.port == 5002 and command == "write memory":
                return "Timed out before acknowledgement"
            return super().command(command)

    saved = worker["existing_save"](None, {}, result["run_id"], {}, UnconfirmedSave)
    assert saved["status"] == "save-incomplete"
    assert saved["saved_nodes"] == ["1"]
    with pytest.raises(ValueError, match="unsaved"):
        worker["existing_save"](None, {}, result["run_id"], {}, FakeDevice)


def test_existing_operation_lock_blocks_application(worker, tmp_path):
    import fcntl

    prepare_apply(worker, tmp_path)
    with (tmp_path / (digest(snapshot()["lab"]) + ".lock")).open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="Another addressing"):
            worker["existing_apply"](None, {}, snapshot(), intent(), {}, FakeDevice)
    assert FakeDevice.calls == []


def test_modified_observation_cannot_bypass_preserve_existing_ips(worker, tmp_path):
    prepare_apply(worker, tmp_path)
    snap = snapshot()
    FakeDevice.states[5001] = ios_config("10.10.30.1 255.255.255.252")
    # A matching hash alone must not make fabricated interface observations trustworthy.
    snap["nodes"][0]["config_hash"] = digest(FakeDevice.states[5001])
    with pytest.raises(ValueError, match="changed"):
        worker["existing_apply"](None, {}, snap, intent(), {}, FakeDevice)
    assert FakeDevice.calls == []
