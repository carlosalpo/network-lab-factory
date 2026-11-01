"""Existing-lab transport and private local review bundles."""

import json
import os
import uuid
from pathlib import Path

from .addressing import config_commands
from .gns3_portable import GNS3PortableSSH, validate_api_url
from .wizard import EveSSH


class ExistingLabSSH(EveSSH):
    def __init__(self, base, *, eve_url="http://127.0.0.1", eve_user="admin", eve_password=None):
        if base.backend == "gns3" and not isinstance(base, GNS3PortableSSH):
            raise ValueError(
                "Existing labs require direct GNS3 SSH access, not the legacy Proxmox transport."
            )
        super().__init__(
            base.host,
            base.user,
            base.control,
            batch=True,
            cancel=base.cancel,
            port=base.port,
            password=base.password,
            auth_method=base.auth_method,
        )
        self.backend = base.backend
        self.api_password = (
            getattr(base, "api_password", None) if self.backend == "gns3" else eve_password
        )
        from urllib.parse import urlsplit

        origin = getattr(base, "api_url", eve_url)
        validate_api_url(origin)
        if urlsplit(origin).hostname not in (base.host.lower(), "127.0.0.1", "localhost", "::1"):
            raise ValueError("The API must address the SSH server or its loopback.")
        self.settings = {
            "backend": self.backend,
            "host": base.host,
            "api_url": origin,
            "api_user": getattr(base, "api_user", eve_user),
            "api_password": self.api_password,
            "api_version": getattr(base, "api_version", "auto"),
        }
        self.device_credentials = {}

    def redact(self, value):
        value = super().redact(value)
        if isinstance(value, str):
            for secret in self.device_credentials.values():
                if secret:
                    value = value.replace(secret, "[redacted]")
        elif isinstance(value, dict):
            value = {k: self.redact(v) for k, v in value.items()}
        elif isinstance(value, list):
            value = [self.redact(v) for v in value]
        return value

    def worker_source(self):
        source = GNS3PortableSSH(self.host).worker_source()
        source = source.replace('if __name__ == "__main__":', "if False:")
        for name in ("addressing.py", "existing_worker.py"):
            source += "\n" + Path(__file__).with_name(name).read_text()
        return source

    def run(self, action, callback=None, **values):
        if action not in {"existing-list", "existing-read", "existing-apply", "existing-save"}:
            raise ValueError("Unknown existing-lab operation")
        return super().run(
            action, callback, settings=self.settings, credentials=self.device_credentials, **values
        )


def export_review(plan, root):
    """Unique private directory, generated commands only; never raw device backups."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    out = root / ("addressing-" + uuid.uuid4().hex[:12])
    out.mkdir(mode=0o700)
    content = {"plan.json": json.dumps(plan, indent=2) + "\n"}
    for index, node in enumerate(sorted({c["node"] for c in plan["changes"]}), 1):
        changes = [c for c in plan["changes"] if c["node"] == node]
        content[f"device-{index:03d}.cfg"] = "\n".join(config_commands(changes)) + "\n"
    lines = [
        "# Existing lab addressing review",
        "",
        "Lab: " + plan["lab"]["name"],
        "",
        "Only missing IPv4 addresses are added. Existing addresses and shutdown state are preserved.",
        "No routing, VLANs, interface activation or permanent save is included.",
        "",
    ]
    for c in plan["changes"]:
        lines.append(
            f"- {c['device']} / {c['interface']}: {c['before'] or 'unassigned'} → {c['after']} ({c['group']})"
        )
    content["review.md"] = "\n".join(lines) + "\n"
    for name, value in content.items():
        fd = os.open(out / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(value)
    return out
