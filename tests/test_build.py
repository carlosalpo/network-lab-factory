import json
import os
import stat
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

from netlab.build import bootstrap, build, check_build
from netlab.model import load


@pytest.fixture
def scenario():
    return load(Path(__file__).parents[1] / "examples/dual-wan.yml")


def test_reproducible_build_and_physical_wiring(scenario, tmp_path):
    a, b = build(scenario, tmp_path / "a"), build(scenario, tmp_path / "b")
    for file in a.rglob("*"):
        if file.is_file():
            assert file.read_bytes() == (b / file.relative_to(a)).read_bytes()
    root = ET.parse(a / "dual-wan.unl").getroot()
    nodes = root.findall("topology/nodes/node")
    assert len(nodes) == 4
    assert len({n.get("uuid") for n in nodes}) == 4
    counts = {}
    for node in nodes:
        interfaces = node.findall("interface")
        assert interfaces[0].get("network_id") == "1"
        assert node.get("config") == "0"  # no undocumented startup-config embedding
        assert node.get("ethernet") == "4"
        assert {p.get("id") for p in interfaces} == {"0", "1", "2"}
        for port in interfaces[1:]:
            nid = port.get("network_id")
            counts[nid] = counts.get(nid, 0) + 1
    assert all(counts[str(i)] == 2 for i in range(2, 6))
    assert check_build(a)["lab"] == "dual-wan"


def test_inventory_and_configs_agree(scenario, tmp_path):
    out = build(scenario, tmp_path / "lab")
    hosts = yaml.safe_load((out / "inventory.yml").read_text())["all"]["children"]["routers"][
        "hosts"
    ]
    for node in scenario["nodes"]:
        host = hosts[node["name"]]
        config = (out / "configs" / f"{node['name']}.cfg").read_text()
        assert node["loopback"] in config
        assert node["management_ip"] == host["ansible_host"]
        assert "GigabitEthernet0/0" not in config
        assert len(host["expected_neighbors"]) == 2
        assert len(host["probe_targets"]) == 3
        for port in host["lab_interfaces"]:
            assert f"ip address {port['ip']} {port['mask']}" in config


def test_refuse_existing_output(scenario, tmp_path):
    out = build(scenario, tmp_path / "lab")
    with pytest.raises(FileExistsError):
        build(scenario, out)


def test_detect_changed_inventory(scenario, tmp_path):
    out = build(scenario, tmp_path / "lab")
    (out / "inventory.yml").write_text("changed")
    with pytest.raises(ValueError, match="artifact changed"):
        check_build(out)


def test_manifest_cannot_read_outside_build(scenario, tmp_path):
    out = build(scenario, tmp_path / "lab")
    manifest = json.loads((out / "manifest.json").read_text())
    manifest["artifacts"]["../outside"] = "0" * 64
    (out / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="artifact changed"):
        check_build(out)


def test_bootstrap_is_private_and_not_in_build(scenario, tmp_path):
    out = bootstrap(scenario, "labadmin", "SyntheticOnly123!", tmp_path / "private")
    assert stat.S_IMODE(out.stat().st_mode) == 0o700
    for file in out.iterdir():
        assert stat.S_IMODE(file.stat().st_mode) == 0o600
        assert "secret 0 SyntheticOnly123!" in file.read_text()
    public = build(scenario, tmp_path / "public")
    assert all("SyntheticOnly123!" not in f.read_text() for f in public.rglob("*") if f.is_file())


@pytest.mark.parametrize(
    "username,password",
    [
        ("admin\nend", "SyntheticOnly123!"),
        ("admin", "weak"),
        ("admin", "test\nshutdown"),
        ("admin", "Space Is Not OK123"),
        ("admin", "A" * 26),
    ],
)
def test_bootstrap_rejects_cli_injection(scenario, tmp_path, username, password):
    with pytest.raises(ValueError):
        bootstrap(scenario, username, password, tmp_path / "secret")
    assert not os.path.exists(tmp_path / "secret")
