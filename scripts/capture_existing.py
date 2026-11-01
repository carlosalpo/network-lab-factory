"""Capture actual addressing widgets using the public synthetic lab fixture."""

import asyncio
import json
from pathlib import Path

from textual.widgets import Button

from netlab.existing_ui import ExistingLabScreen
from netlab.tui import WorkshopApp
from netlab.wizard import EveSSH


async def capture(theme, size, filename):
    root = Path(__file__).resolve().parents[1]
    fixture = root / "examples/existing-lab"
    app = WorkshopApp(theme=theme)
    async with app.run_test(size=size) as pilot:
        screen = ExistingLabScreen(EveSSH("fixture.example"))
        await app.push_screen(screen)
        await pilot.pause()
        screen.finish(
            "existing-read", {"snapshot": json.loads((fixture / "snapshot.json").read_text())}, None
        )
        screen.intent = json.loads((fixture / "intent.json").read_text())
        screen.query_one("#existing-preview", Button).press()
        await pilot.pause()
        data = app.export_screenshot(
            title="Network Lab Factory · synthetic addressing review · no lab contacted"
        )
        (root / "docs/screenshots/workshop" / filename).write_text(data)


async def main():
    await capture("dark", (150, 58), "existing-review.svg")
    await capture("light", (150, 58), "existing-review-light.svg")
    await capture("dark", (80, 32), "existing-review-narrow.svg")


if __name__ == "__main__":
    asyncio.run(main())
