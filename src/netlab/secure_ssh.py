"""Password SSH transport: verified host keys, in-memory secrets, encrypted stdin."""

import json
import queue
import threading
import time


def connect(connector):
    import paramiko

    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        client.connect(
            connector.host,
            port=connector.port,
            username=connector.user,
            password=connector.password,
            timeout=10,
            auth_timeout=20,
            banner_timeout=15,
            allow_agent=False,
            look_for_keys=False,
        )
        return client
    except paramiko.BadHostKeyException:
        client.close()
        raise RuntimeError(
            "SSH host identity changed. Verify it with your administrator before reconnecting."
        ) from None
    except paramiko.AuthenticationException:
        client.close()
        raise RuntimeError("SSH authentication failed. Check the username and password.") from None
    except (paramiko.SSHException, OSError):
        client.close()
        raise RuntimeError(
            "SSH connection failed. Check the address and port. For a new server, first verify "
            "its fingerprint using OpenSSH on this computer; unknown host keys are never accepted automatically."
        ) from None


def run(connector, command, payload, callback=None):
    client = connect(connector)
    channel = None
    try:
        channel = client.get_transport().open_session(timeout=10)
        channel.settimeout(30)
        channel.exec_command(command)
        channel.sendall(json.dumps(payload).encode())
        channel.shutdown_write()
        channel.settimeout(None)
        lines = queue.Queue()
        stdout = channel.makefile("r")

        def read():
            try:
                for line in stdout:
                    lines.put(line)
            finally:
                lines.put(None)

        thread = threading.Thread(target=read, daemon=True)
        thread.start()
        deadline = time.monotonic() + {
            "deploy": 3600,
            "verify": 1800,
            "stop": 600,
            "existing-read": 3600,
            "existing-apply": 3600,
            "existing-save": 3600,
        }.get(payload["action"], 120)
        events = []
        while True:
            if connector.cancel and connector.cancel.is_set():
                raise RuntimeError(
                    "Operation cancelled. Remote resources may remain; inspect the lab before retrying."
                )
            if time.monotonic() > deadline:
                raise RuntimeError("Operation timed out. Inspect the remote lab before retrying.")
            # Drain diagnostics without recording server messages or credentials.
            while channel.recv_stderr_ready():
                channel.recv_stderr(8192)
            try:
                line = lines.get(timeout=0.1)
            except queue.Empty:
                continue
            if line is None:
                break
            try:
                event = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if not isinstance(event, dict):
                continue
            event = connector.redact(event)
            events.append(event)
            if callback:
                callback(event)
        while not channel.exit_status_ready():
            if (connector.cancel and connector.cancel.is_set()) or time.monotonic() > deadline:
                raise RuntimeError(
                    "Remote exit status was not confirmed. Inspect the lab before retrying."
                )
            if channel.recv_stderr_ready():
                channel.recv_stderr(8192)
            time.sleep(0.05)
        if channel.recv_exit_status() or not events:
            raise RuntimeError(
                next(
                    (e["message"] for e in events if e.get("event") == "error"),
                    "Remote operation failed; inspect the lab before retrying.",
                )
            )
        return events[-1]
    finally:
        if channel is not None:
            channel.close()
        client.close()


def console(connector, port):
    """Keep console traffic in SSH; never expose a new public listener."""
    import select
    import sys
    import termios
    import tty

    if not sys.stdin.isatty():
        raise RuntimeError("An interactive terminal is required to open a console.")
    client = connect(connector)
    channel = None
    saved = termios.tcgetattr(sys.stdin)
    try:
        channel = client.get_transport().open_session(timeout=10)
        channel.get_pty(term="xterm")
        channel.exec_command("telnet -K -c 127.0.0.1 " + str(int(port)))
        print("Console over SSH. Press Ctrl+] to return.")
        tty.setraw(sys.stdin.fileno())
        while True:
            ready, _, _ = select.select([channel, sys.stdin], [], [], 1)
            if channel in ready:
                data = channel.recv(8192)
                if not data:
                    break
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
            if sys.stdin in ready:
                data = sys.stdin.buffer.read1(1024)
                if b"\x1d" in data or not data:
                    break
                channel.sendall(data)
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, saved)
        if channel is not None:
            channel.close()
        client.close()
