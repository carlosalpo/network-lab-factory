"""SSH transport for the explicit GNS3 3.0.6 Nexo host profile."""

from pathlib import Path, PurePosixPath

from .catalog import PROFILES
from .gns3_profiles import GNS3_PROFILES
from .gns3_render import native_graph
from .wizard import EveSSH


class GNS3SSH(EveSSH):
    backend = "gns3"

    def __init__(
        self,
        host,
        user="gns3admin",
        control=None,
        *,
        auth_file="/etc/gns3/nexo-admin.json",
        batch=False,
        cancel=None,
    ):
        super().__init__(host, user, control, batch=batch, cancel=cancel)
        path = PurePosixPath(auth_file)
        if not path.is_absolute() or ".." in path.parts:
            raise ValueError(
                "The private GNS3 configuration must use an absolute path on the server."
            )
        self.auth_file = str(path)

    def connection(self):
        return dict(super().connection(), backend="gns3", auth_file=self.auth_file)

    def worker_source(self):
        source = super().worker_source().replace('if __name__ == "__main__":', "if False:")
        source += (
            "\nGNS3_PROFILES = "
            + repr(GNS3_PROFILES)
            + "\nIMAGE_ALIASES = "
            + repr({k: p["image"] for k, p in PROFILES.items()})
            + "\n"
        )
        return source + Path(__file__).with_name("gns3_worker.py").read_text()

    def run(self, action, callback=None, **values):
        if action == "deploy":
            values["graph"] = native_graph(values["plan"])
        return super().run(action, callback, auth_file=self.auth_file, **values)
