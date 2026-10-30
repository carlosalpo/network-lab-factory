import base64
import json
import subprocess
import sys
import threading
import xml.etree.ElementTree as ET

import pytest

from netlab.wizard import EveSSH, deploy_plan, run_wizard
from netlab.workshop import PROFILE, config_lines, lab_xml, make_plan, validate_plan


def test_practice_prepares_addresses_but_does_not_solve_exercise():
    p = make_plan("practice")
    for node in p["nodes"]:
        config = "\n".join(config_lines(p, node))
        assert node["ip"] in config and node["loopback"] in config
        assert "ospf" not in config
    assert p["nodes"][0]["ip"] == "10.240.0.1"
    assert p["nodes"][1]["ip"] == "10.240.0.2"


def test_reference_and_labels_share_same_resolved_plan():
    p = make_plan("reference", mode="reference", transit="10.2.0.0/31", loopbacks="10.3.0.0/30")
    xml = ET.fromstring(lab_xml(p))
    assert len(xml.findall(".//node")) == 2
    assert not any(n.get("type", "").startswith("pnet") for n in xml.findall(".//network"))
    labels = "\n".join(base64.b64decode(n.text).decode() for n in xml.findall(".//data"))
    for node in p["nodes"]:
        assert node["ip"] + "/31" in labels
        assert node["loopback"] + "/32" in labels
        assert "router ospf 1" in config_lines(p, node)
    assert p["nodes"][0]["ip"] == "10.2.0.0"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"transit": "10.241.0.0/30"},
        {"transit": "8.8.8.0/30"},
        {"transit": "10.0.0.1/30"},
        {"transit": "10.0.0.0/29"},
        {"loopbacks": "10.9.0.0/32"},
        {"folder": "../outside"},
        {"image": "vios-unknown"},
        {"mode": "unknown"},
        {"name": "bad;touch-file"},
    ],
)
def test_invalid_or_incompatible_plans_rejected(kwargs):
    with pytest.raises(ValueError):
        make_plan(**({"name": "valid"} | kwargs))


def test_modified_resolved_plan_is_rejected():
    p = make_plan("valid")
    assert validate_plan(p) == p
    p["nodes"][0]["ip"] = "10.240.0.2"
    with pytest.raises(ValueError):
        validate_plan(p)


def test_ssh_keeps_host_validation_and_rejects_option_injection():
    assert "StrictHostKeyChecking=yes" in EveSSH("lab.example").ssh_args()
    with pytest.raises(ValueError):
        EveSSH("-oProxyCommand=bad")


def test_cancel_never_calls_deploy(monkeypatch, tmp_path):
    actions = []

    def fake_run(self, action, **kwargs):
        actions.append(action)
        return {"images": [PROFILE], "memory_mib": 4096, "profile": "test"}

    monkeypatch.setattr(EveSSH, "run", fake_run)
    monkeypatch.chdir(tmp_path)
    answers = iter(["eve", "lab.example", "", "B01", "", "", "1", "1", "", "", ""])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert run_wizard() == 0
    assert actions == ["inventory", "preflight"]
    assert not list(tmp_path.iterdir())


def test_failure_preserves_partial_record(tmp_path):
    class Failing:
        host = "lab.example"
        user = "root"
        control = None

        def run(self, action, callback=None, **kwargs):
            if action == "deploy":
                callback({"event": "created", "path": "/lab/test.unl"})
                raise RuntimeError("boot failed")

    out = tmp_path / "run"
    with pytest.raises(RuntimeError, match="boot failed"):
        deploy_plan(Failing(), make_plan("test"), out)
    assert json.loads((out / "result.json").read_text())["status"] == "incomplete"
    assert json.loads((out / "events.json").read_text())[0]["event"] == "created"
    assert (out / "plan.json").is_file()


def test_preflight_failure_does_not_write_output(tmp_path):
    class Existing:
        def run(self, *args, **kwargs):
            raise RuntimeError("already exists")

    with pytest.raises(RuntimeError):
        deploy_plan(Existing(), make_plan("test"), tmp_path / "run")
    assert not (tmp_path / "run").exists()


def test_ssh_streams_events_and_cancels_a_silent_child(monkeypatch):
    real_popen = subprocess.Popen
    children = []

    def local_worker(args, **kwargs):
        assert "BatchMode=yes" in args
        child = real_popen(
            [
                sys.executable,
                "-u",
                "-c",
                (
                    "import sys,time; sys.stdin.read(); "
                    'print(\'{"event":"waiting","node":"r01"}\',flush=True); time.sleep(20)'
                ),
            ],
            **kwargs,
        )
        children.append(child)
        return child

    monkeypatch.setattr("netlab.wizard.subprocess.Popen", local_worker)
    cancel = threading.Event()
    connector = EveSSH("lab.example", batch=True, cancel=cancel)
    events = []

    def observed(event):
        events.append(event)
        cancel.set()

    with pytest.raises(RuntimeError, match="cancelled"):
        connector.run("inventory", callback=observed)
    assert events == [{"event": "waiting", "node": "r01"}]
    assert children[0].poll() is not None
