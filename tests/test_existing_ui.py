"""Exercise the real terminal widgets with read-only synthetic lab responses."""

import asyncio

from test_existing_addressing import snapshot
from textual.widgets import Button, Input, Select, Static

from netlab.existing import ExistingLabSSH
from netlab.tui import WorkshopApp


def test_existing_wizard_mixed_plan_export_and_explicit_apply(monkeypatch, tmp_path):
    actions = []

    def run(self, action, **values):
        actions.append((action, values))
        if action == "existing-list":
            return {
                "folders": ["/Study"],
                "labs": [{"id": "fixture", "name": "Study lab", "state": "opened"}],
            }
        if action == "existing-read":
            return {"snapshot": snapshot()}
        if action == "existing-apply":
            assert values["confirm"] == "Study lab"
            assert values["intent"]["segments"]["b"]["subnet"] == "10.10.30.0/30"
            return {
                "status": "verified",
                "run_id": "fixture",
                "backup_path": "/private/fixture",
                "attempted": ["1", "2", "3", "4"],
                "verified": ["1", "2", "3", "4"],
            }
        if action == "existing-save":
            assert values["confirm"] == "SAVE"
            return {
                "status": "saved",
                "saved_nodes": ["1", "2", "3", "4"],
                "backup_path": "/private/fixture",
            }
        raise AssertionError(action)

    monkeypatch.setattr(ExistingLabSSH, "run", run)

    async def scenario():
        app = WorkshopApp()
        async with app.run_test(size=(110, 42)) as pilot:
            app.query_one("#host", Input).value = "fixture.example"
            await pilot.click("#existing-open")
            await pilot.pause()
            screen = app.screen
            screen.output_root = tmp_path
            assert screen.query_one("#existing-eve-password", Input).password
            assert screen.query_one("#existing-device-password", Input).password
            assert screen.query_one("#existing-device-enable", Input).password
            screen.query_one("#existing-list", Button).press()
            await pilot.pause(0.15)
            screen.query_one("#existing-lab", Select).value = "fixture"
            await pilot.pause()
            screen.query_one("#existing-read", Button).press()
            await pilot.pause(0.15)
            assert screen.stage == "existing-addressing"
            screen.query_one("#existing-add-group", Button).press()
            await pilot.pause()
            screen.query_one("#existing-auto", Button).press()
            await pilot.pause()
            assert len(screen.intent["segments"]) == 2
            screen.query_one("#existing-segment", Select).value = "b"
            await pilot.pause()
            screen.query_one("#existing-subnet", Input).value = "10.10.30.0/30"
            screen.query_one("#existing-endpoint", Select).value = "3|GigabitEthernet0/0"
            await pilot.pause()
            screen.query_one("#existing-fixed", Input).value = "10.10.30.2"
            screen.query_one("#existing-pin", Button).press()
            await pilot.pause()
            screen.query_one("#existing-include", Button).press()
            await pilot.pause()
            screen.query_one("#existing-preview", Button).press()
            await pilot.pause()
            assert screen.stage == "existing-review"
            assert screen.plan["segments"][0]["subnet"] == "10.10.30.4/30"
            assert screen.plan["changes"][2]["after"] == "10.10.30.2/30"
            assert [a for a, _ in actions] == ["existing-list", "existing-read"]
            screen.query_one("#existing-export", Button).press()
            await pilot.pause()
            assert (screen.exported / "plan.json").is_file()
            screen.query_one("#existing-apply", Button).press()
            await pilot.pause()
            assert len(actions) == 2  # Empty confirmation must never reach the connector.
            screen.query_one("#existing-confirm", Input).value = "Study lab"
            screen.query_one("#existing-apply", Button).press()
            await pilot.pause(0.15)
            assert screen.stage == "existing-result"
            assert not screen.query_one("#existing-save", Button).disabled
            screen.query_one("#existing-save", Button).press()
            await pilot.pause()
            assert len(actions) == 3
            screen.query_one("#existing-save-confirm", Input).value = "SAVE"
            screen.query_one("#existing-save", Button).press()
            await pilot.pause(0.15)
            assert screen.query_one("#existing-save", Button).disabled

    asyncio.run(scenario())


def test_unknown_apply_outcome_disables_retry_and_busy_navigation():
    async def scenario():
        app = WorkshopApp()
        async with app.run_test(size=(90, 30)) as pilot:
            app.query_one("#host", Input).value = "fixture.example"
            await pilot.click("#existing-open")
            await pilot.pause()
            screen = app.screen
            screen.busy = True
            screen.action_back()
            assert app.screen is screen
            app.action_request_exit()
            assert app.screen is screen
            screen.finish("existing-apply", None, "Connection lost")
            assert screen.query_one("#existing-apply", Button).disabled
            assert "partial" in str(screen.query_one("#existing-status", Static).render())

    asyncio.run(scenario())
