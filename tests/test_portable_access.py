"""Portable connections: fail closed, bind reviewed templates, never persist secrets."""

import copy
import io
import json
import urllib.error
from unittest.mock import Mock

import pytest

from netlab.gns3_portable import GNS3PortableSSH, validate_api_url
from netlab.gns3_render import native_graph
from netlab.recipes import make_catalog_plan
from netlab.wizard import EveSSH, connector_from_record


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org:3080",
        "https://u:p@example.org",
        "https://example.org/v3",
        "https://example.org?password=x",
        "file:///etc/passwd",
        "http://localhost:bad",
        "http://localhost.example.org:3080",
    ],
)
def test_unsafe_api_urls_rejected_before_credentials(url):
    with pytest.raises(ValueError):
        validate_api_url(url)


def test_records_roundtrip_without_secrets_and_keep_required_template_binding():
    c = GNS3PortableSSH(
        "lab.example",
        password="ssh-secret",
        api_password="api-secret",
        template_map={"iosv": "11a11111-1111-4111-8111-111111111111"},
    )
    record = c.connection()
    assert "secret" not in json.dumps(record)
    restored = connector_from_record(json.loads(json.dumps(record)))
    assert restored.connection() == record
    assert restored.password is None and restored.api_password is None
    with pytest.raises(RuntimeError, match="Re-enter"):
        restored.run("inventory")
    assert c.redact({"message": "ssh-secret and api-secret"}) == {
        "message": "[redacted] and [redacted]"
    }


def worker():
    ns = {"__name__": "portable_test"}
    exec(compile(GNS3PortableSSH("lab.example").worker_source(), "portable-worker", "exec"), ns)  # noqa: S102 — exercise bundled worker
    return ns


class Response(io.BytesIO):
    pass


@pytest.mark.parametrize("version", ["2", "3"])
def test_api_negotiates_authentication_and_never_logs_password(version):
    ns = worker()
    calls = []

    class Opener:
        def open(self, req, timeout):
            calls.append(req)
            if req.full_url.endswith("/v3/version") and version == "2":
                raise urllib.error.HTTPError(req.full_url, 404, "not found", {}, None)
            if req.full_url.endswith("/authenticate"):
                assert json.loads(req.data) == {"username": "admin", "password": "fixture-secret"}
                return Response(b'{"access_token":"fixture-token"}')
            return Response(
                json.dumps({"version": "2.2.55" if version == "2" else "3.0.7"}).encode()
            )

    ns["urllib"].request.build_opener = Mock(return_value=Opener())
    try:
        api = ns["PortableAPI"]({"api_user": "admin", "api_password": "fixture-secret"})
        assert api.version == version
        assert calls[0].get_header("Authorization") is None
        api.request("GET", "/templates")
        auth = calls[-1].get_header("Authorization")
        assert auth.startswith("Basic " if version == "2" else "Bearer ")
    finally:
        # shared urllib module must not leak monkeypatches to other tests
        import importlib

        importlib.reload(ns["urllib"].request)


def test_redirects_never_forward_credentials_and_http_errors_hide_body(monkeypatch):
    ns = worker()
    with pytest.raises(ns["APIError"]):
        ns["NoRedirect"]().redirect_request(None, None, 302, "", {}, "http://attacker.invalid")
    api = object.__new__(ns["PortableAPI"])
    api.origin = "http://127.0.0.1:3080"
    api.version = "3"
    api.user = "admin"
    api.password = "secret"
    api.token = "token"
    api.opener = Mock()
    api.opener.open.side_effect = urllib.error.HTTPError(
        "url", 500, "secret", {}, Response(b"secret token")
    )
    with pytest.raises(ns["APIError"]) as e:
        api.request("POST", "/projects", {"name": "owned"})
    assert "secret" not in str(e.value) and "token" not in str(e.value)
    assert api.opener.open.call_count == 1


def fixture_template(ns):
    return ns["checked_template"](
        {
            "template_id": "11a11111-1111-4111-8111-111111111111",
            "name": "My IOSv",
            "template_type": "qemu",
            "compute_id": "local",
            "console_type": "telnet",
            "hda_disk_image": "my-owned-image.qcow2",
            "ram": 768,
            "cpus": 1,
            "adapters": 4,
            "qemu_path": "/usr/bin/qemu-system-x86_64",
            "adapter_type": "e1000",
            "default_password": "must-not-export",
        }
    )


def test_template_binding_uses_target_runtime_and_rejects_changes_before_mutation():
    ns = worker()
    t = fixture_template(ns)
    ns["portable"] = {"template_map": {"iosv": t["template_id"]}}
    ns["api"] = Mock()
    ns["api"].request.return_value = [{"filename": "my-owned-image.qcow2"}]
    plan = make_catalog_plan("B01", "portable", backend="gns3")
    graph, fingerprints, ram = ns["bound_graph"](plan, {"templates": [t]}, native_graph(plan))
    assert ram == 1536
    assert "nexo" not in json.dumps(graph).lower()
    assert "must-not-export" not in json.dumps(graph)
    assert graph["nodes"][0]["properties"]["qemu_path"] == "/usr/bin/qemu-system-x86_64"
    ns["portable"]["template_fingerprints"] = fingerprints
    changed = copy.deepcopy(t)
    changed["properties"]["ram"] = 2048
    with pytest.raises(ValueError, match="changed after review"):
        ns["bound_graph"](plan, {"templates": [changed]}, native_graph(plan))
    assert all(call.args[0] == "GET" for call in ns["api"].request.call_args_list)


@pytest.mark.parametrize(
    "change",
    [{"compute_id": "remote"}, {"console_type": "vnc"}, {"linked_clone": False}, {"adapters": 0}],
)
def test_unsupported_templates_fail_closed(change):
    ns = worker()
    template = {
        "template_id": "11a11111-1111-4111-8111-111111111111",
        "name": "Router",
        "template_type": "qemu",
        "hda_disk_image": "image.qcow2",
        "ram": 1024,
        "adapters": 4,
    }
    template.update(change)
    with pytest.raises(ValueError):
        ns["checked_template"](template)


def test_missing_image_or_insufficient_ports_never_mutates():
    ns = worker()
    t = fixture_template(ns)
    ns["portable"] = {"template_map": {"iosv": t["template_id"]}}
    ns["api"] = Mock()
    ns["api"].request.return_value = []
    plan = make_catalog_plan("B01", "portable", backend="gns3")
    with pytest.raises(ValueError, match="unavailable"):
        ns["bound_graph"](plan, {"templates": [t]}, native_graph(plan))
    assert all(c.args[0] == "GET" for c in ns["api"].request.call_args_list)


def test_ssh_rejects_unknown_host_and_does_not_save_it(monkeypatch):
    import paramiko

    from netlab.secure_ssh import connect

    client = Mock()
    client.connect.side_effect = paramiko.SSHException("secret-host-error")
    monkeypatch.setattr(paramiko, "SSHClient", lambda: client)
    with pytest.raises(RuntimeError, match="fingerprint") as error:
        connect(EveSSH("new.example", password="private-secret"))
    assert "private-secret" not in str(error.value) and "secret-host-error" not in str(error.value)
    assert isinstance(client.set_missing_host_key_policy.call_args.args[0], paramiko.RejectPolicy)
    client.save_host_keys.assert_not_called()
    client.close.assert_called_once()


def test_ssh_bad_password_does_not_fallback_or_leak(monkeypatch):
    import paramiko

    from netlab.secure_ssh import connect

    client = Mock()
    client.connect.side_effect = paramiko.AuthenticationException("private-secret")
    monkeypatch.setattr(paramiko, "SSHClient", lambda: client)
    with pytest.raises(RuntimeError, match="authentication failed") as error:
        connect(EveSSH("lab.example", password="private-secret"))
    assert "private-secret" not in str(error.value)
    assert client.connect.call_args.kwargs["look_for_keys"] is False
    assert client.connect.call_args.kwargs["allow_agent"] is False


def test_password_transport_uses_encrypted_stdin_and_redacts_events(monkeypatch):
    """Real Paramiko client/server exchange over a local socket pair, no lab needed."""
    import socket
    import threading

    import paramiko

    from netlab.secure_ssh import run

    server_socket, client_socket = socket.socketpair()
    server_key = paramiko.RSAKey.generate(2048)
    received = {}
    done = threading.Event()

    class Server(paramiko.ServerInterface):
        def check_auth_password(self, username, password):
            received["ssh_login"] = (username, password)
            return paramiko.AUTH_SUCCESSFUL

        def get_allowed_auths(self, username):
            return "password"

        def check_channel_request(self, kind, chanid):
            return (
                paramiko.OPEN_SUCCEEDED
                if kind == "session"
                else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED
            )

        def check_channel_exec_request(self, channel, command):
            received["command"] = command.decode()
            done.set()
            return True

    transport = paramiko.Transport(server_socket)
    transport.add_server_key(server_key)

    def serve():
        transport.start_server(server=Server())
        channel = transport.accept(10)
        assert done.wait(10)
        body = b""
        while part := channel.recv(8192):
            body += part
        received["payload"] = json.loads(body)
        channel.sendall(b'{"event":"inventory","message":"api-fixture-secret"}\n')
        channel.send_exit_status(0)
        channel.shutdown_write()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    real_client = paramiko.SSHClient

    def client():
        c = real_client()
        c.load_system_host_keys = lambda: None
        c.get_host_keys().add("fixture.example", server_key.get_name(), server_key)
        original = c.connect
        c.connect = lambda *args, **kwargs: original(*args, sock=client_socket, **kwargs)
        return c

    monkeypatch.setattr(paramiko, "SSHClient", client)
    c = GNS3PortableSSH(
        "fixture.example", password="ssh-fixture-secret", api_password="api-fixture-secret"
    )
    events = []
    try:
        result = run(
            c,
            "python3 -c harmless-fixture-worker",
            {"action": "inventory", "api_password": "api-fixture-secret"},
            events.append,
        )
        assert received["ssh_login"] == ("gns3", "ssh-fixture-secret")
        assert "secret" not in received["command"]
        assert received["payload"]["api_password"] == "api-fixture-secret"
        assert result == {"event": "inventory", "message": "[redacted]"}
        assert "api-fixture-secret" not in json.dumps(events)
    finally:
        transport.close()
        client_socket.close()
        server_socket.close()
        thread.join(5)
