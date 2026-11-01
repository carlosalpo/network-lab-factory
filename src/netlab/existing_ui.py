"""Existing lab addressing flow, hosted inside the current terminal assistant."""

import json
import re
from pathlib import Path
from typing import ClassVar

from textual import work
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Checkbox,
    Collapsible,
    ContentSwitcher,
    DataTable,
    Input,
    Select,
    Static,
)

from .addressing import compile_addressing, endpoint_key, ipv4_network
from .existing import ExistingLabSSH, export_review


class ExistingLabScreen(Screen):
    BINDINGS: ClassVar = [("escape", "back", "Back")]
    DEFAULT_CSS = """
    ExistingLabScreen #existing-pages { height: 1fr; }
    ExistingLabScreen .page { padding: 1 3; }
    ExistingLabScreen DataTable { height: 9; margin: 1 0; }
    ExistingLabScreen #existing-heading { padding: 1 3; color: $primary; text-style: bold; }
    ExistingLabScreen #existing-status { padding: 1 3; height: auto; max-height: 6; }
    ExistingLabScreen #existing-nav { height: 4; padding: 0 3; }
    ExistingLabScreen .actions { height: auto; layout: vertical; }
    ExistingLabScreen .actions Button { width: 1fr; max-width: 48; }
    ExistingLabScreen Checkbox { margin: 1 0; }
    """

    def __init__(self, base, *, output_root=Path("build/existing")):
        super().__init__()
        self.base, self.output_root = base, output_root
        self.connector = None
        self.snapshot = self.plan = self.result = self.exported = None
        self.intent = {"groups": {}, "segments": {}}
        self.endpoint_mappings, self.endpoint_fixed = {}, {}
        self.busy = False
        self.stage = "existing-access"

    def compose(self):
        yield Static(
            "Prepare an existing lab · Access → Addressing → Review → Result",
            id="existing-heading",
            markup=False,
        )
        with ContentSwitcher(initial="existing-access", id="existing-pages"):
            with VerticalScroll(id="existing-access", classes="page"):
                yield Static("Choose the lab you already built", classes="title")
                yield Static(
                    "Read-only discovery. Start the routers in your platform first. This preview does not create links or start devices.",
                    classes="muted",
                )
                with Collapsible(title="EVE-NG web access", collapsed=False, id="existing-eve"):
                    yield Static(
                        "EVE API address · loopback HTTP or trusted HTTPS", classes="label"
                    )
                    yield Input("http://127.0.0.1", id="existing-eve-url")
                    yield Static("EVE web username", classes="label")
                    yield Input("admin", id="existing-eve-user")
                    yield Static("EVE web password", classes="label")
                    yield Input(password=True, id="existing-eve-password")
                    yield Static(
                        "Use a dedicated existing EVE account if possible: an API login can end that account's browser session. TLS certificate checks remain enabled.",
                        classes="muted",
                    )
                yield Static(
                    "EVE folder · / for the root (GNS3 lists all accessible projects)",
                    classes="label",
                )
                yield Input("/", id="existing-folder")
                yield Button("List laboratories", id="existing-list", variant="primary")
                yield Static("Folders", classes="label")
                yield Select([], id="existing-folders", prompt="Choose a folder")
                yield Static("Laboratory", classes="label")
                yield Select([], id="existing-lab", prompt="List laboratories first")
                with Collapsible(
                    title="Router login · shared by selected lab devices", collapsed=True
                ):
                    yield Static(
                        "Leave blank when the console is already authenticated. Passwords remain in memory for this screen only.",
                        classes="muted",
                    )
                    yield Static("Device username", classes="label")
                    yield Input(id="existing-device-user")
                    yield Static("Device password", classes="label")
                    yield Input(password=True, id="existing-device-password")
                    yield Static("Enable password", classes="label")
                    yield Input(password=True, id="existing-device-enable")
                yield Button("Read topology and addresses", id="existing-read", disabled=True)
            with VerticalScroll(id="existing-addressing", classes="page"):
                yield Static("Pools and connections", classes="title")
                yield Static("", id="existing-observations", markup=False)
                with Collapsible(title="Group pools", collapsed=False):
                    yield DataTable(id="existing-groups")
                    yield Static(
                        "Group name · enter an existing name to update it", classes="label"
                    )
                    yield Input("Internal", id="existing-group-name")
                    yield Static("Pool · network/prefix", classes="label")
                    yield Input("10.10.30.0/24", id="existing-pool")
                    yield Static(
                        "Reserved ranges · optional, comma-separated CIDRs", classes="label"
                    )
                    yield Input(
                        placeholder="10.10.30.128/26, 10.10.30.200/32", id="existing-exclude"
                    )
                    yield Button("Add or update group", id="existing-add-group")
                yield Static("Connection / broadcast segment", classes="label")
                yield Select([], id="existing-segment")
                yield Static("Group", classes="label")
                yield Select([], id="existing-group")
                yield Static(
                    "Subnet · blank for automatic or preserved addressing", classes="label"
                )
                yield Input(placeholder="Automatic, or 10.10.30.8/30", id="existing-subnet")
                yield Static("Automatic subnet size", classes="label")
                yield Select(
                    [(f"/{p}", p) for p in (30, 31, 29, 28, 27, 26, 25, 24)],
                    value=30,
                    allow_blank=False,
                    id="existing-prefix",
                )
                yield Checkbox(
                    "I confirm these endpoints share one broadcast segment", id="existing-shared"
                )
                with Collapsible(title="Endpoint mapping and fixed addresses", collapsed=True):
                    yield Static(
                        "Match platform ports to observed IOS interfaces. Pin an IP only when needed. Save each endpoint override before including the connection.",
                        classes="muted",
                    )
                    yield Select([], id="existing-endpoint", prompt="Select an endpoint")
                    yield Select([], id="existing-interface", prompt="Select its IOS interface")
                    yield Input(
                        placeholder="Fixed host IP, or blank for automatic", id="existing-fixed"
                    )
                    yield Button("Set endpoint override", id="existing-pin")
                with VerticalScroll(classes="actions"):
                    yield Button(
                        "Include / update connection", id="existing-include", variant="primary"
                    )
                    yield Button("Remove connection from plan", id="existing-remove")
                    yield Button("Use group for eligible links", id="existing-auto")
                yield Static("", id="existing-selected", markup=False)
                yield Button("Build addressing preview", id="existing-preview", variant="primary")
            with VerticalScroll(id="existing-review", classes="page"):
                yield Static("Review before changing the lab", classes="title")
                yield Static("", id="existing-review-summary", markup=False)
                yield DataTable(id="existing-changes")
                yield Static("", id="existing-networks", markup=False)
                with Collapsible(title="Review generated IOS commands", collapsed=True):
                    yield Static("", id="existing-command-preview", markup=False)
                yield Static(
                    "Existing IPs and shutdown state are preserved. Only missing addresses are added. Review includes no VLAN, routing or interface activation commands. No automatic rollback or retry occurs after a partial failure.",
                    classes="muted",
                )
                yield Button("Export plan and commands", id="existing-export")
                yield Static(
                    "Type the exact lab name to apply the reviewed changes", classes="label"
                )
                yield Input(id="existing-confirm")
                yield Button("Back up, apply and verify", id="existing-apply", variant="primary")
            with VerticalScroll(id="existing-result", classes="page"):
                yield Static("Application result", classes="title")
                yield Static("", id="existing-result-summary", markup=False)
                yield Static(
                    "Verification checks configured IPs and preserved shutdown state. It does not certify connectivity. Private server backups can contain secrets; do not publish them.",
                    classes="muted",
                )
                yield Static(
                    "Optional: type SAVE to write running configuration to startup configuration on changed devices. This persists all their current settings, including changes made before this assistant.",
                    classes="label",
                )
                yield Input(id="existing-save-confirm")
                yield Button("Save permanently", id="existing-save", disabled=True)
        yield Static("", id="existing-status", markup=False)
        with Horizontal(id="existing-nav"):
            yield Button("Back", id="existing-back")

    def on_mount(self):
        self.query_one("#existing-eve").display = self.base.backend == "eve"
        self.query_one("#existing-folder").disabled = self.base.backend == "gns3"
        self.query_one("#existing-groups", DataTable).add_columns("Group", "Pool", "Reserved")
        self.query_one("#existing-changes", DataTable).add_columns(
            "Device / interface", "Group", "Before", "After", "Action"
        )

    def message(self, value):
        self.query_one("#existing-status", Static).update(value)

    def show(self, stage):
        self.stage = stage
        self.query_one("#existing-pages", ContentSwitcher).current = stage
        self.query_one("#" + stage).scroll_home(animate=False)

    def action_back(self):
        if self.busy:
            self.message(
                "Operation in progress. Wait for its result before leaving; do not retry uncertain writes."
            )
            return
        if self.stage == "existing-review":
            self.plan = self.exported = None
            self.show("existing-addressing")
        elif self.stage == "existing-addressing":
            self.snapshot = self.plan = None
            self.intent = {"groups": {}, "segments": {}}
            self.show("existing-access")
        else:
            for field in (
                "existing-eve-password",
                "existing-device-password",
                "existing-device-enable",
            ):
                self.query_one("#" + field, Input).value = ""
            if self.connector:
                self.connector.device_credentials.clear()
                self.connector.api_password = self.connector.password = None
                self.connector.settings["api_password"] = None
            self.dismiss()

    def value(self, name):
        return self.query_one("#existing-" + name, Input).value.strip()

    def selected(self, name):
        return self.query_one("#existing-" + name, Select).value

    def segment(self):
        return next(s for s in self.snapshot["segments"] if s["id"] == self.selected("segment"))

    def refresh_selected(self):
        lines = ["Included connections: " + str(len(self.intent["segments"]))]
        for sid, choice in self.intent["segments"].items():
            seg = next(s for s in self.snapshot["segments"] if s["id"] == sid)
            lines.append(
                seg["name"]
                + " · "
                + choice["group"]
                + " · "
                + (choice["subnet"] or "automatic / preserved")
            )
        self.query_one("#existing-selected", Static).update("\n".join(lines))

    def on_select_changed(self, event):
        if event.value is Select.NULL:
            return
        name = event.select.id
        if name == "existing-folders":
            self.query_one("#existing-folder", Input).value = str(event.value)
        elif name == "existing-lab":
            self.query_one("#existing-read", Button).disabled = self.connector is None
        elif name == "existing-segment" and self.snapshot:
            seg = self.segment()
            choice = self.intent["segments"].get(seg["id"], {})
            self.endpoint_mappings = dict(choice.get("interfaces", {}))
            self.endpoint_fixed = dict(choice.get("fixed", {}))
            self.query_one("#existing-subnet", Input).value = choice.get("subnet", "")
            self.query_one("#existing-prefix", Select).value = choice.get("prefix", 30)
            self.query_one("#existing-shared", Checkbox).value = choice.get("confirm_shared", False)
            if choice.get("group"):
                self.query_one("#existing-group", Select).value = choice["group"]
            names = {n["id"]: n["name"] for n in self.snapshot["nodes"]}
            self.query_one("#existing-endpoint", Select).set_options(
                [
                    (names[e["node"]] + " · " + e["interface"], endpoint_key(e))
                    for e in seg["endpoints"]
                ]
            )
        elif name == "existing-endpoint" and self.snapshot:
            ep = next(e for e in self.segment()["endpoints"] if endpoint_key(e) == event.value)
            node = next(n for n in self.snapshot["nodes"] if n["id"] == ep["node"])
            options = [
                (name + " · " + (i["address"] or "unassigned"), name)
                for name, i in node.get("interfaces", {}).items()
                if not i["blocked"]
            ]
            widget = self.query_one("#existing-interface", Select)
            widget.set_options(options)
            mapped = self.endpoint_mappings.get(event.value, ep["interface"])
            if mapped in {v for _, v in options}:
                widget.value = mapped
            self.query_one("#existing-fixed", Input).value = self.endpoint_fixed.get(
                ep["node"] + "|" + mapped, ""
            )

    def on_input_changed(self, event):
        if event.input.id in {"existing-eve-url", "existing-eve-user", "existing-eve-password"}:
            self.connector = None
            self.query_one("#existing-read", Button).disabled = True

    def on_button_pressed(self, event):
        event.stop()
        action = event.button.id
        if self.busy:
            return
        try:
            if action == "existing-back":
                self.action_back()
            elif action == "existing-list":
                self.connector = ExistingLabSSH(
                    self.base,
                    eve_url=self.value("eve-url"),
                    eve_user=self.value("eve-user"),
                    eve_password=self.query_one("#existing-eve-password", Input).value,
                )
                self.start_remote(action, folder=self.value("folder"))
            elif action == "existing-read":
                if not isinstance(self.selected("lab"), str):
                    raise ValueError("Select a laboratory first.")
                self.connector.device_credentials = {
                    "user": self.value("device-user"),
                    "password": self.query_one("#existing-device-password", Input).value,
                    "enable": self.query_one("#existing-device-enable", Input).value,
                }
                self.start_remote(action, lab_id=self.selected("lab"))
            elif action == "existing-add-group":
                if re.fullmatch(r"\d{1,3}\.\d{1,3}\.\d{1,3}", self.value("pool")):
                    suggestion = str(ipv4_network(self.value("pool") + ".0/24"))
                    self.query_one("#existing-pool", Input).value = suggestion
                    self.message(
                        "Suggested "
                        + suggestion
                        + ". Check the prefix and select Add or update group again to confirm."
                    )
                    return
                pool = str(ipv4_network(self.value("pool")))
                name = self.value("group-name")
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,47}", name):
                    raise ValueError("Enter a short group name, for example Internal or Site A.")
                exclusions = [
                    str(ipv4_network(v.strip()))
                    for v in self.value("exclude").split(",")
                    if v.strip()
                ]
                self.intent["groups"][name] = {"pool": pool, "exclude": exclusions}
                table = self.query_one("#existing-groups", DataTable)
                table.clear()
                for group, value in self.intent["groups"].items():
                    table.add_row(group, value["pool"], ", ".join(value["exclude"]) or "None")
                self.query_one("#existing-group", Select).set_options(
                    [(n, n) for n in self.intent["groups"]]
                )
                self.query_one("#existing-group", Select).value = name
                self.message(
                    "Group saved. Include connections below; the preview checks pool conflicts."
                )
            elif action == "existing-pin":
                ep = next(
                    e
                    for e in self.segment()["endpoints"]
                    if endpoint_key(e) == self.selected("endpoint")
                )
                mapped = self.selected("interface")
                if not isinstance(mapped, str):
                    raise ValueError("Choose an observed IOS interface.")
                key = endpoint_key(ep)
                old = self.endpoint_mappings.get(key, ep["interface"])
                self.endpoint_fixed.pop(ep["node"] + "|" + old, None)
                self.endpoint_mappings[key] = mapped
                if self.value("fixed"):
                    self.endpoint_fixed[ep["node"] + "|" + mapped] = self.value("fixed")
                self.message(
                    "Endpoint override set. Include / update the connection to save it in the plan."
                )
            elif action in ("existing-include", "existing-auto"):
                group = self.selected("group")
                if group not in self.intent["groups"]:
                    raise ValueError("Add and select a group first.")
                if action == "existing-auto":
                    for seg in self.snapshot["segments"]:
                        if seg.get("blocked") or seg.get("shared") or len(seg["endpoints"]) != 2:
                            continue
                        nodes = {n["id"]: n for n in self.snapshot["nodes"]}
                        if all(
                            not nodes[e["node"]].get("error")
                            and e["interface"] in nodes[e["node"]].get("interfaces", {})
                            and not nodes[e["node"]]["interfaces"][e["interface"]]["blocked"]
                            for e in seg["endpoints"]
                        ):
                            self.intent["segments"].setdefault(
                                seg["id"],
                                {
                                    "group": group,
                                    "subnet": "",
                                    "prefix": self.selected("prefix"),
                                    "fixed": {},
                                },
                            )
                    self.message(
                        "Added eligible direct links. Existing choices are preserved; shared or unmapped segments need individual review."
                    )
                else:
                    seg = self.segment()
                    self.intent["segments"][seg["id"]] = {
                        "group": group,
                        "subnet": self.value("subnet"),
                        "prefix": self.selected("prefix"),
                        "confirm_shared": self.query_one("#existing-shared", Checkbox).value,
                        "interfaces": dict(self.endpoint_mappings),
                        "fixed": dict(self.endpoint_fixed),
                    }
                    self.message("Connection saved in the plan.")
                self.refresh_selected()
            elif action == "existing-remove":
                self.intent["segments"].pop(self.segment()["id"], None)
                self.refresh_selected()
            elif action == "existing-preview":
                self.plan = compile_addressing(self.snapshot, json.loads(json.dumps(self.intent)))
                table = self.query_one("#existing-changes", DataTable)
                table.clear()
                for c in self.plan["changes"]:
                    table.add_row(
                        c["device"] + " " + c["interface"],
                        c["group"],
                        c["before"] or "unassigned",
                        c["after"],
                        "Add IP" if c["change"] else "Keep",
                    )
                from .addressing import config_commands

                previews = []
                for nid in sorted({c["node"] for c in self.plan["changes"]}):
                    changes = [c for c in self.plan["changes"] if c["node"] == nid]
                    previews.append(
                        changes[0]["device"]
                        + "\n"
                        + ("\n".join(config_commands(changes)) or "No changes")
                    )
                self.query_one("#existing-command-preview", Static).update("\n\n".join(previews))
                network_lines = []
                for segment in self.plan["segments"]:
                    choice = self.plan["intent"]["segments"][segment["id"]]
                    preserved = any(
                        c["before"] for c in self.plan["changes"] if c["segment"] == segment["id"]
                    )
                    mode = (
                        "Fixed subnet"
                        if choice.get("subnet")
                        else "Preserved subnet"
                        if preserved
                        else "Automatic subnet"
                    )
                    network_lines.append(segment["name"] + " · " + segment["subnet"] + " · " + mode)
                self.query_one("#existing-networks", Static).update("\n".join(network_lines))
                blocked = any(n.get("error") for n in self.snapshot["nodes"])
                self.query_one("#existing-apply", Button).disabled = blocked or not any(
                    c["change"] for c in self.plan["changes"]
                )
                self.query_one("#existing-review-summary", Static).update(
                    self.snapshot["lab"]["name"]
                    + "\n"
                    + (
                        "Export only: not every lab node was readable. Conflict detection is incomplete."
                        if blocked
                        else "All lab nodes were read. Configuration and topology will be rechecked before writing."
                    )
                )
                self.query_one("#existing-confirm", Input).value = ""
                self.exported = None
                self.show("existing-review")
                self.message(
                    "Review the included connections and commands. Nothing has been applied."
                )
            elif action == "existing-export":
                self.exported = export_review(self.plan, self.output_root)
                self.message("Private review bundle: " + str(self.exported.resolve()))
            elif action == "existing-apply":
                if self.value("confirm") != self.snapshot["lab"]["name"]:
                    raise ValueError("Type the exact lab name shown above.")
                if self.exported is None:
                    self.exported = export_review(self.plan, self.output_root)
                self.start_remote(
                    action,
                    snapshot=self.snapshot,
                    intent=self.plan["intent"],
                    confirm=self.value("confirm"),
                )
            elif action == "existing-save":
                if self.value("save-confirm") != "SAVE":
                    raise ValueError("Type SAVE to persist the verified configuration.")
                self.start_remote(action, run_id=self.result["run_id"], confirm="SAVE")
        except (ValueError, KeyError, StopIteration, OSError) as exc:
            self.message(str(exc) or "Select a connection or endpoint first.")

    def start_remote(self, action, **values):
        self.busy = True
        self.query_one("#existing-pages").disabled = True
        self.query_one("#existing-back", Button).disabled = True
        self.message(
            {
                "existing-list": "Listing accessible laboratories…",
                "existing-read": "Reading topology and IOS configurations…",
                "existing-apply": "Rechecking, backing up, applying and verifying. Do not close the terminal…",
                "existing-save": "Saving verified configurations. Do not close the terminal…",
            }[action]
        )
        self.remote(action, values)

    @work(thread=True, exclusive=True)
    def remote(self, action, values):
        try:
            result = self.connector.run(action, **values)
        except Exception as exc:  # noqa: BLE001 — render the transport's redacted failure.
            self.app.call_from_thread(self.finish, action, None, str(exc))
        else:
            self.app.call_from_thread(self.finish, action, result, None)

    def finish(self, action, result, error):
        self.busy = False
        self.query_one("#existing-pages").disabled = False
        self.query_one("#existing-back", Button).disabled = False
        if error:
            self.message(error)
            if action in ("existing-apply", "existing-save"):
                self.query_one("#" + action, Button).disabled = True
                self.message(
                    error
                    + "\nOutcome may be partial. Inspect the lab and private server journal before starting a new operation; this operation will not retry."
                )
            return
        if action == "existing-list":
            self.query_one("#existing-folders", Select).set_options(
                [(p, p) for p in result["folders"]]
            )
            self.query_one("#existing-lab", Select).set_options(
                [(p["name"] + " · " + p["state"], p["id"]) for p in result["labs"]]
            )
            self.query_one("#existing-read", Button).disabled = True
            self.message(
                f"{len(result['labs'])} laboratories found. Choose one to read; no devices were changed."
            )
        elif action == "existing-read":
            self.snapshot = result["snapshot"]
            self.intent = {"groups": {}, "segments": {}}
            self.query_one("#existing-groups", DataTable).clear()
            self.query_one("#existing-group", Select).set_options([])
            self.query_one("#existing-segment", Select).set_options(
                [
                    (s["name"] + (" · blocked" if s["blocked"] else ""), s["id"])
                    for s in self.snapshot["segments"]
                ]
            )
            self.query_one("#existing-observations", Static).update(
                "\n".join(
                    n["name"] + ": " + (n.get("error") or f"{len(n['interfaces'])} interfaces read")
                    for n in self.snapshot["nodes"]
                )
            )
            self.refresh_selected()
            self.show("existing-addressing")
            self.message(
                "Add group pools, then select connections. Only included connections appear in the preview."
            )
        elif action in ("existing-apply", "existing-save"):
            if action == "existing-apply":
                self.result = result
            labels = {
                "verified": "Addresses verified · not saved permanently",
                "saved": "Configuration saved permanently",
                "incomplete": "Application incomplete · inspect the lab before continuing",
                "save-incomplete": "Permanent save incomplete · inspect the lab",
            }
            summary = [
                labels.get(result["status"], result["status"]),
                "Private backup on the SSH server: " + result["backup_path"],
            ]
            if action == "existing-apply":
                summary.append(
                    f"Devices attempted: {len(result['attempted'])} · verified: {len(result['verified'])}"
                )
            else:
                summary.append(f"Devices saved: {len(result['saved_nodes'])}")
            self.query_one("#existing-result-summary", Static).update("\n\n".join(summary))
            self.query_one("#existing-save", Button).disabled = result[
                "status"
            ] != "verified" or not result.get("attempted")
            self.show("existing-result")
            self.message(
                "Running configuration verified; nothing saved permanently."
                if result["status"] == "verified"
                else "Operation: " + result["status"] + ". Inspect the result before continuing."
            )
