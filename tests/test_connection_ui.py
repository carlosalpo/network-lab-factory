"""Credential entry, template selection and saved-session reauthentication."""

import asyncio
import json

from textual.widgets import Input, Select

from netlab.catalog import PROFILES
from netlab.gns3_portable import GNS3PortableSSH
from netlab.recipes import make_catalog_plan
from netlab.tui import WorkshopApp


def test_password_fields_are_masked_and_platform_switch_forgets_credentials():
    async def scenario():
        app = WorkshopApp()
        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.pause()
            app.query_one("#host", Input).value = "lab.example"
            app.query_one("#ssh-password", Input).value = "fixture-ssh-secret"
            assert app.query_one("#ssh-password", Input).password
            assert app.make_connector().password == "fixture-ssh-secret"
            app.query_one("#backend", Select).value = "gns3"
            await pilot.pause()
            assert app.query_one("#ssh-password", Input).value == ""
            assert app.query_one("#gns3-settings").display
            app.query_one("#host", Input).value = "gns3.example"
            app.query_one("#api-password", Input).value = "fixture-api-secret"
            assert app.query_one("#api-password", Input).password
            c = app.make_connector()
            assert isinstance(c, GNS3PortableSSH)
            assert c.api_password == "fixture-api-secret"
            assert "fixture-api-secret" not in json.dumps(c.connection())
            app.inventory = {"portable": True}
            app.query_one("#api-user", Input).value = "different-user"
            await pilot.pause()
            assert app.inventory is None
            app.query_one("#backend", Select).value = "eve"
            await pilot.pause()
            assert app.query_one("#api-password", Input).value == ""
            assert not app.query_one("#gns3-settings").display

    asyncio.run(scenario())


def test_portable_template_options_and_actual_ram_reach_review(monkeypatch):
    template = {
        "template_id": "11a11111-1111-4111-8111-111111111111",
        "name": "Site IOSv",
        "template_type": "qemu",
        "properties": {"ram": 768, "adapters": 4},
    }

    def run(self, action, **kwargs):
        if action == "inventory":
            result = {
                "portable": True,
                "templates": [template],
                "images": [],
                "memory_mib": 8192,
                "free_gib": 20,
                "version": "3.0.7",
                "api_version": "3",
                "projects_path": "/home/gns3/projects",
            }
            self.inventory = result
            return result
        if action == "preflight":
            assert self.template_map == {"iosv": template["template_id"]}
            assert kwargs["plan"]["nodes"][0]["device"]["image"] == PROFILES["iosv"]["image"]
            return {"required_ram_mib": 1536}
        raise AssertionError("No mutation permitted in this test")

    monkeypatch.setattr(GNS3PortableSSH, "run", run)

    async def scenario():
        app = WorkshopApp()
        async with app.run_test(size=(120, 40)) as pilot:
            app.query_one("#backend", Select).value = "gns3"
            await pilot.pause()
            app.query_one("#host", Input).value = "gns3.example"
            app.query_one("#api-password", Input).value = "fixture-api-secret"
            await pilot.pause()

            async def press(id):
                app.query_one("#" + id).focus()
                await pilot.press("enter")
                await app.workers.wait_for_complete()
                await pilot.pause()

            await press("connect")
            assert app.inventory
            await press("choose")
            await press("b01")
            assert app.query_one("#image-iosv", Select).value == template["template_id"]
            await press("preview")
            assert app.page == "review"
            assert "1536 MiB" in str(app.query_one("#review-summary").content)
            assert "fixture-api-secret" not in str(app.query_one("#review-summary").content)

    asyncio.run(scenario())


def test_saved_password_session_reconnects_without_creating(tmp_path, monkeypatch):
    plan = make_catalog_plan("B01", "existing", backend="gns3")
    c = GNS3PortableSSH(
        "lab.example",
        password="old-secret",
        api_password="api-secret",
        api_user="owner",
        projects_path="/home/gns3/projects",
    )
    result = {
        "status": "ready",
        "ports": {"r01": 5001, "r02": 5002},
        "path": "/owned",
        "preparation": {"status": "passed"},
        "exercise": {"status": "pending"},
    }
    for name, value in [("plan", plan), ("result", result), ("connection", c.connection())]:
        (tmp_path / (name + ".json")).write_text(json.dumps(value))
    calls = []

    def run(self, action, **kwargs):
        calls.append(action)
        assert self.password == "new-ssh-secret" and self.api_password == "new-api-secret"
        return {"portable": True}

    monkeypatch.setattr(GNS3PortableSSH, "run", run)

    async def scenario():
        app = WorkshopApp()
        async with app.run_test(size=(100, 35)) as pilot:
            app.load_workshop(tmp_path)
            await pilot.pause()
            assert app.page == "server" and app.resume_connection
            assert app.query_one("#backend", Select).value == "gns3"
            app.query_one("#ssh-password", Input).value = "new-ssh-secret"
            app.query_one("#api-password", Input).value = "new-api-secret"
            await pilot.pause()
            app.query_one("#connect").focus()
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.page == "result"
            assert calls == ["inventory"]

    asyncio.run(scenario())
