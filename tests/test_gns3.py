"""GNS3 isolation, transport recovery and export contracts (no live server)."""

import copy
import io
import json
import urllib.error

import pytest

from netlab.catalog import CATALOG
from netlab.catalog_render import write_bundle
from netlab.gns3 import GNS3SSH
from netlab.gns3_qga import GNS3QGA
from netlab.gns3_render import native_graph, resource_id
from netlab.recipes import make_catalog_plan
from netlab.wizard import connector_from_record


@pytest.mark.parametrize("scenario", list(CATALOG))
@pytest.mark.parametrize("mode", ["practice", "reference"])
def test_native_graph_has_only_isolated_nodes_and_unique_ports(scenario, mode):
    plan = make_catalog_plan(scenario, "gns3-case", backend="gns3", mode=mode)
    graph = native_graph(plan)
    assert graph == native_graph(copy.deepcopy(plan))
    assert len(graph["nodes"]) == len(plan["nodes"])
    assert len(graph["links"]) == len(plan["networks"])
    ids = {n["node_id"]: n for n in graph["nodes"]}
    used = []
    for node in graph["nodes"]:
        assert node["node_type"] in {"qemu", "vpcs"}
        assert node["compute_id"] == "local"
        assert node["label"]["style"] == "font-size: 10px;"
    for link in graph["links"]:
        assert len(link["nodes"]) == 2
        for end in link["nodes"]:
            node = ids[end["node_id"]]
            assert 0 <= end["adapter_number"] < node["properties"].get("adapters", 1)
            assert end["port_number"] == 0
            used.append((end["node_id"], end["adapter_number"]))
    assert len(used) == len(set(used))
    assert graph["drawings"]
    changed = copy.deepcopy(plan)
    changed["uuid"] = "27a70aac-ec44-41dd-a2e8-123456789abc"
    assert resource_id(changed, "r01") != resource_id(plan, "r01")


def test_export_keeps_backend_and_does_not_write_eve_lab(tmp_path):
    plan = make_catalog_plan("B01", "gns3-case", backend="gns3")
    out = tmp_path / "bundle"
    write_bundle(plan, out)
    assert (out / "gns3-request.json").exists()
    assert not list(out.glob("*.unl"))
    assert json.loads((out / "plan.json").read_text())["backend"] == "gns3"
    with pytest.raises(ValueError):
        native_graph(make_catalog_plan("B01", "eve-case"))


def test_qga_pending_status_does_not_need_pid_in_each_reply(monkeypatch):
    c = GNS3QGA("qa.example")
    monkeypatch.setattr(c, "guest_start", lambda *args: {"pid": 123})
    states = iter([{"exited": 0}, {"exited": 1, "exitcode": 0, "out-data": '{"ok":true}'}])
    calls = []

    def status(pid):
        calls.append(pid)
        return next(states)

    monkeypatch.setattr(c, "guest_status", status)
    monkeypatch.setattr("netlab.gns3_qga.time.sleep", lambda _: None)
    assert c.guest_read("read only") == {"ok": True}
    assert calls == [123, 123]


def test_ssh_status_poll_cannot_consume_interactive_keyboard(monkeypatch):
    from types import SimpleNamespace

    seen = []

    def run(args, **kwargs):
        seen.append(kwargs["input"])
        return SimpleNamespace(returncode=0, stdout='{"exited":0}')

    monkeypatch.setattr("netlab.gns3_qga.subprocess.run", run)
    assert GNS3QGA("qa.example").guest_status(123) == {"exited": 0}
    assert seen == [""]


def test_connection_roundtrip_stores_no_credentials():
    c = GNS3QGA("qa.example", control="/tmp/session", guest_id=110)
    record = c.connection()
    restored = connector_from_record(json.loads(json.dumps(record)), batch=True)
    assert isinstance(restored, GNS3QGA)
    assert restored.connection() == record
    assert not {"password", "token", "access_token"} & set(record)
    with pytest.raises(ValueError):
        GNS3SSH("qa.example", auth_file="/tmp/../etc/private")


def worker():
    ns = {"__name__": "gns3_test"}
    exec(compile(GNS3SSH("qa.example").worker_source(), "gns3-worker", "exec"), ns)  # noqa: S102 — exercise the bundled remote source.
    return ns


def test_uncertain_api_mutation_is_not_retried_and_hides_response_body():
    ns = worker()
    api = ns["GNS3API"]("/unused")
    api.token = "fixture-token"
    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            raise urllib.error.HTTPError(request.full_url, 500, "error", {}, io.BytesIO(b"secret"))

    api.opener = Opener()
    with pytest.raises(RuntimeError, match="HTTP 500") as error:
        api.request("POST", "/projects", {"name": "isolated"})
    assert len(calls) == 1
    assert "secret" not in str(error.value) and "fixture-token" not in str(error.value)


def test_stop_refuses_changed_project_composition_before_mutating():
    ns = worker()
    plan = make_catalog_plan("B01", "owned", backend="gns3")
    calls = []

    class API:
        def __init__(self, _):
            pass

        def request(self, method, path, *args, **kwargs):
            calls.append((method, path))
            if path.endswith("/nodes"):
                return [{"node_id": "foreign", "console": 5000}]
            return {"name": plan["name"], "path": str(ns["destination"](plan))}

    ns["GNS3API"] = API
    with pytest.raises(ValueError, match="composición"):
        ns["gns3_main"]({"action": "stop", "plan": plan})
    assert all(method == "GET" for method, _ in calls)


def test_identity_rejects_project_moved_outside_expected_folder():
    ns = worker()
    plan = make_catalog_plan("B01", "owned", backend="gns3")

    class API:
        def request(self, *args):
            return {"name": plan["name"], "path": "/srv/gns3/projects/someone-else"}

    ns["api"] = API()
    with pytest.raises(ValueError, match="identidad"):
        ns["identity"](plan)
