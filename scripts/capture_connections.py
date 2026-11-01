"""Render actual connection widgets with public fixture values; no network calls."""

import asyncio
from pathlib import Path

from textual.widgets import Input, Select

from netlab.tui import WorkshopApp


async def main():
    destination = Path(__file__).resolve().parents[1] / "docs/screenshots/workshop"
    app = WorkshopApp(theme="dark")
    async with app.run_test(size=(150, 58)) as pilot:
        app.query_one("#backend", Select).value = "gns3"
        await pilot.pause()
        app.query_one("#host", Input).value = "gns3.example"
        app.query_one("#user", Input).value = "gns3"
        app.query_one("#ssh-password", Input).value = "fixture-only-ssh"
        app.query_one("#api-user", Input).value = "lab-user"
        app.query_one("#api-password", Input).value = "fixture-only-api"
        app.query_one("#host", Input).focus()
        await pilot.pause()
        data = app.export_screenshot(
            title="Network Lab Factory · fixture connection form · no server contacted"
        )
        assert "fixture-only-ssh" not in data and "fixture-only-api" not in data
        (destination / "connection.svg").write_text(data)
        app.query_one("#api-password", Input).value = ""
        app.query_one("#ssh-password", Input).value = ""


if __name__ == "__main__":
    asyncio.run(main())
