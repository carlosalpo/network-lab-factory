"""Export the real terminal widgets with public fixture inventory; never deploy.

Run from an installed checkout: python scripts/capture_workshop.py
"""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from textual.widgets import Button, Input, Select

from netlab.catalog import PROFILES
from netlab.tui import WorkshopApp


class FixtureInventory:
    """Only discovery and preflight are simulated; mutations fail closed."""

    def __init__(self, host, user, control, **kwargs):
        self.host, self.user, self.control = host, user, control

    def run(self, action, **kwargs):
        if action == "inventory":
            return {
                "images": [p["image"] for p in PROFILES.values() if p["image"]],
                "memory_mib": 65536,
                "free_gib": 200,
                "vpcs": True,
                "version": "fixture",
            }
        if action == "preflight":
            return {}
        raise AssertionError("Capture fixture cannot deploy or modify a lab")


async def capture():
    destination = Path(__file__).resolve().parents[1] / "docs/screenshots/workshop"
    with TemporaryDirectory(prefix="nlf-capture-") as output:
        app = WorkshopApp(connector_factory=FixtureInventory, output_root=output, theme="dark")
        async with app.run_test(size=(150, 44)) as pilot:

            async def press(id):
                app.query_one("#" + id, Button).focus()
                await pilot.press("enter")
                await app.workers.wait_for_complete()
                await pilot.pause()

            def save(name):
                (destination / (name + ".svg")).write_text(
                    app.export_screenshot(title="Network Lab Factory · fixture preview"),
                    encoding="utf-8",
                )

            app.query_one("#host", Input).value = "lab.example"
            app.query_one("#user", Input).value = "root"
            await press("connect")
            await press("choose")
            app.query_one("#scenario-choice", Select).value = "B03"
            await pilot.pause()
            save("scenario")
            await press("b01")
            app.query_one("#name", Input).value = "vlan-trunk-practice"
            await pilot.pause()
            save("prepare")
            await press("preview")
            assert app.page == "review"
            assert app.query_one("#start", Button).disabled
            save("review")
            assert not list(Path(output).iterdir())


if __name__ == "__main__":
    asyncio.run(capture())
