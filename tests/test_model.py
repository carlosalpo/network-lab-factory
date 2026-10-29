from copy import deepcopy
from pathlib import Path

import pytest

from netlab.model import ValidationError, load, validate


@pytest.fixture
def scenario():
    return load(Path(__file__).parents[1] / "examples/dual-wan.yml")


def test_example_has_four_routers_and_four_links(scenario):
    assert len(scenario["nodes"]) == len(scenario["links"]) == 4


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update(schema_version=2),
        lambda d: d.update(schema_version=True),
        lambda d: d.update(unknown="typo"),
        lambda d: d.update(name="../../escape"),
        lambda d: d.update(image="../../image"),
        lambda d: d["management"].update(bridge="pnet0"),
        lambda d: d["management"].update(network="192.0.2.1/24"),
        lambda d: d["nodes"][1].update(name="branch"),
        lambda d: d["nodes"][0].update(management_ip="192.0.2.0"),
        lambda d: d["nodes"][0].update(management_ip="192.0.2.255"),
        lambda d: d["nodes"][0].update(management_ip="192.0.3.10"),
        lambda d: d["nodes"][1].update(management_ip="192.0.2.11"),
        lambda d: d["nodes"][0].update(loopback="192.0.2.99"),
        lambda d: d["nodes"][0].update(loopback="198.18.0.1"),
        lambda d: d["nodes"][0].update(loopback="224.0.0.1"),
        lambda d: d["nodes"][0].update(x=True),
        lambda d: d["links"][0].update(cost=0),
        lambda d: d["links"][0].update(subnet="198.18.0.0/24"),
        lambda d: d["links"][1].update(subnet="198.18.0.0/30"),
        lambda d: d["links"][0]["endpoints"][0].update(node="missing"),
        lambda d: d["links"][0]["endpoints"][0].update(port=0),
        lambda d: d["links"][0]["endpoints"][0].update(port=4),
        lambda d: d["links"][0]["endpoints"][0].update(ip="198.18.0.0"),
        lambda d: d["links"][0]["endpoints"][1].update(ip="198.18.0.1"),
        lambda d: d["links"][2]["endpoints"][0].update(port=1),
        lambda d: d["links"][0]["endpoints"][1].update(node="branch", port=3),
        lambda d: d["links"][0].update(endpoints=[]),
        lambda d: d.update(links=d["links"][:2]),
    ],
)
def test_invalid_designs_are_rejected(scenario, change):
    candidate = deepcopy(scenario)
    change(candidate)
    with pytest.raises(ValidationError):
        validate(candidate)


def test_slash31_endpoints(scenario):
    scenario["links"][0]["subnet"] = "198.18.0.0/31"
    scenario["links"][0]["endpoints"][0]["ip"] = "198.18.0.0"
    scenario["links"][0]["endpoints"][1]["ip"] = "198.18.0.1"
    validate(scenario)


def test_duplicate_yaml_keys_fail(tmp_path):
    source = tmp_path / "bad.yml"
    source.write_text("name: first\nname: second\n")
    with pytest.raises(ValidationError, match="Duplicate YAML"):
        load(source)


def test_unsafe_yaml_tag_rejected(tmp_path):
    source = tmp_path / "unsafe.yml"
    source.write_text("!!python/object/apply:os.system ['echo unsafe']")
    with pytest.raises(ValidationError, match="Invalid YAML"):
        load(source)
