"""Portable Linux/GNS3 VM connector; templates belong to the target server."""

import re
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from .gns3 import GNS3SSH
from .gns3_render import native_graph
from .wizard import EveSSH


def validate_api_url(value):
    p = urlsplit(value)
    if (
        p.scheme not in ("http", "https")
        or not p.hostname
        or p.username
        or p.password
        or p.query
        or p.fragment
        or p.path not in ("", "/")
    ):
        raise ValueError(
            "Use an API origin such as http://127.0.0.1:3080, without credentials or a path."
        )
    if p.scheme == "http" and p.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError(
            "HTTP is allowed only on server loopback inside SSH. Use HTTPS for a remote controller."
        )
    try:
        port = p.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError("Invalid API port")
    except ValueError:
        raise ValueError("Invalid API port") from None
    return value.rstrip("/")


class GNS3PortableSSH(EveSSH):
    backend = "gns3"

    def __init__(
        self,
        host,
        user="gns3",
        control=None,
        *,
        api_url="http://127.0.0.1:3080",
        api_version="auto",
        api_user="",
        api_password=None,
        projects_path="",
        template_map=None,
        template_fingerprints=None,
        **options,
    ):
        super().__init__(host, user, control, **options)
        self.api_url = validate_api_url(api_url)
        if api_version not in ("auto", "2", "3"):
            raise ValueError("Choose Auto, API v2 or API v3.")
        if projects_path and (
            not projects_path.startswith("/") or ".." in Path(projects_path).parts
        ):
            raise ValueError("Projects directory must be an absolute Linux path.")
        self.api_version, self.api_user, self.api_password = api_version, api_user, api_password
        self.projects_path = projects_path
        self.template_map = dict(template_map or {})
        for family, template in self.template_map.items():
            if not re.fullmatch("[a-z0-9]+", family):
                raise ValueError("Invalid template family")
            uuid.UUID(template)
        self.template_fingerprints = dict(template_fingerprints or {})
        self.prepared_graph = None
        self.inventory = None

    def connection(self):
        return dict(
            super().connection(),
            backend="gns3",
            transport="portable-ssh",
            api_url=self.api_url,
            api_version=self.api_version,
            api_user=self.api_user,
            projects_path=self.projects_path,
            template_map=self.template_map,
            template_fingerprints=self.template_fingerprints,
        )

    def worker_source(self):
        source = (
            GNS3SSH(self.host).worker_source().replace('if __name__ == "__main__":', "if False:")
        )
        return source + "\n" + Path(__file__).with_name("gns3_portable_worker.py").read_text()

    def export_graph(self, plan):
        if self.prepared_graph is None:
            raise ValueError("Check the selected templates before exporting the deployment.")
        return self.prepared_graph

    def run(self, action, callback=None, **values):
        if action in ("preflight", "deploy"):
            values["graph"] = native_graph(values["plan"])
        result = super().run(
            action,
            callback,
            portable={
                "api_url": self.api_url,
                "api_version": self.api_version,
                "api_user": self.api_user,
                "api_password": self.api_password,
                "projects_path": self.projects_path,
                "template_map": self.template_map,
                "template_fingerprints": self.template_fingerprints,
            },
            **values,
        )
        if action == "inventory":
            self.inventory = result
            self.projects_path = result["projects_path"]
            self.api_version = result["api_version"]
        if action == "preflight":
            self.prepared_graph = result["graph"]
            self.template_fingerprints = result["template_fingerprints"]
        return result
