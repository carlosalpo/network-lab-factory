"""Drive real widgets and the deployment record, without touching an EVE server."""

import asyncio
import json
from contextlib import contextmanager

import pytest
from textual.filter import Monochrome, NoColor
from textual.widgets import Button, Input, RadioButton, Static

from netlab.tui import Dialog, WorkshopApp
from netlab.workshop import PROFILE


class FakeEve:
    def __init__(self, host, user, control, *, batch, cancel):
        self.host, self.user, self.control = host, user, control
        self.cancel = cancel
        self.actions = []
        self.fail = None
        self.empty = False
        self.block = False

    def run(self, action, callback=None, **kwargs):
        self.actions.append(action)
        if action == "inventory":
            return {
                "images": [] if self.empty else [PROFILE],
                "memory_mib": 8192,
                "free_gib": 40,
                "version": "test",
                "profile": "test",
            }
        if action == "preflight":
            return {}
        if action == "deploy":
            path = "/opt/unetlab/labs/test/" + kwargs["plan"]["name"] + ".unl"
            callback({"event": "created", "path": path})
            if self.block:
                assert self.cancel.wait(10), "Cancellation was not delivered to connector"
                raise RuntimeError("Operación cancelada")
            if self.fail:
                raise RuntimeError(self.fail)
            for node in ("r01", "r02"):
                callback({"event": "started", "node": node})
                callback({"event": "configured", "node": node})
            callback({"event": "verified", "status": "passed"})
            return {
                "status": "ready",
                "path": path,
                "ports": {"r01": 12345, "r02": 12346},
                "preparation": {"status": "passed"},
                "exercise": {
                    "status": "pending" if kwargs["plan"]["mode"] == "practice" else "passed"
                },
            }
        if action == "verify":
            return {
                "status": "passed",
                "scope": "exercise" if kwargs["exercise"] else "preparation",
                "checks": [],
            }
        raise AssertionError(action)


async def press(app, pilot, id):
    await pilot.pause()
    button = app.screen.query_one("#" + id, Button)
    button.focus()
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()


async def settle(app, pilot):
    await app.workers.wait_for_complete()
    await pilot.pause()


async def reach_review(app, pilot):
    app.query_one("#host", Input).value = "lab.example"
    await press(app, pilot, "connect")
    await settle(app, pilot)
    await press(app, pilot, "choose")
    await press(app, pilot, "b01")
    await press(app, pilot, "preview")
    await settle(app, pilot)
    assert app.page == "review"


def test_wizard_review_edit_confirm_deploy_verify_resume(tmp_path):
    async def scenario():
        app = WorkshopApp(connector_factory=FakeEve, output_root=tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await reach_review(app, pilot)
            assert app.connector.actions == ["inventory", "preflight"]
            assert not list(tmp_path.iterdir())
            assert app.query_one("#start", Button).disabled
            await pilot.press("escape")
            assert app.page == "prepare"
            app.query_one("#transit", Input).value = "10.7.0.0/31"
            app.query_one("#reference", RadioButton).value = True
            await press(app, pilot, "preview")
            await settle(app, pilot)
            assert "10.7.0.0/31" in str(app.query_one("#topology", Static).content)
            app.query_one("#confirmation", Input).value = "deploy"
            await pilot.pause()
            assert app.query_one("#start", Button).disabled
            app.query_one("#confirmation", Input).value = "DEPLOY"
            await pilot.pause()
            await press(app, pilot, "start")
            await settle(app, pilot)
            assert app.page == "result" and app.result["exercise"]["status"] == "passed"
            assert app.connector.actions.count("deploy") == 1
            assert (app.out / "events.json").is_file()
            assert "router ospf" in (app.out / "r01.cfg").read_text()
            await press(app, pilot, "check-exercise")
            await settle(app, pilot)
            assert list(app.out.glob("check-*.json"))
            out = app.out
        resumed = WorkshopApp(connector_factory=FakeEve, resume=out)
        async with resumed.run_test() as pilot:
            await pilot.pause()
            assert resumed.page == "result"
            assert resumed.result["exercise"]["status"] == "passed"
            assert not resumed.connector.actions

    asyncio.run(scenario())


def test_invalid_pools_and_changed_server_cannot_bypass_validation(tmp_path):
    async def scenario():
        app = WorkshopApp(connector_factory=FakeEve, output_root=tmp_path)
        async with app.run_test() as pilot:
            await reach_review(app, pilot)
            await pilot.press("escape")
            app.query_one("#loops", Input).value = "10.240.0.0/24"
            await press(app, pilot, "preview")
            assert app.page == "prepare"
            assert "overlap" in str(app.query_one("#prepare-error", Static).content)
            assert app.connector.actions.count("preflight") == 1
            await pilot.press("escape", "escape")
            app.query_one("#host", Input).value = "another.example"
            await pilot.pause()
            assert app.inventory is None and app.query_one("#choose", Button).disabled
            assert not list(tmp_path.iterdir())

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel", [False, True])
def test_failure_or_cancel_preserves_record_and_never_repeats_deployment(tmp_path, cancel):
    async def scenario():
        app = WorkshopApp(connector_factory=FakeEve, output_root=tmp_path)
        async with app.run_test(size=(100, 35)) as pilot:
            await reach_review(app, pilot)
            app.connector.fail = "r02 no inició"
            app.connector.block = cancel
            app.query_one("#confirmation", Input).value = "DEPLOY"
            await pilot.pause()
            await press(app, pilot, "start")
            if cancel:
                assert app.focused.id == "deploy"
                assert "Transcurrido" in str(app.query_one("#elapsed", Static).content)
                await pilot.press("ctrl+c")
                await pilot.pause()
                assert isinstance(app.screen, Dialog)
                await press(app, pilot, "confirm")
            await settle(app, pilot)
            assert app.page == "failure"
            assert json.loads((app.out / "result.json").read_text())["status"] == "incomplete"
            assert (app.out / "connection.json").exists()
            assert app.connector.actions.count("deploy") == 1
            out = app.out
        resumed = WorkshopApp(connector_factory=FakeEve, resume=out)
        async with resumed.run_test() as pilot:
            await pilot.pause()
            assert resumed.page == "failure"
            assert not resumed.connector.actions

    asyncio.run(scenario())


def test_no_compatible_image_keeps_scenario_unavailable(tmp_path):
    def empty(*args, **kwargs):
        connector = FakeEve(*args, **kwargs)
        connector.empty = True
        return connector

    async def scenario():
        app = WorkshopApp(connector_factory=empty, output_root=tmp_path)
        async with app.run_test() as pilot:
            app.query_one("#host", Input).value = "lab.example"
            await press(app, pilot, "connect")
            await settle(app, pilot)
            assert app.inventory is None and app.query_one("#choose", Button).disabled
            assert "no instalada" in str(app.query_one("#inventory", Static).content)

    asyncio.run(scenario())


def test_resize_keyboard_themes_and_help_preserve_inputs(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "")

    async def scenario():
        app = WorkshopApp(connector_factory=FakeEve, output_root=tmp_path)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert app.theme == "nlf-mono"
            await pilot.press("tab", "t")
            assert app.query_one("#host", Input).value.endswith("t")
            assert app.theme == "nlf-mono"
            await pilot.press("ctrl+t")
            assert app.theme == "nlf-dark"
            await reach_review(app, pilot)
            for size in [(120, 40), (80, 24), (60, 24), (50, 16)]:
                await pilot.resize_terminal(*size)
                await pilot.pause()
                assert app.query_one("#body").display
                assert app.query_one("#pages").region.right <= size[0]
                assert app.query_one("#topology").virtual_size.width <= size[0]
            await pilot.resize_terminal(40, 12)
            assert app.query_one("#too-small").display
            await pilot.resize_terminal(80, 24)
            await pilot.press("f1")
            assert isinstance(app.screen, Dialog)
            await pilot.press("escape")
            assert app.page == "review"
            assert app.query_one("#host", Input).value == "lab.example"

    asyncio.run(scenario())


def test_console_handoff_restores_ui_and_marks_observations_stale(tmp_path, monkeypatch):
    calls = []

    @contextmanager
    def suspended(self):
        calls.append("suspend")
        yield
        calls.append("resume")

    monkeypatch.setattr(WorkshopApp, "suspend", suspended)

    def child(args, **kwargs):
        calls.append(args)
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr("netlab.tui.subprocess.run", child)
    monkeypatch.setattr(
        FakeEve, "ssh_args", lambda self: ["ssh", "root@lab.example"], raising=False
    )

    async def scenario():
        app = WorkshopApp(connector_factory=FakeEve, output_root=tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await reach_review(app, pilot)
            app.query_one("#confirmation", Input).value = "DEPLOY"
            await pilot.pause()
            await press(app, pilot, "start")
            await settle(app, pilot)
            await press(app, pilot, "console-1")
            assert app.page == "result"
            assert calls == [
                "suspend",
                ["ssh", "-tt", "root@lab.example", "telnet -K -c 127.0.0.1 12345"],
                "resume",
            ]
            assert "nuevamente" in str(app.query_one("#check-result", Static).content)

    asyncio.run(scenario())


def test_linear_keyboard_navigation_and_fixed_action_bar(tmp_path):
    async def scenario():
        app = WorkshopApp(connector_factory=FakeEve, output_root=tmp_path)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            await pilot.press("tab", *"lab.example", "enter")
            assert app.focused.id == "connect"
            nav_y = app.query_one("#navigation").region.y
            assert not app.query_one("#authenticate").display
            await pilot.press("enter")
            await settle(app, pilot)
            assert app.focused.id == "choose"
            assert not app.query_one("#connect").display
            await pilot.press("enter")
            assert app.page == "scenario"
            assert app.focused.id == "level"
            assert app.query_one("#level").region.y < app.query_one("#navigation").region.y
            for _ in range(8):
                if app.focused.id == "b01":
                    break
                await pilot.press("tab")
            await pilot.press("enter")
            assert app.page == "prepare"
            assert app.query_one("#navigation").region.y == nav_y
            assert not app.query_one("#image").can_focus
            # The primary action is reachable using Tab, without moving focus directly.
            for _ in range(12):
                if app.focused.id == "preview":
                    break
                await pilot.press("tab")
            assert app.focused.id == "preview"
            await pilot.press("enter")
            await settle(app, pilot)
            assert app.page == "review" and app.focused.id == "review"
            assert app.query_one("#navigation").region.y == nav_y
            await pilot.press("tab")
            assert app.focused.id == "confirmation"
            await pilot.press(*"DEPLOY", "enter")
            assert app.focused.id == "start"
            assert app.connector.actions.count("deploy") == 0
            await pilot.press("enter")
            await settle(app, pilot)
            assert app.page == "result"
            assert app.connector.actions.count("deploy") == 1

    asyncio.run(scenario())


def test_back_button_preserves_fields_and_action_stays_visible_when_scrolling(tmp_path):
    async def scenario():
        app = WorkshopApp(connector_factory=FakeEve, output_root=tmp_path)
        async with app.run_test(size=(60, 24)) as pilot:
            await reach_review(app, pilot)
            for page, next_id in (
                ("review", "start"),
                ("prepare", "preview"),
                ("scenario", "b01"),
                ("server", "choose"),
            ):
                assert app.page == page
                visible = [b.id for b in app.query("#navigation Button") if b.display]
                assert visible == ["back", next_id]
                app.query_one("#" + page).scroll_end(animate=False)
                await pilot.pause()
                action = app.query_one("#" + next_id)
                assert 0 <= action.region.y < 24 and action.region.bottom <= 24
                if page != "server":
                    await press(app, pilot, "back")
            assert app.query_one("#host", Input).value == "lab.example"
            assert app.inventory is not None

    asyncio.run(scenario())


def test_explicit_theme_switch_can_restore_color_after_no_color(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")

    async def scenario():
        app = WorkshopApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert any(isinstance(f, (Monochrome, NoColor)) for f in app.get_line_filters())
            await pilot.press("ctrl+t")
            assert app.theme == "nlf-dark"
            assert not any(isinstance(f, (Monochrome, NoColor)) for f in app.get_line_filters())
            assert "Oscuro" in str(app.query_one("#brand", Static).content)
            assert os.environ["NO_COLOR"] == "1"

    import os

    asyncio.run(scenario())


def test_catalog_selection_versions_and_missing_capability(tmp_path):
    from textual.widgets import Select

    from netlab.catalog import CATALOG, PROFILES

    async def scenario():
        app = WorkshopApp(connector_factory=FakeEve, output_root=tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            app.query_one("#host", Input).value = "lab.example"
            await press(app, pilot, "connect")
            await settle(app, pilot)
            await press(app, pilot, "choose")
            app.query_one("#scenario-choice", Select).value = "B03"
            await pilot.pause()
            await press(app, pilot, "b01")
            await press(app, pilot, "preview")
            assert app.page == "prepare"
            assert "imagen compatible" in str(app.query_one("#prepare-error", Static).content)
            assert app.connector.actions == ["inventory"]
            app.inventory["images"] = [p["image"] for p in PROFILES.values() if p["image"]]
            app.inventory["vpcs"] = True
            app.refresh_profiles()
            await pilot.pause(0.3)
            await press(app, pilot, "preview")
            await settle(app, pilot)
            assert app.page == "review", str(app.query_one("#prepare-error", Static).content)
            assert app.plan["scenario"] == "B03" and len(app.plan["nodes"]) == 6
            assert app.connector.actions.count("deploy") == 0
            await pilot.press("escape", "escape")
            for level in ("Intermedio", "Avanzado"):
                app.query_one("#level", Select).value = level
                await pilot.pause()
                assert CATALOG[app.scenario_id]["level"] == level
            app.query_one("#scenario-choice", Select).value = "A08"
            await pilot.pause()
            await press(app, pilot, "b01")
            assert (
                app.query_one("#image-nxos", Select).value
                != app.query_one("#image-nxos105", Select).value
            )
            app.query_one("#image-nxos105", Select).value = app.query_one(
                "#image-nxos", Select
            ).value
            await press(app, pilot, "preview")
            assert app.page == "prepare"
            assert "diferentes" in str(app.query_one("#prepare-error", Static).content)

    asyncio.run(scenario())


def test_backend_switch_clears_inventory_and_selects_guest_access(monkeypatch):
    from textual.widgets import Select

    from netlab.gns3_qga import GNS3QGA

    monkeypatch.setenv("NLF_GNS3_GUEST_ID", "110")
    monkeypatch.setenv("NLF_GNS3_HOST", "proxmox.example")
    monkeypatch.setenv("NLF_GNS3_SSH_CONTROL", "/tmp/gns3-session")

    async def scenario():
        app = WorkshopApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert app.focused.id == "backend"
            app.inventory = {"images": ["stale-image"]}
            app.query_one("#backend", Select).value = "gns3"
            await pilot.pause()
            assert app.inventory is None
            assert app.query_one("#host", Input).value == "proxmox.example"
            assert app.query_one("#user", Input).value == "root"
            assert app.query_one("#choose", Button).disabled
            c = app.make_connector()
            assert isinstance(c, GNS3QGA) and c.guest_id == 110
            assert c.control == "/tmp/gns3-session"
            app.query_one("#backend", Select).value = "eve"
            await pilot.pause()
            assert app.backend == "eve" and app.inventory is None
            assert app.control != "/tmp/gns3-session"

    asyncio.run(scenario())
