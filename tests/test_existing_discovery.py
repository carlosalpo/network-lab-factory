"""Platform API fixtures and IOS console protocol contract tests."""

import copy
import sys
import textwrap

import pytest
from test_existing_addressing import worker as worker_fixture

worker = worker_fixture

PROJECT = "11111111-1111-4111-8111-111111111111"
NODE_A = "22222222-2222-4222-8222-222222222222"
NODE_B = "33333333-3333-4333-8333-333333333333"


class FixtureAPI:
    def __init__(self, responses):
        self.responses, self.calls = responses, []

    def request(self, method, path):
        assert method == "GET", "Discovery must never create, start or change platform resources"
        self.calls.append(path)
        return copy.deepcopy(self.responses[path])


def gns3_api():
    base = "/projects/" + PROJECT
    nodes = [
        {
            "node_id": nid,
            "name": name,
            "node_type": "qemu",
            "compute_id": "local",
            "console_type": "telnet",
            "console_host": "127.0.0.1",
            "console": port,
            "status": "started",
            "ports": [{"name": "Gi0/0", "adapter_number": 0, "port_number": 0}],
            "properties": {"default_password": "never-export-this"},
        }
        for nid, name, port in ((NODE_A, "R1", 5001), (NODE_B, "R2", 5002))
    ]
    return FixtureAPI(
        {
            "/projects": [{"project_id": PROJECT, "name": "Study", "status": "opened"}],
            base: {"name": "Study", "status": "opened"},
            base + "/nodes": nodes,
            base + "/links": [
                {
                    "link_id": "link-one",
                    "nodes": [
                        {"node_id": nid, "adapter_number": 0, "port_number": 0}
                        for nid in (NODE_A, NODE_B)
                    ],
                }
            ],
        }
    )


def test_gns3_discovers_native_links_with_no_mutating_requests(worker):
    api = gns3_api()
    listing = worker["existing_list"](api, "gns3")
    assert listing["labs"][0]["id"] == PROJECT
    topology = worker["existing_topology"](
        api, {"backend": "gns3", "host": "fixture.example"}, PROJECT
    )
    assert topology["segments"][0]["endpoints"][0]["interface"] == "GigabitEthernet0/0"
    assert topology["nodes"][0]["console"] == 5001
    assert "never-export-this" not in str(topology)
    assert all(n["error"] is None for n in topology["nodes"])


def test_closed_gns3_project_is_not_opened_implicitly(worker):
    api = gns3_api()
    api.responses["/projects/" + PROJECT]["status"] = "closed"
    with pytest.raises(ValueError, match="Open this project"):
        worker["existing_topology"](api, {"backend": "gns3", "host": "fixture.example"}, PROJECT)
    assert len(api.calls) == 1


def test_distributed_compute_visible_but_not_eligible(worker):
    api = gns3_api()
    api.responses["/projects/" + PROJECT + "/nodes"][0]["compute_id"] = "remote"
    snap = worker["existing_topology"](api, {"backend": "gns3", "host": "fixture.example"}, PROJECT)
    assert snap["nodes"][0]["error"] and snap["nodes"][0]["console"] is None


def test_eve_folders_and_shared_network_are_not_independent_subnets(worker):
    base = "/labs/Study/Lab%201.unl"
    raw = {
        str(i): {
            "name": f"R{i}",
            "template": "vios",
            "status": 2,
            "console": "telnet",
            "url": f"telnet://127.0.0.1:{32768 + i}",
        }
        for i in range(1, 4)
    }
    responses = {
        "/folders/Study": {
            "folders": [{"name": "..", "path": "/"}],
            "labs": [{"path": "/Study/Lab 1.unl", "file": "Lab 1.unl"}],
        },
        base: {"name": "Lab 1", "id": PROJECT},
        base + "/nodes": raw,
        base + "/networks": {"1": {"name": "LAN", "type": "bridge"}},
    }
    for i in range(1, 4):
        responses[base + f"/nodes/{i}/interfaces"] = {
            "ethernet": [{"name": "Gi0/0", "network_id": 1}]
        }
    api = FixtureAPI(responses)
    assert worker["existing_list"](api, "eve", "/Study")["labs"][0]["id"] == "/Study/Lab 1.unl"
    settings = {"backend": "eve", "host": "fixture.example"}
    snap = worker["existing_topology"](api, settings, "/Study/Lab 1.unl")
    assert len(snap["segments"]) == 1
    assert snap["segments"][0]["shared"]
    assert len(snap["segments"][0]["endpoints"]) == 3
    assert not any(n["error"] for n in snap["nodes"])
    responses[base + "/networks"]["1"]["type"] = "pnet0"
    assert worker["existing_topology"](api, settings, "/Study/Lab 1.unl")["segments"][0]["blocked"]


@pytest.mark.parametrize("path", ["/../outside.unl", "/Study/../../lab.unl", "/Study/\nlab.unl"])
def test_eve_path_escape_refused(worker, path):
    with pytest.raises(ValueError):
        worker["safe_lab_path"](path)


def test_ios_protocol_login_enable_and_complete_read(worker, monkeypatch, tmp_path):
    import pexpect

    script = tmp_path / "ios_fixture.py"
    script.write_text(
        textwrap.dedent("""
        input()  # Wake-up carriage return.
        print("Username: ", end="", flush=True)
        assert input() == "student"
        print("Password: ", end="", flush=True)
        assert input() == "fixture-login"
        print("Router>", end="", flush=True)
        assert input() == "enable"
        print("Password: ", end="", flush=True)
        assert input() == "fixture-enable"
        while True:
            print("Router#", end="", flush=True)
            command = input()
            if command == "show version":
                print("Cisco IOS Software, IOSv Software, Version 15.9")
            elif command == "show running-config":
                print("version 15.9\\nhostname Router\\ninterface GigabitEthernet0/0\\n no ip address\\n shutdown\\n!\\nend")
            elif command != "terminal length 0":
                print("% Invalid input detected")
    """)
    )
    spawn = pexpect.spawn
    monkeypatch.setattr(
        pexpect, "spawn", lambda *args, **kwargs: spawn(sys.executable, [str(script)], **kwargs)
    )
    device = worker["IOSConsole"](
        5001, {"user": "student", "password": "fixture-login", "enable": "fixture-enable"}
    )
    try:
        config, interfaces = device.read()
        assert interfaces["GigabitEthernet0/0"]["address"] is None
        assert interfaces["GigabitEthernet0/0"]["shutdown"]
        assert "fixture-login" not in config
        with pytest.raises(ValueError, match="rejected"):
            device.command("not-a-valid-command")
    finally:
        device.close()


def test_console_transport_errors_never_include_secret_buffers(worker):
    class BrokenChild:
        def sendline(self, text):
            raise RuntimeError("timeout before='enable secret hidden-device-secret'")

    device = worker["IOSConsole"].__new__(worker["IOSConsole"])
    device.child = BrokenChild()
    with pytest.raises(RuntimeError) as err:
        device.command("show running-config")
    assert "hidden-device-secret" not in str(err.value)
