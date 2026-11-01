"""Terminal workshop UI. All remote work goes through the existing EVE adapter."""

import json
import os
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult, SuspendNotSupported
from textual.binding import Binding
from textual.containers import Horizontal, VerticalGroup, VerticalScroll
from textual.filter import Monochrome, NoColor
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import (
    Button,
    Collapsible,
    ContentSwitcher,
    Footer,
    Input,
    RadioButton,
    RadioSet,
    RichLog,
    Select,
    Static,
)

from .catalog import CATALOG, PROFILES
from .catalog_render import ascii_topology
from .language import english
from .recipes import make_catalog_plan
from .wizard import (
    EveSSH,
    connector_from_record,
    deploy_plan,
    gns3_transport_options,
    save_json,
    update_observation,
)
from .workshop import PROFILE, make_plan, validate_plan

STEPS = ("Server", "Scenario", "Preparation", "Review", "Deployment", "Lab")
PAGES = ("server", "scenario", "prepare", "review", "deploy", "result", "failure")
STATUS = {
    "passed": "Passed",
    "failed": "Failed",
    "pending": "Pending · your exercise",
    "ready": "Ready",
    "incomplete": "Incomplete",
    "unverified": "Not checked yet",
}
THEMES = ("nlf-dark", "nlf-light", "nlf-mono")


def topology(plan, narrow=False):
    """Use the resolved plan for both the preview and deployed lab labels."""
    if plan.get("schema") == 2:
        return ascii_topology(plan, 45 if narrow else 80, details=False)
    a, b = plan["nodes"]
    prefix = plan["transit"].split("/")[1]

    def node(n):
        return f"{n['name']}  [ IOSv ]\nGi0/1  {n['ip']}/{prefix}\nLo0    {n['loopback']}/32"

    if narrow:
        return node(a) + "\n       |\n       | isolated link\n       |\n" + node(b)
    return "\n".join(
        [
            f"       {a['name']:<28}{b['name']}",
            "   +---------+                 +---------+",
            "   |  IOSv   |-----------------|  IOSv   |",
            "   +---------+                 +---------+",
            "      Gi0/1                       Gi0/1",
            f"   {a['ip'] + '/' + prefix:<28}{b['ip']}/{prefix}",
            f"   {'Lo0 ' + a['loopback'] + '/32':<28}Lo0 {b['loopback']}/32",
        ]
    )


class Dialog(ModalScreen[bool]):
    BINDINGS: ClassVar = [("escape", "dismiss(False)", "Back")]

    def __init__(self, title, message, confirm=None):
        super().__init__()
        self.heading, self.message, self.confirm = title, message, confirm

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="dialog"):
            yield Static(self.heading, classes="title", markup=False)
            yield Static(self.message, markup=False)
            yield Button("Back", id="dismiss")
            if self.confirm:
                yield Button(self.confirm, id="confirm", variant="error")

    def on_mount(self):
        self.query_one("#dismiss", Button).focus()

    def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        self.dismiss(event.button.id == "confirm")


class WorkshopApp(App):
    TITLE = "Network Lab Factory"
    ENABLE_COMMAND_PALETTE = False
    CSS_PATH = "tui.tcss"
    BINDINGS: ClassVar = [
        Binding("escape", "back", "Back"),
        Binding("f1", "help", "Help"),
        Binding("ctrl+t", "theme_next", "Theme", priority=True),
        Binding("t", "theme_next", "Theme", show=False),
        Binding("ctrl+c", "request_exit", "Exit", priority=True),
        Binding("ctrl+q", "request_exit", "Exit", show=False, priority=True),
        Binding("ctrl+z", "suspend_process", "Suspend", show=False, priority=True),
    ]

    def __init__(
        self,
        *,
        connector_factory=EveSSH,
        output_root=Path("build/workshops"),
        resume=None,
        theme=None,
        existing=False,
    ):
        super().__init__()
        self.connector_factory = connector_factory
        self.existing_mode = existing
        self.output_root = Path(output_root)
        self.resume_path = Path(resume) if resume else None
        self.connector = None
        self.inventory = None
        self.plan = None
        self.scenario_id = "B01"
        self.result = None
        self.out = None
        self.page = "server"
        self.busy = False
        self.cancel_event = threading.Event()
        self.events = []
        self.operation = ""
        self.started_at = None
        self.last_event_at = None
        self.host = os.environ.get("NLF_EVE_HOST", "")
        self.backend = "eve"
        self.user = os.environ.get("NLF_EVE_USER", "root")
        self.control = os.environ.get("NLF_SSH_CONTROL")
        self.resume_connection = None
        self.initial_theme = theme or ("mono" if "NO_COLOR" in os.environ else "dark")
        self.register_theme(
            Theme(
                name="nlf-dark",
                primary="#dc8dbf",
                accent="#dc8dbf",
                secondary="#aeb0c2",
                background="#121318",
                surface="#1b1c24",
                panel="#20212b",
                foreground="#e7e7ed",
                success="#a5d6ad",
                warning="#dcc386",
                error="#ee9696",
                dark=True,
            )
        )
        self.register_theme(
            Theme(
                name="nlf-light",
                primary="#803661",
                accent="#803661",
                secondary="#55596d",
                background="#faf8fb",
                surface="#f0edf2",
                panel="#e8e3eb",
                foreground="#27232c",
                success="#286338",
                warning="#775712",
                error="#a42c3b",
                dark=False,
            )
        )
        self.register_theme(
            Theme(
                name="nlf-mono",
                primary="#dddddd",
                accent="#dddddd",
                secondary="#bbbbbb",
                background="#141414",
                surface="#202020",
                panel="#292929",
                foreground="#eeeeee",
                success="#dddddd",
                warning="#dddddd",
                error="#dddddd",
                dark=True,
            )
        )
        self.theme = "nlf-" + self.initial_theme

    def compose(self) -> ComposeResult:
        yield Static("NLF  NETWORK LAB FACTORY", id="brand", markup=False)
        yield Static("", id="location", markup=False)
        yield Static(
            "Resize the terminal to at least 50 columns and 16 rows.\nCtrl+C to exit.",
            id="too-small",
            markup=False,
        )
        with Horizontal(id="body"):
            yield Static("", id="rail", markup=False)
            with ContentSwitcher(initial="server", id="pages"):
                with VerticalScroll(id="server", classes="page"):
                    yield Static("Connect your server", classes="title")
                    yield Button("Prepare existing lab", id="existing-open", variant="primary" if self.existing_mode else "default")
                    yield Static(
                        "First, check server access, installed images and available resources.",
                        classes="muted",
                    )
                    yield Static("Platform", classes="label")
                    yield Select(
                        [("EVE-NG", "eve"), ("GNS3 · installed templates", "gns3")],
                        value="eve",
                        allow_blank=False,
                        id="backend",
                    )
                    with Horizontal(classes="columns"):
                        with VerticalGroup(classes="column"):
                            yield Static("CONNECTION", classes="section")
                            yield Static("SSH server", classes="label", id="server-host-label")
                            yield Input(
                                self.host, placeholder="Server IP address or hostname", id="host"
                            )
                            yield Static("User", classes="label")
                            yield Input(self.user, id="user")
                            yield Static("SSH password · blank to use SSH keys", classes="label")
                            yield Input(
                                password=True,
                                id="ssh-password",
                                placeholder="Used for this session only",
                            )
                            with Collapsible(title="SSH options", collapsed=True):
                                yield Static("SSH port", classes="label")
                                yield Input("22", id="ssh-port", type="integer")
                            yield Static(
                                "Supported profile: admin / tenant 0",
                                classes="muted",
                                id="server-profile",
                            )
                            yield Button("Authenticate in terminal", id="authenticate")
                        with VerticalGroup(classes="column"):
                            yield Static("SERVER STATUS", classes="section")
                            yield Static("Not checked yet.", id="inventory", markup=False)
                    yield Static("", id="server-error", classes="error", markup=False)
                    with VerticalGroup(id="gns3-settings"):
                        yield Static("GNS3 API", classes="section")
                        yield Static(
                            "Separate from SSH. Passwords stay in memory and are never saved in lab records.",
                            classes="muted",
                        )
                        yield Static("API username", classes="label")
                        yield Input("admin", id="api-user")
                        yield Static("API password", classes="label")
                        yield Input(
                            password=True, id="api-password", placeholder="GNS3 account password"
                        )
                        with Collapsible(title="API and storage options", collapsed=True):
                            yield Static("API address · from the SSH server", classes="label")
                            yield Input("http://127.0.0.1:3080", id="api-url")
                            yield Static("API version", classes="label")
                            yield Select(
                                [
                                    ("Auto-detect", "auto"),
                                    ("GNS3 2.2 / API v2", "2"),
                                    ("GNS3 3.x / API v3", "3"),
                                ],
                                value="auto",
                                allow_blank=False,
                                id="api-version",
                            )
                            yield Static(
                                "Projects directory · leave blank to discover", classes="label"
                            )
                            yield Input(
                                "",
                                id="projects-path",
                                placeholder="Existing directory on the Linux server",
                            )
                    yield Static(
                        "Use a Linux server or GNS3 VM with a local compute, Python 3, pexpect and telnet. Template OS families must match the scenario.",
                        id="gns3-help",
                        classes="muted",
                    )
                with VerticalScroll(id="scenario", classes="page"):
                    yield Static("Choose what to practice", classes="title")
                    yield Static("Level", classes="label")
                    yield Select(
                        [(x, x) for x in ("Basic", "Intermediate", "Advanced")],
                        value="Basic",
                        allow_blank=False,
                        id="level",
                    )
                    yield Static("Scenario", classes="label")
                    yield Select(
                        [
                            (k + " · " + v["title"], k)
                            for k, v in CATALOG.items()
                            if v["level"] == "Basic"
                        ],
                        value="B01",
                        allow_blank=False,
                        id="scenario-choice",
                    )
                    yield Static("", id="scenario-description", markup=False)
                    yield Static("", id="scenario-requirements", classes="muted", markup=False)
                with VerticalScroll(id="prepare", classes="page"):
                    yield Static("Set up your practice session", classes="title")
                    with Horizontal(classes="columns"):
                        with VerticalGroup(classes="column"):
                            yield Static("LAB", classes="section")
                            yield Static("Name", classes="label")
                            yield Input(
                                "ospf-practice-" + datetime.now().strftime("%m%d-%H%M%S"), id="name"
                            )
                            yield Static("Lab folder", classes="label")
                            yield Input("Network-Lab-Factory", id="folder")
                            yield Static("DEVICES", classes="section")
                            yield Static(
                                "Images are selected for the devices in this scenario.",
                                id="image",
                                markup=False,
                            )
                            with Collapsible(
                                title="Operating systems · choose versions", collapsed=False
                            ):
                                for family in PROFILES:
                                    yield Static(
                                        family.upper(), id="label-image-" + family, classes="label"
                                    )
                                    yield Select(
                                        [],
                                        id="image-" + family,
                                        prompt="Choose an installed image or template",
                                    )
                        with VerticalGroup(classes="column"):
                            yield Static("EXERCISE MODE", classes="section")
                            with RadioSet(id="mode"):
                                yield RadioButton(
                                    "Practice · configure it yourself", value=True, id="practice"
                                )
                                yield RadioButton("Reference · completed exercise", id="reference")
                            yield Static("Arrows: navigate · Space: select", classes="muted")
                            yield Static("", id="mode-note", markup=False)
                    with Collapsible(
                        title="Addressing · edit automatic values",
                        collapsed=True,
                        id="addressing",
                    ):
                        yield Static("Link subnet · /30 or /31", classes="label")
                        yield Input("10.240.0.0/30", id="transit")
                        yield Static("Loopback pool", classes="label")
                        yield Input("10.241.0.0/24", id="loops")
                        yield Static("LAN pool", classes="label")
                        yield Input("10.242.0.0/16", id="lans")
                    yield Static("", id="prepare-error", classes="error", markup=False)
                with VerticalScroll(id="review", classes="page"):
                    yield Static("Review before creating", classes="title")
                    yield Static("TOPOLOGY", classes="section")
                    yield Static("", id="topology", markup=False)
                    with Collapsible(
                        title="Show ports and addresses", collapsed=True, id="port-details"
                    ):
                        yield Static("", id="topology-details", markup=False)
                    yield Static("DESTINATION AND PREPARATION", classes="section")
                    yield Static("", id="review-summary", markup=False)
                    yield Static("CONFIRMATION", classes="section")
                    yield Static(
                        "The devices in this lab will be created and started.\n"
                        "Type DEPLOY, then choose Create lab.",
                        classes="muted",
                    )
                    yield Input(placeholder="Type DEPLOY", id="confirmation")
                with VerticalScroll(id="deploy", classes="page"):
                    yield Static("Building your lab", classes="title")
                    yield Static("", id="deployment-status", classes="section", markup=False)
                    yield Static("", id="elapsed", classes="muted", markup=False)
                    yield Static("", id="stages", markup=False)
                    with Collapsible(title="Show technical log", collapsed=True):
                        yield RichLog(id="events", wrap=True, markup=False, highlight=False)
                with VerticalScroll(id="result", classes="page"):
                    yield Static("", id="result-title", classes="title", markup=False)
                    yield Static("", id="result-summary", markup=False)
                    yield Static("1. PRACTICE ON THE DEVICES", classes="section")
                    with Horizontal(classes="actions"):
                        yield Button("Open r01", id="console-1", variant="primary")
                        yield Button("Open r02", id="console-2")
                    yield Select([], id="console-choice", prompt="Choose another device")
                    yield Button("Open selected console", id="console-selected")
                    yield Static("2. CHECK YOUR WORK", classes="section")
                    with Horizontal(classes="actions"):
                        yield Button("Verify preparation", id="check-base")
                        yield Button("Verify exercise", id="check-exercise")
                    with Horizontal(classes="actions"):
                        yield Button("Inject fault…", id="fault")
                        yield Button("Restore link…", id="restore")
                    yield Static("", id="check-result", markup=False, classes="section")
                    yield Button("Topology and objective", id="goals")
                with VerticalScroll(id="failure", classes="page"):
                    yield Static("The operation is incomplete", classes="title")
                    yield Static("", id="failure-summary", markup=False)
                    yield Button("Show log", id="failure-log")
        with Horizontal(id="navigation"):
            yield Button("< Back", id="back")
            yield Static("", id="nav-space")
            yield Button("Check connection >", id="connect", variant="primary")
            yield Button("Continue >", id="choose", variant="primary", disabled=True)
            yield Button("Set up scenario >", id="b01", variant="primary")
            yield Button("Review lab >", id="preview", variant="primary")
            yield Button("Create lab", id="start", variant="primary", disabled=True)
            yield Button("Interrupt…", id="cancel")
            yield Button("Exit and keep lab", id="finish")
            yield Button("Exit and keep lab", id="failure-exit")
        yield Static("Tab: move focus · Enter: activate · Esc: back", id="hint")
        yield Footer()

    def on_mount(self):
        self.query_one("#gns3-settings").display = False
        self.query_one("#gns3-help").display = False
        self.query_one("#image-vpcs").display = False
        self.query_one("#label-image-vpcs").display = False
        self.set_layout(self.size.width, self.size.height)
        self.refresh_scenario()
        self.update_mode_note()
        self.update_appearance_label()
        self.show_page("server")
        self.set_interval(1, self.update_elapsed)
        if self.resume_path:
            self.load_workshop(self.resume_path)

    def get_line_filters(self):
        filters = super().get_line_filters()
        # NO_COLOR remains the automatic default. An explicit color theme choice
        # should not remain trapped behind Textual's startup monochrome filter.
        if self.theme in ("nlf-dark", "nlf-light"):
            return [f for f in filters if not isinstance(f, (Monochrome, NoColor))]
        return filters

    def on_resize(self, event):
        if self.is_mounted:
            self.set_layout(event.size.width, event.size.height)

    def set_layout(self, width, height):
        self.set_class(width < 110, "compact")
        self.set_class(width < 95, "narrow")
        small = width < 50 or height < 16
        self.query_one("#body").display = not small
        self.query_one("#navigation").display = not small
        self.query_one("#too-small").display = small
        if self.plan:
            self.query_one("#topology", Static).update(topology(self.plan, width < 95))

    def show_page(self, page):
        self.page = page
        self.query_one("#pages", ContentSwitcher).current = page
        index = PAGES.index(page)
        self.query_one("#location", Static).update(
            f"Step {index + 1} of 6 · {STEPS[index]}" if index < 6 else "Status · Incomplete"
        )
        rail = Text("PROGRESS\n\n", style="dim")
        for n, label in enumerate(STEPS):
            rail.append(
                f"{'>' if n == index else '+' if n < index else ' '} {n + 1:02} {label}\n\n",
                style="bold not dim" if n == index else "dim",
            )
        self.query_one("#rail", Static).update(rail)
        self.update_navigation()
        target = {
            "server": "choose" if self.inventory else "backend",
            "scenario": "level",
            "prepare": "name",
            "review": "review",
            "deploy": "deploy",
            "result": "console-1",
            "failure": "failure-log",
        }[page]
        self.query_one("#" + page, VerticalScroll).scroll_home(animate=False)
        self.call_after_refresh(lambda: self.query_one("#" + target).focus(scroll_visible=False))

    def set_busy(self, busy):
        self.busy = busy
        for selector in (
            "#server Input",
            "#server Button",
            "#server Select",
            "#prepare Input",
            "#prepare RadioSet",
            "#prepare Select",
            "#preview",
            "#result Button",
        ):
            for widget in self.query(selector):
                widget.disabled = busy
        self.update_navigation()

    def on_input_changed(self, event: Input.Changed):
        if event.input.id == "confirmation":
            self.query_one("#start", Button).disabled = event.value != "DEPLOY" or self.busy
        elif (
            event.input.id
            in (
                "host",
                "user",
                "ssh-port",
                "ssh-password",
                "api-url",
                "api-user",
                "api-password",
                "projects-path",
            )
            and self.is_mounted
        ):
            self.inventory = None
            self.query_one("#choose", Button).disabled = True
            self.query_one("#inventory", Static).update("Connection not checked yet.")
            self.query_one("#server-error", Static).update("")
            self.update_navigation()

    def update_navigation(self):
        primary = {
            "server": "choose" if self.inventory else "connect",
            "scenario": "b01",
            "prepare": "preview",
            "review": "start",
            "deploy": "cancel",
            "result": "finish",
            "failure": "failure-exit",
        }[self.page]
        for button in self.query("#navigation Button"):
            button.display = button.id in ("back", primary)
            button.disabled = self.busy and button.id != "cancel"
        back = self.query_one("#back", Button)
        back.display = self.page in ("server", "scenario", "prepare", "review")
        back.label = (
            "Exit" if self.page == "server" else "< Edit" if self.page == "review" else "< Back"
        )
        self.query_one("#choose", Button).disabled = self.busy or not self.inventory
        self.query_one("#start", Button).disabled = (
            self.busy or self.query_one("#confirmation", Input).value != "DEPLOY"
        )
        if self.busy:
            labels = {"connect": "Checking…", "preview": "Validating…"}
        else:
            labels = {"connect": "Check connection >", "preview": "Review lab >"}
        for id, label in labels.items():
            self.query_one("#" + id, Button).label = label
        self.query_one("#authenticate", Button).display = self.inventory is None and bool(
            str(self.query_one("#server-error", Static).content)
        )

    def on_input_submitted(self, event: Input.Submitted):
        # Enter in a field moves to the action; it never creates a lab by itself.
        target = {
            "server": "choose" if self.inventory else "connect",
            "prepare": "preview",
            "review": "start",
        }.get(self.page)
        if target and not self.query_one("#" + target, Button).disabled:
            self.query_one("#" + target, Button).focus()

    def on_radio_set_changed(self, event: RadioSet.Changed):
        if event.radio_set.id == "mode":
            self.update_mode_note()

    def selected_mode(self):
        return "reference" if self.query_one("#reference", RadioButton).value else "practice"

    def on_select_changed(self, event: Select.Changed):
        if not self.is_mounted:
            return
        if event.select.id == "api-version":
            self.inventory = None
            self.query_one("#inventory", Static).update("Connection not checked yet.")
            self.update_navigation()
        if (
            event.select.id == "backend"
            and event.value != self.backend
            and isinstance(event.value, str)
        ):
            self.backend = event.value
            self.inventory = None
            self.control = os.environ.get(
                "NLF_GNS3_SSH_CONTROL" if self.backend == "gns3" else "NLF_SSH_CONTROL"
            )
            self.host = os.environ.get(
                "NLF_GNS3_HOST" if self.backend == "gns3" else "NLF_EVE_HOST", ""
            )
            guest = gns3_transport_options() if self.backend == "gns3" else {}
            self.user = (
                ("root" if guest else "gns3")
                if self.backend == "gns3"
                else os.environ.get("NLF_EVE_USER", "root")
            )
            self.query_one("#ssh-password", Input).value = ""
            self.query_one("#api-password", Input).value = ""
            self.connector = None
            self.query_one("#gns3-settings").display = self.backend == "gns3" and not guest
            self.query_one("#gns3-help").display = self.backend == "gns3" and not guest
            self.query_one("#host", Input).value = self.host
            self.query_one("#user", Input).value = self.user
            self.query_one("#server-profile", Static).update(
                f"GNS3 in VM {guest['guest_id']} · access through the temporary Proxmox session."
                if guest
                else "GNS3 2.2 / 3.x · local templates · credentials held only for this session."
                if self.backend == "gns3"
                else "Supported profile: admin / tenant 0"
            )
            self.query_one("#server-host-label", Static).update(
                "Proxmox server" if guest else "SSH server"
            )
            self.query_one("#inventory", Static).update("Not checked yet.")
            self.update_navigation()
        elif event.select.id == "level" and isinstance(event.value, str):
            options = [
                (k + " · " + v["title"], k) for k, v in CATALOG.items() if v["level"] == event.value
            ]
            selector = self.query_one("#scenario-choice", Select)
            selector.set_options(options)
            selector.value = options[0][1]
        elif event.select.id == "scenario-choice" and isinstance(event.value, str):
            self.scenario_id = event.value
            self.refresh_scenario()

    def refresh_scenario(self):
        s = CATALOG[self.scenario_id]
        self.query_one("#scenario-description", Static).update(
            s["purpose"]
            + "\n\nPREPARATION\n"
            + s["prepare"]
            + "\n\nYOUR EXERCISE\n"
            + s["exercise"]
        )
        self.query_one("#scenario-requirements", Static).update(
            s["devices"]
            + "\n"
            + s["dependency"]
            + "\nDeployment checks images, ports and resources."
        )
        self.query_one("#transit", Input).value = (
            "10.240.0.0/30"
            if self.scenario_id == "B01" and self.backend == "eve"
            else "10.240.0.0/16"
        )
        self.query_one("#name", Input).value = (
            self.scenario_id.lower() + "-practice-" + datetime.now().strftime("%m%d-%H%M%S")
        )
        self.refresh_profiles()
        self.update_mode_note()

    def refresh_profiles(self):
        sample = make_catalog_plan(self.scenario_id, "preview", backend=self.backend)
        families = {n["profile"] for n in sample["nodes"]}
        images = (self.inventory or {}).get("images", [])
        if (self.inventory or {}).get("portable"):
            templates = self.inventory["templates"]
            for family in PROFILES:
                sel = self.query_one("#image-" + family, Select)
                self.query_one("#label-image-" + family).display = sel.display = family in families
                kind = "vpcs" if family == "vpcs" else "qemu"
                options = [
                    (t["name"], t["template_id"]) for t in templates if t["template_type"] == kind
                ]
                sel.set_options(options)
                # Only a unique matching name is a convenience suggestion; user reviews every binding.
                suggested = [
                    t
                    for t in templates
                    if t["template_type"] == kind
                    and (family in t["name"].lower() or family == "vpcs")
                ]
                if len(suggested) == 1:
                    sel.value = suggested[0]["template_id"]
            self.query_one("#image", Static).update(
                "Select a matching OS-family template for each device type. Existing template disks, BIOS and QEMU settings are preserved; resources are checked before review."
            )
            return
        self.query_one("#image-vpcs").display = False
        self.query_one("#label-image-vpcs").display = False
        for family, p in PROFILES.items():
            if family == "vpcs":
                continue
            sel = self.query_one("#image-" + family, Select)
            self.query_one("#label-image-" + family).display = sel.display = (
                family in families and not (self.scenario_id == "B01" and self.backend == "eve")
            )
            options = sorted(
                {
                    v["image"]
                    for v in PROFILES.values()
                    if v["template"] == p["template"] and v["image"] in images
                }
            )
            sel.set_options([(i, i) for i in options])
            if options:
                sel.value = p["image"] if p["image"] in options else options[0]
        self.query_one("#image", Static).update(
            "2 × IOSv · validated profile"
            if self.scenario_id == "B01" and self.backend == "eve"
            else f"{len(sample['nodes'])} devices · {sample['ram_mib']} MiB RAM + headroom\n"
            + ", ".join(sorted(families))
        )

    def update_mode_note(self):
        mode = self.selected_mode()
        s = CATALOG[self.scenario_id]
        note = "The tool prepares: " + s["prepare"] + "\n\n"
        note += (
            "Your task: " + s["exercise"]
            if mode == "practice"
            else "The tool also configures the solution and verifies the exercise."
        )
        if self.scenario_id == "A07":
            note = "A verified reference is created first. Then choose Inject fault; repairing it is the exercise."
        self.query_one("#mode-note", Static).update(note)

    def run_lab_action(self, action):
        save_json(
            self.out / "latest-result.json", update_observation(self.plan, self.result, action)
        )
        self.render_result()
        self.operation = action
        self.cancel_event.clear()
        self.set_busy(True)
        self.remote(action)

    def make_connector(self):
        host = self.query_one("#host", Input).value.strip()
        user = self.query_one("#user", Input).value.strip()
        if self.resume_connection:
            saved = dict(self.resume_connection)
            password = self.query_one("#ssh-password", Input).value or None
            options = {"password": password} if saved.get("auth_method") == "password" else {}
            if saved.get("transport") == "portable-ssh":
                options["api_password"] = self.query_one("#api-password", Input).value or None
            return connector_from_record(saved, batch=True, cancel=self.cancel_event, **options)
        # A control socket is bound to the previously authenticated host and user.
        if (host, user) != (self.host, self.user):
            self.control = None
        self.host, self.user = host, user
        self.cancel_event.clear()
        if self.connector_factory is not EveSSH:
            return self.connector_factory(
                host, user, self.control, batch=True, cancel=self.cancel_event
            )
        try:
            port = int(self.query_one("#ssh-port", Input).value)
        except ValueError:
            raise ValueError("Enter an SSH port between 1 and 65535") from None
        password = self.query_one("#ssh-password", Input).value or None
        connection = {"backend": self.backend, "host": host, "user": user, "control": self.control}
        if self.backend == "gns3":
            guest = gns3_transport_options()
            if guest:
                if password or port != 22:
                    raise ValueError(
                        "Legacy Proxmox access uses the existing OpenSSH session. Use direct server access for password fields."
                    )
                connection.update(guest)
                connection["auth_file"] = os.environ.get(
                    "NLF_GNS3_AUTH_FILE", "/etc/gns3/nexo-admin.json"
                )
                return connector_from_record(connection, batch=True, cancel=self.cancel_event)
            connection.update(
                transport="portable-ssh",
                api_url=self.query_one("#api-url", Input).value.strip(),
                api_version=self.query_one("#api-version", Select).value,
                api_user=self.query_one("#api-user", Input).value.strip(),
                projects_path=self.query_one("#projects-path", Input).value.strip(),
            )
            return connector_from_record(
                connection,
                batch=True,
                cancel=self.cancel_event,
                port=port,
                password=password,
                api_password=self.query_one("#api-password", Input).value or None,
            )
        return connector_from_record(
            connection, batch=True, cancel=self.cancel_event, port=port, password=password
        )

    def on_button_pressed(self, event: Button.Pressed):
        action = event.button.id
        if action == "cancel":
            self.request_cancel()
            return
        if self.busy:
            return
        if action == "existing-open" or (action == "connect" and self.existing_mode):
            try:
                from .existing_ui import ExistingLabScreen

                connector = self.make_connector()
                self.push_screen(ExistingLabScreen(connector))
            except ValueError as exc:
                self.query_one("#server-error", Static).update(str(exc))
            return
        if action == "connect":
            try:
                self.connector = self.make_connector()
            except ValueError as exc:
                self.query_one("#server-error", Static).update(str(exc))
                self.update_navigation()
                return
            self.set_busy(True)
            self.operation = "inventory"
            self.query_one("#server-error", Static).update("")
            self.query_one("#inventory", Static).update("Querying the server…")
            self.remote("inventory")
        elif action == "authenticate":
            self.authenticate()
        elif action == "choose" and self.inventory:
            self.show_page("scenario")
        elif action == "b01":
            self.refresh_profiles()
            self.show_page("prepare")
        elif action == "preview":
            self.prepare()
        elif action == "back":
            self.action_back()
        elif action == "start" and self.page == "review":
            if self.query_one("#confirmation", Input).value != "DEPLOY":
                return
            self.out = self.output_root / (self.plan["name"] + "-" + self.plan["uuid"][:8])
            self.events = []
            self.query_one("#events", RichLog).clear()
            self.cancel_event.clear()
            self.operation = "deploy"
            self.started_at = time.monotonic()
            self.last_event_at = None
            self.set_busy(True)
            self.query_one("#start", Button).disabled = True
            self.show_page("deploy")
            self.update_stages()
            self.remote("deploy")
        elif action in ("check-base", "check-exercise"):
            self.cancel_event.clear()
            self.operation = "verify"
            self.set_busy(True)
            self.query_one("#check-result", Static).update("Collecting current observations…")
            self.remote("verify", exercise=action == "check-exercise")
        elif action in ("console-1", "console-2"):
            self.open_console(self.plan["nodes"][int(action[-1]) - 1]["name"])
        elif action == "console-selected":
            node = self.query_one("#console-choice", Select).value
            if isinstance(node, str):
                self.open_console(node)
        elif action in ("fault", "restore"):
            self.push_screen(
                Dialog(
                    "Confirm lab change",
                    "Only the link defined in this recipe will be modified. The action is recorded.",
                    "Inject fault" if action == "fault" else "Restore",
                ),
                lambda accepted: self.run_lab_action(action) if accepted else None,
            )
        elif action == "goals":
            self.push_screen(
                Dialog(
                    "Topology and objective",
                    topology(self.plan, True)
                    + "\n\n"
                    + english(self.plan.get("exercise", CATALOG["B01"]["exercise"])),
                )
            )
        elif action == "failure-log":
            self.push_screen(
                Dialog(
                    "Operation log",
                    "\n".join(self.event_text(e) for e in self.events)
                    or "No events were received from the server.",
                )
            )
        elif action in ("finish", "failure-exit"):
            self.exit(
                return_code=0
                if self.page == "result" and self.result.get("status") == "ready"
                else 1
            )

    def prepare(self):
        try:
            if not self.inventory:
                raise ValueError("Check the server first.")

            def value(id):
                return self.query_one("#" + id, Input).value.strip()

            if self.scenario_id == "B01" and self.backend == "eve":
                if PROFILE not in self.inventory.get("images", []):
                    raise ValueError("The B01 IOSv image is missing.")
                self.plan = make_plan(
                    value("name"),
                    PROFILE,
                    value("transit"),
                    value("loops"),
                    self.selected_mode(),
                    value("folder"),
                )
            else:
                sample = make_catalog_plan(self.scenario_id, "preview", backend=self.backend)
                families = {n["profile"] for n in sample["nodes"]}
                images = {}
                if self.inventory.get("portable"):
                    self.connector.template_map = {}
                    self.connector.template_fingerprints = {}
                    for family in families:
                        chosen = self.query_one("#image-" + family, Select).value
                        if not isinstance(chosen, str):
                            raise ValueError("Choose an installed template for " + family)  # noqa: TRY004 — missing UI selection
                        self.connector.template_map[family] = chosen
                for family in set() if self.inventory.get("portable") else families - {"vpcs"}:
                    chosen = self.query_one("#image-" + family, Select).value
                    if not isinstance(chosen, str):
                        raise ValueError("No compatible image for " + family)  # noqa: TRY004 — missing selection, not a programmer type error.
                    images[family] = chosen
                self.plan = make_catalog_plan(
                    self.scenario_id,
                    value("name"),
                    images=images,
                    transit=value("transit"),
                    loopbacks=value("loops"),
                    lans=value("lans"),
                    mode=self.selected_mode(),
                    folder=value("folder"),
                    backend=self.backend,
                )
        except ValueError as exc:
            self.query_one("#prepare-error", Static).update("Check your input: " + str(exc))
            self.call_after_refresh(self.query_one("#prepare-error").scroll_visible)
            return
        self.query_one("#prepare-error", Static).update("Validating destination and resources…")
        self.cancel_event.clear()
        self.operation = "preflight"
        self.set_busy(True)
        self.remote("preflight")

    @work(thread=True, exit_on_error=False)
    def remote(self, action, exercise=False):
        try:
            if action == "deploy":
                result = deploy_plan(
                    self.connector,
                    self.plan,
                    self.out,
                    quiet=True,
                    callback=lambda e: self.call_from_thread(self.progress, e),
                )
            elif action in ("fault", "restore"):
                result = self.connector.run(action, plan=self.plan, ports=self.result["ports"])
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                save_json(self.out / f"action-{stamp}.json", result)
            elif action == "verify":
                result = self.connector.run(
                    "verify", plan=self.plan, ports=self.result["ports"], exercise=exercise
                )
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                save_json(self.out / f"check-{stamp}.json", result)
            else:
                result = self.connector.run(
                    action, **({"plan": self.plan} if action == "preflight" else {})
                )
        except Exception as exc:  # noqa: BLE001 - worker boundary renders errors without quitting
            self.call_from_thread(self.operation_failed, action, str(exc))
        else:
            self.call_from_thread(self.operation_done, action, result)

    def operation_done(self, action, result):
        self.set_busy(False)
        if action == "inventory":
            if self.resume_connection:
                self.resume_connection = None
                if self.result.get("status") == "incomplete":
                    self.operation_failed("deploy", self.result.get("reason", "No final result"))
                else:
                    self.render_result()
                    self.show_page("result")
                return
            valid = any(
                p["image"] in result.get("images", []) for p in PROFILES.values() if p["image"]
            )
            if result.get("portable"):
                valid = any(t["template_type"] == "qemu" for t in result.get("templates", []))
            enough = result.get("memory_mib", 0) >= 1536 and result.get("free_gib", 0) >= 2
            self.inventory = result if valid and enough else None
            self.query_one("#inventory", Static).update(
                ("READY TO CONTINUE\n\n" if valid and enough else "NEEDS ATTENTION\n\n")
                + f"{'GNS3' if self.backend == 'gns3' else 'EVE-NG'} {result.get('version', '')}\n"
                f"{('[+]' if valid else '[!]')} {'Local QEMU templates' if result.get('portable') else 'Profile-compatible images'}: "
                f"{'available' if valid else 'not installed'}\n"
                f"Available RAM: {result.get('memory_mib', '?')} MiB\n"
                f"Free disk space: {result.get('free_gib', '?')} GiB\n"
                + ("[+] Sufficient resources" if enough else "[!] Insufficient resources")
            )
            self.refresh_scenario()
            self.query_one("#choose", Button).disabled = not self.inventory
            self.update_navigation()
            if self.inventory:
                self.query_one("#choose", Button).focus()
            else:
                self.query_one("#server-error", Static).update(
                    "At least one supported image and sufficient free resources are required.\n"
                    "Images found: " + (", ".join(result.get("images", [])) or "none")
                )
        elif action == "preflight":
            self.query_one("#prepare-error", Static).update("")
            self.query_one("#confirmation", Input).value = ""
            self.query_one("#start", Button).disabled = True
            self.query_one("#topology", Static).update(topology(self.plan, self.size.width < 95))
            p = self.plan
            self.query_one("#port-details").display = p.get("schema") == 2
            self.query_one("#topology-details", Static).update(
                ascii_topology(p) if p.get("schema") == 2 else ""
            )
            self.query_one("#review-summary", Static).update(
                self.server_destination() + "\n"
                f"Destination: {p['folder']}/{p['name']}{'' if self.backend == 'gns3' else '.unl'}\n"
                f"Devices: {len(p['nodes'])} · {result.get('required_ram_mib', p['ram_mib'])} MiB RAM + headroom\n"
                f"Mode: {'Practice' if p['mode'] == 'practice' else 'Reference'}\nExercise: "
                + english(p.get("exercise", CATALOG["B01"]["exercise"]))
            )
            self.show_page("review")
        elif action == "deploy":
            self.result = result
            self.render_result()
            self.show_page("result")
        elif action in ("fault", "restore"):
            update_observation(self.plan, self.result, action, result)
            save_json(self.out / "latest-result.json", self.result)
            self.render_result()
            self.query_one("#check-result", Static).update(
                "Change applied and recorded. Verify the exercise to observe the result."
            )
        elif action == "verify":
            scope = "Exercise" if result.get("scope") == "exercise" else "Preparation"
            key = "exercise" if result.get("scope") == "exercise" else "preparation"
            self.result[key] = result
            self.result["status"] = (
                "ready"
                if (
                    self.result.get("preparation", {}).get("status") == "passed"
                    and (
                        self.plan["mode"] == "practice"
                        or self.result.get("exercise", {}).get("status") == "passed"
                    )
                )
                else "failed"
            )
            self.render_result()
            try:
                save_json(self.out / "latest-result.json", self.result)
            except OSError as exc:
                self.notify(f"Could not update the local summary: {exc}", severity="error")
            self.query_one("#check-result", Static).update(
                f"{scope}: {STATUS.get(result['status'], result['status'])}\n"
                f"Observed: {datetime.now():%H:%M:%S} · report saved with the recipe."
            )

    def operation_failed(self, action, message):
        self.set_busy(False)
        if action == "deploy":
            record = str(self.out.resolve()) if self.out and self.out.exists() else "not created"
            created = next(
                (e.get("path") for e in self.events if e.get("event") == "created"),
                "Not confirmed by the server",
            )
            self.query_one("#failure-summary", Static).update(
                f"{message}\n\nLab: {created}\nLocal record: {record}\n\n"
                "Any resources already created are preserved. Nothing is retried or deleted automatically.\n"
                "If SSH was interrupted, the remote state may have changed: check it on the server."
            )
            self.show_page("failure")
        else:
            target = {
                "inventory": "server-error",
                "preflight": "prepare-error",
                "verify": "check-result",
                "fault": "check-result",
                "restore": "check-result",
            }[action]
            self.query_one("#" + target, Static).update(message)
            self.call_after_refresh(self.query_one("#" + target).scroll_visible)
            if action == "inventory":
                self.inventory = None
                self.query_one("#choose", Button).disabled = True
                self.query_one("#inventory", Static).update("[!] Could not complete the query.")
            self.update_navigation()

    @staticmethod
    def event_text(event):
        labels = {
            "created": "Lab created",
            "started": "Device started",
            "waiting": "Waiting for console",
            "configured": "Base configured",
            "verified": "Preparation verified",
            "result": "Result",
            "error": "Error",
        }
        detail = event.get("message") or event.get("node") or event.get("path") or ""
        status = event.get("status", "")
        return (
            f"{labels.get(event.get('event'), event.get('event', 'Event'))}: {detail} "
            f"{STATUS.get(status, status)}"
        ).strip()

    def progress(self, event):
        self.events.append(event)
        self.last_event_at = time.monotonic()
        self.query_one("#events", RichLog).write(Text(self.event_text(event)))
        self.update_stages()

    def update_stages(self):
        created = any(e.get("event") == "created" for e in self.events)
        lines = [("[+]" if created else "[…] ") + " Create topology and labels"]
        for name in [n["name"] for n in self.plan["nodes"]] if self.plan else []:
            kinds = {e.get("event") for e in self.events if e.get("node") == name}
            status = (
                "Configured"
                if "configured" in kinds
                else "Waiting for console"
                if "waiting" in kinds
                else "Started"
                if "started" in kinds
                else "Pending"
            )
            lines.append(f"{name} · {status}")
        verified = next((e for e in reversed(self.events) if e.get("event") == "verified"), None)
        lines.append(
            "Preparation · "
            + (
                STATUS.get(verified["status"], verified["status"])
                if verified
                else "Not checked yet"
            )
        )
        self.query_one("#stages", Static).update("\n".join(lines))
        latest = self.events[-1] if self.events else {}
        kind = latest.get("event")
        message = {
            "created": "Starting devices…",
            "started": "Preparing consoles…",
            "waiting": f"Waiting for {latest.get('node', 'the device')} to finish booting…",
            "configured": "Configuring and checking the lab…",
            "verified": "Finishing checks…",
        }.get(kind, "Validating the destination and creating the topology…")
        self.query_one("#deployment-status", Static).update(message)
        self.update_elapsed()

    def update_elapsed(self):
        if self.page != "deploy" or self.started_at is None:
            return
        now = time.monotonic()
        elapsed = int(now - self.started_at)
        last = (
            f"Last event received {int(now - self.last_event_at)} s ago."
            if self.last_event_at is not None
            else "Waiting for the first server event."
        )
        self.query_one("#elapsed", Static).update(
            f"Elapsed: {elapsed // 60:02}:{elapsed % 60:02} · {last}\n"
            "Some images take several minutes to boot; progress reflects actual events."
        )

    def server_destination(self):
        if hasattr(self.connector, "guest_id"):
            return f"GNS3 · VM {self.connector.guest_id} · Proxmox access: {self.connector.host}"
        return f"{'GNS3' if self.backend == 'gns3' else 'EVE-NG'}: {self.connector.host}"

    def render_result(self):
        r = self.result
        self.query_one("#result-title", Static).update(
            "Your lab is ready"
            if r.get("status") == "ready"
            else "Lab created · some checks are pending or failed"
        )
        prep = r.get("preparation", {}).get("status", "incomplete")
        exercise = r.get("exercise", {}).get("status", "pending")
        self.query_one("#result-summary", Static).update(
            self.server_destination() + f"\nPath: {r.get('path', 'Not confirmed')}\n"
            f"Preparation: {STATUS.get(prep, prep)}\nExercise: {STATUS.get(exercise, exercise)}\n\n"
            f"Recipe and evidence: {self.out.resolve()}\n"
            "Results from the last check; this is not continuous monitoring."
        )
        names = [n["name"] for n in self.plan["nodes"]]
        for i in (1, 2):
            button = self.query_one(f"#console-{i}", Button)
            button.label = "Open " + names[i - 1]
            button.disabled = names[i - 1] not in r.get("ports", {})
        self.query_one("#console-choice", Select).set_options([(n, n) for n in names])
        self.query_one("#console-choice").display = len(names) > 2
        self.query_one("#console-selected").display = len(names) > 2
        for id in ("check-base", "check-exercise"):
            self.query_one("#" + id, Button).disabled = not all(
                n in r.get("ports", {}) for n in names
            )
        for action in ("fault", "restore"):
            self.query_one("#" + action).display = bool(self.plan.get("actions"))

    def load_workshop(self, path):
        try:
            self.plan = validate_plan(json.loads((path / "plan.json").read_text()))
            result_path = path / "latest-result.json"
            self.result = json.loads(
                (result_path if result_path.exists() else path / "result.json").read_text()
            )
            connection = json.loads((path / "connection.json").read_text())
            self.backend = connection.get("backend", "eve")
            connection["control"] = os.environ.get(
                "NLF_GNS3_SSH_CONTROL" if self.backend == "gns3" else "NLF_SSH_CONTROL",
                connection.get("control"),
            )
            factory = (
                connector_from_record
                if self.connector_factory is EveSSH
                else lambda record, **kw: self.connector_factory(**record, **kw)
            )
            self.connector = factory(connection, batch=True, cancel=self.cancel_event)
            self.out = path
            if (
                connection.get("auth_method") == "password"
                or connection.get("transport") == "portable-ssh"
            ):
                self.resume_connection = connection
                self.query_one("#backend", Select).value = self.backend
                self.query_one("#host", Input).value = connection["host"]
                self.query_one("#user", Input).value = connection["user"]
                self.query_one("#ssh-port", Input).value = str(connection.get("port", 22))
                for field in ("host", "user", "ssh-port"):
                    self.query_one("#" + field, Input).disabled = True
                self.query_one("#backend", Select).disabled = True
                portable = connection.get("transport") == "portable-ssh"
                self.query_one("#gns3-settings").display = portable
                self.query_one("#gns3-help").display = portable
                if portable:
                    for field, key in (
                        ("api-url", "api_url"),
                        ("api-user", "api_user"),
                        ("projects-path", "projects_path"),
                    ):
                        self.query_one("#" + field, Input).value = connection.get(key, "")
                        self.query_one("#" + field, Input).disabled = True
                    self.query_one("#api-version", Select).value = connection.get(
                        "api_version", "auto"
                    )
                    self.query_one("#api-version", Select).disabled = True
                self.show_page("server")
                self.query_one("#server-error", Static).update(
                    "Saved lab loaded. Re-enter your session passwords and choose Check connection; no new lab will be created."
                )
                return
            if self.result.get("status") == "incomplete":
                self.events = (
                    json.loads((path / "events.json").read_text())
                    if (path / "events.json").exists()
                    else []
                )
                self.operation_failed("deploy", self.result.get("reason", "No final result"))
            else:
                self.render_result()
                self.show_page("result")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.push_screen(Dialog("Could not open the recipe", str(exc)))

    def authenticate(self):
        try:
            connector = self.make_connector()
            if getattr(connector, "password", None):
                self.query_one("#server-error", Static).update(
                    "Password entered. Select Check connection to authenticate inside the assistant."
                )
                return
            if not self.control:
                self.control = str(Path(tempfile.mkdtemp(prefix="nlf-ssh-")) / "session")
                connector.control = self.control
            args = connector.ssh_args()
            args[1:1] = ["-o", "ControlMaster=auto", "-o", "ControlPersist=3600"]
            with self.suspend():
                print("SSH authentication. SSH handles passwords; NLF does not store them.")
                result = subprocess.run(args + ["true"], check=False)
            if result.returncode:
                raise RuntimeError("SSH authentication failed. Check the server and its host key.")
            self.connector = connector
            self.query_one("#server-error", Static).update(
                "Authenticated. Select Check connection to read the inventory."
            )
        except (OSError, ValueError, RuntimeError, SuspendNotSupported) as exc:
            self.query_one("#server-error", Static).update(str(exc))

    def open_console(self, node):
        try:
            if hasattr(self.connector, "open_console"):
                with self.suspend():
                    self.connector.open_console(self.plan, node)
                return
            port = int(self.result["ports"][node])
            if not 1 <= port <= 65535:
                raise ValueError("Invalid console port")
            if getattr(self.connector, "password", None):
                with self.suspend():
                    self.connector.open_console_at(port)
                self.query_one("#check-result", Static).update(
                    "Console closed. Verify again to refresh the results."
                )
                return
            args = self.connector.ssh_args()
            with self.suspend():
                print(f"Console {node}. To return: Ctrl+], then quit.")
                completed = subprocess.run(
                    args[:-1] + ["-tt", args[-1], "telnet -K -c 127.0.0.1 " + str(port)],
                    check=False,
                )
            self.query_one("#check-result", Static).update(
                ("Console closed." if completed.returncode == 0 else "Console connection failed.")
                + " Verify again to refresh the results."
            )
        except (OSError, ValueError, KeyError, RuntimeError, SuspendNotSupported) as exc:
            self.query_one("#check-result", Static).update(str(exc))

    def action_theme_next(self):
        self.theme = THEMES[(THEMES.index(self.theme) + 1) % len(THEMES)]
        self.update_appearance_label()
        self.notify(
            {"nlf-dark": "Dark", "nlf-light": "Light", "nlf-mono": "Monochrome"}[self.theme],
            title="Theme",
        )

    def update_appearance_label(self):
        label = {"nlf-dark": "Dark", "nlf-light": "Light", "nlf-mono": "Mono"}[self.theme]
        self.query_one("#brand", Static).update(f"NLF  NETWORK LAB FACTORY     [{label}]")

    def action_help(self):
        self.push_screen(
            Dialog(
                "Shortcuts and scope",
                "Tab / Shift+Tab: move focus\n"
                "Enter: activate · Arrows: select a menu item\nEsc: back · Ctrl+T: change theme\n"
                "Ctrl+C: exit or request interruption\nCtrl+Z: suspend on Unix systems\n\n"
                "Choose one of 24 scenarios. Review it and type DEPLOY before creating.\n"
                "Practice leaves the exercise for you; reference configures and verifies it.\n"
                "The recipe keeps events and results. Exiting does not delete the lab.",
            )
        )

    def action_back(self):
        if self.busy:
            self.notify("An operation is running. Press Ctrl+C to interrupt it.")
            return
        previous = {"scenario": "server", "prepare": "scenario", "review": "prepare"}
        if self.page in previous:
            self.show_page(previous[self.page])
        elif self.page == "server":
            self.action_request_exit()

    def request_cancel(self):
        self.push_screen(
            Dialog(
                "Interrupt the operation",
                "The local SSH operation will be closed. "
                "Any resources already created are preserved.\nThe server may still be working: "
                "check the server before attempting to create the lab again.",
                "Interrupt",
            ),
            self.cancel_confirmed,
        )

    def cancel_confirmed(self, accepted):
        if accepted and self.busy:
            self.cancel_event.set()
            self.notify("Interrupting and saving the record…")

    def action_request_exit(self):
        if getattr(self.screen, "busy", False) and self.screen is not self.screen_stack[0]:
            self.notify("Existing-lab operation in progress. Wait for the result before leaving.")
            return
        if self.busy:
            if len(self.screen_stack) == 1:
                self.request_cancel()
        else:
            failed = self.page == "failure" or (
                self.page == "result" and self.result.get("status") != "ready"
            )
            self.exit(return_code=1 if failed else 0)


def run_tui(*, resume=None, theme=None, existing=False):
    app = WorkshopApp(resume=resume, theme=theme, existing=existing)
    app.run()
    if app.out:
        print(f"Recipe and evidence: {app.out.resolve()}")
        print("The lab is preserved on the server.")
    return app.return_code
