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

STEPS = ("Servidor", "Escenario", "Preparación", "Revisión", "Despliegue", "Laboratorio")
PAGES = ("server", "scenario", "prepare", "review", "deploy", "result", "failure")
STATUS = {
    "passed": "Correcto",
    "failed": "Falló",
    "pending": "Pendiente para practicar",
    "ready": "Listo",
    "incomplete": "Incompleto",
    "unverified": "Pendiente de comprobar",
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
        return node(a) + "\n       |\n       | enlace aislado\n       |\n" + node(b)
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
    BINDINGS: ClassVar = [("escape", "dismiss(False)", "Volver")]

    def __init__(self, title, message, confirm=None):
        super().__init__()
        self.heading, self.message, self.confirm = title, message, confirm

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="dialog"):
            yield Static(self.heading, classes="title", markup=False)
            yield Static(self.message, markup=False)
            yield Button("Volver", id="dismiss")
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
        Binding("escape", "back", "Volver"),
        Binding("f1", "help", "Ayuda"),
        Binding("ctrl+t", "theme_next", "Tema", priority=True),
        Binding("t", "theme_next", "Tema", show=False),
        Binding("ctrl+c", "request_exit", "Salir", priority=True),
        Binding("ctrl+q", "request_exit", "Salir", show=False, priority=True),
        Binding("ctrl+z", "suspend_process", "Suspender", show=False, priority=True),
    ]

    def __init__(
        self,
        *,
        connector_factory=EveSSH,
        output_root=Path("build/workshops"),
        resume=None,
        theme=None,
    ):
        super().__init__()
        self.connector_factory = connector_factory
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
            "Ampliá la terminal a 50 columnas y 16 filas.\nCtrl+C para salir.",
            id="too-small",
            markup=False,
        )
        with Horizontal(id="body"):
            yield Static("", id="rail", markup=False)
            with ContentSwitcher(initial="server", id="pages"):
                with VerticalScroll(id="server", classes="page"):
                    yield Static("Conectá tu servidor", classes="title")
                    yield Static(
                        "Primero comprobamos imágenes, acceso y recursos del servidor.",
                        classes="muted",
                    )
                    yield Static("Plataforma", classes="label")
                    yield Select(
                        [("EVE-NG", "eve"), ("GNS3 · perfil Nexo 3.0.6", "gns3")],
                        value="eve",
                        allow_blank=False,
                        id="backend",
                    )
                    with Horizontal(classes="columns"):
                        with VerticalGroup(classes="column"):
                            yield Static("CONEXIÓN", classes="section")
                            yield Static("Servidor SSH", classes="label", id="server-host-label")
                            yield Input(
                                self.host, placeholder="IP o nombre del servidor", id="host"
                            )
                            yield Static("Usuario", classes="label")
                            yield Input(self.user, id="user")
                            yield Static(
                                "Perfil compatible: admin / tenant 0",
                                classes="muted",
                                id="server-profile",
                            )
                            yield Button("Autenticar en terminal", id="authenticate")
                        with VerticalGroup(classes="column"):
                            yield Static("ESTADO DEL SERVIDOR", classes="section")
                            yield Static("Pendiente de comprobar.", id="inventory", markup=False)
                    yield Static("", id="server-error", classes="error", markup=False)
                with VerticalScroll(id="scenario", classes="page"):
                    yield Static("Elegí qué querés practicar", classes="title")
                    yield Static("Nivel", classes="label")
                    yield Select(
                        [(x, x) for x in ("Básico", "Intermedio", "Avanzado")],
                        value="Básico",
                        allow_blank=False,
                        id="level",
                    )
                    yield Static("Escenario", classes="label")
                    yield Select(
                        [
                            (k + " · " + v["title"], k)
                            for k, v in CATALOG.items()
                            if v["level"] == "Básico"
                        ],
                        value="B01",
                        allow_blank=False,
                        id="scenario-choice",
                    )
                    yield Static("", id="scenario-description", markup=False)
                    yield Static("", id="scenario-requirements", classes="muted", markup=False)
                with VerticalScroll(id="prepare", classes="page"):
                    yield Static("Definí cómo querés practicar", classes="title")
                    with Horizontal(classes="columns"):
                        with VerticalGroup(classes="column"):
                            yield Static("LABORATORIO", classes="section")
                            yield Static("Nombre", classes="label")
                            yield Input(
                                "ospf-practice-" + datetime.now().strftime("%m%d-%H%M%S"), id="name"
                            )
                            yield Static("Carpeta del laboratorio", classes="label")
                            yield Input("Network-Lab-Factory", id="folder")
                            yield Static("EQUIPOS", classes="section")
                            yield Static(
                                "Las imágenes se eligen según los equipos del escenario.",
                                id="image",
                                markup=False,
                            )
                            with Collapsible(
                                title="Sistemas operativos · elegir versiones", collapsed=False
                            ):
                                for family in PROFILES:
                                    if family == "vpcs":
                                        continue
                                    yield Static(
                                        family.upper(), id="label-image-" + family, classes="label"
                                    )
                                    yield Select(
                                        [], id="image-" + family, prompt="Sin imagen compatible"
                                    )
                        with VerticalGroup(classes="column"):
                            yield Static("MODO DEL EJERCICIO", classes="section")
                            with RadioSet(id="mode"):
                                yield RadioButton(
                                    "Práctica · configuro el ejercicio", value=True, id="practice"
                                )
                                yield RadioButton("Referencia · ejercicio resuelto", id="reference")
                            yield Static("Flechas: elegir · Espacio: seleccionar", classes="muted")
                            yield Static("", id="mode-note", markup=False)
                    with Collapsible(
                        title="Direccionamiento · editar valores automáticos",
                        collapsed=True,
                        id="addressing",
                    ):
                        yield Static("Subred del enlace · /30 o /31", classes="label")
                        yield Input("10.240.0.0/30", id="transit")
                        yield Static("Pool de loopbacks", classes="label")
                        yield Input("10.241.0.0/24", id="loops")
                        yield Static("Pool de LAN", classes="label")
                        yield Input("10.242.0.0/16", id="lans")
                    yield Static("", id="prepare-error", classes="error", markup=False)
                with VerticalScroll(id="review", classes="page"):
                    yield Static("Revisá antes de crear", classes="title")
                    yield Static("TOPOLOGÍA", classes="section")
                    yield Static("", id="topology", markup=False)
                    with Collapsible(
                        title="Ver puertos y direcciones", collapsed=True, id="port-details"
                    ):
                        yield Static("", id="topology-details", markup=False)
                    yield Static("DESTINO Y PREPARACIÓN", classes="section")
                    yield Static("", id="review-summary", markup=False)
                    yield Static("CONFIRMACIÓN", classes="section")
                    yield Static(
                        "Se crearán y encenderán los equipos de esta maqueta.\n"
                        "Escribí DEPLOY y luego elegí Crear laboratorio.",
                        classes="muted",
                    )
                    yield Input(placeholder="Escribí DEPLOY", id="confirmation")
                with VerticalScroll(id="deploy", classes="page"):
                    yield Static("Construyendo tu laboratorio", classes="title")
                    yield Static("", id="deployment-status", classes="section", markup=False)
                    yield Static("", id="elapsed", classes="muted", markup=False)
                    yield Static("", id="stages", markup=False)
                    with Collapsible(title="Ver registro técnico", collapsed=True):
                        yield RichLog(id="events", wrap=True, markup=False, highlight=False)
                with VerticalScroll(id="result", classes="page"):
                    yield Static("", id="result-title", classes="title", markup=False)
                    yield Static("", id="result-summary", markup=False)
                    yield Static("1. PRACTICÁ EN LOS EQUIPOS", classes="section")
                    with Horizontal(classes="actions"):
                        yield Button("Abrir r01", id="console-1", variant="primary")
                        yield Button("Abrir r02", id="console-2")
                    yield Select([], id="console-choice", prompt="Elegí otro equipo")
                    yield Button("Abrir consola seleccionada", id="console-selected")
                    yield Static("2. COMPROBÁ TU TRABAJO", classes="section")
                    with Horizontal(classes="actions"):
                        yield Button("Verificar preparación", id="check-base")
                        yield Button("Verificar ejercicio", id="check-exercise")
                    with Horizontal(classes="actions"):
                        yield Button("Introducir falla…", id="fault")
                        yield Button("Restaurar enlace…", id="restore")
                    yield Static("", id="check-result", markup=False, classes="section")
                    yield Button("Topología y objetivo", id="goals")
                with VerticalScroll(id="failure", classes="page"):
                    yield Static("La operación quedó incompleta", classes="title")
                    yield Static("", id="failure-summary", markup=False)
                    yield Button("Ver registro", id="failure-log")
        with Horizontal(id="navigation"):
            yield Button("< Volver", id="back")
            yield Static("", id="nav-space")
            yield Button("Comprobar conexión >", id="connect", variant="primary")
            yield Button("Continuar >", id="choose", variant="primary", disabled=True)
            yield Button("Preparar escenario >", id="b01", variant="primary")
            yield Button("Revisar maqueta >", id="preview", variant="primary")
            yield Button("Crear laboratorio", id="start", variant="primary", disabled=True)
            yield Button("Interrumpir…", id="cancel")
            yield Button("Salir y conservar", id="finish")
            yield Button("Salir y conservar", id="failure-exit")
        yield Static("Tab: mover foco · Enter: activar · Esc: volver", id="hint")
        yield Footer()

    def on_mount(self):
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
            f"Paso {index + 1} de 6 · {STEPS[index]}" if index < 6 else "Estado · Incompleto"
        )
        rail = Text("PROGRESO\n\n", style="dim")
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
        elif event.input.id in ("host", "user") and self.is_mounted:
            self.inventory = None
            self.query_one("#choose", Button).disabled = True
            self.query_one("#inventory", Static).update("Conexión pendiente de comprobar.")
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
            "Salir"
            if self.page == "server"
            else "< Editar"
            if self.page == "review"
            else "< Volver"
        )
        self.query_one("#choose", Button).disabled = self.busy or not self.inventory
        self.query_one("#start", Button).disabled = (
            self.busy or self.query_one("#confirmation", Input).value != "DEPLOY"
        )
        if self.busy:
            labels = {"connect": "Comprobando…", "preview": "Validando…"}
        else:
            labels = {"connect": "Comprobar conexión >", "preview": "Revisar maqueta >"}
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
                ("root" if guest else "gns3admin")
                if self.backend == "gns3"
                else os.environ.get("NLF_EVE_USER", "root")
            )
            self.query_one("#host", Input).value = self.host
            self.query_one("#user", Input).value = self.user
            self.query_one("#server-profile", Static).update(
                f"GNS3 en VM {guest['guest_id']} · acceso mediante la sesión temporal de Proxmox."
                if guest
                else "API local de GNS3 mediante SSH; configuración privada en el servidor."
                if self.backend == "gns3"
                else "Perfil compatible: admin / tenant 0"
            )
            self.query_one("#server-host-label", Static).update(
                "Servidor Proxmox" if guest else "Servidor SSH"
            )
            self.query_one("#inventory", Static).update("Pendiente de comprobar.")
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
            s["purpose"] + "\n\nPREPARACIÓN\n" + s["prepare"] + "\n\nTU EJERCICIO\n" + s["exercise"]
        )
        self.query_one("#scenario-requirements", Static).update(
            s["devices"]
            + "\n"
            + s["dependency"]
            + "\nEl despliegue comprobará imágenes, puertos y recursos."
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
            "2 × IOSv · perfil validado"
            if self.scenario_id == "B01" and self.backend == "eve"
            else f"{len(sample['nodes'])} equipos · {sample['ram_mib']} MiB de RAM + margen\n"
            + ", ".join(sorted(families))
        )

    def update_mode_note(self):
        mode = self.selected_mode()
        s = CATALOG[self.scenario_id]
        note = "La herramienta prepara: " + s["prepare"] + "\n\n"
        note += (
            "Tu tarea: " + s["exercise"]
            if mode == "practice"
            else "La herramienta también configura la solución y comprueba el ejercicio."
        )
        if self.scenario_id == "A07":
            note = "Se crea una referencia comprobada. Después elegís Introducir falla; la reparación es el ejercicio."
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
        # A control socket is bound to the previously authenticated host and user.
        if (host, user) != (self.host, self.user):
            self.control = None
        self.host, self.user = host, user
        self.cancel_event.clear()
        if self.connector_factory is not EveSSH:
            return self.connector_factory(
                host, user, self.control, batch=True, cancel=self.cancel_event
            )
        connection = {"backend": self.backend, "host": host, "user": user, "control": self.control}
        if self.backend == "gns3":
            connection.update(gns3_transport_options())
            connection["auth_file"] = os.environ.get(
                "NLF_GNS3_AUTH_FILE", "/etc/gns3/nexo-admin.json"
            )
        return connector_from_record(connection, batch=True, cancel=self.cancel_event)

    def on_button_pressed(self, event: Button.Pressed):
        action = event.button.id
        if action == "cancel":
            self.request_cancel()
            return
        if self.busy:
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
            self.query_one("#inventory", Static).update("Consultando el servidor…")
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
            self.query_one("#check-result", Static).update("Recogiendo observaciones actuales…")
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
                    "Confirmar cambio en la maqueta",
                    "Se modificará únicamente el enlace definido en esta receta. La acción queda registrada.",
                    "Introducir falla" if action == "fault" else "Restaurar",
                ),
                lambda accepted: self.run_lab_action(action) if accepted else None,
            )
        elif action == "goals":
            self.push_screen(
                Dialog(
                    "Topología y objetivo",
                    topology(self.plan, True)
                    + "\n\n"
                    + self.plan.get("exercise", CATALOG["B01"]["exercise"]),
                )
            )
        elif action == "failure-log":
            self.push_screen(
                Dialog(
                    "Registro de la operación",
                    "\n".join(self.event_text(e) for e in self.events)
                    or "No se recibieron eventos del servidor.",
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
                raise ValueError("Primero comprobá el servidor.")

            def value(id):
                return self.query_one("#" + id, Input).value.strip()

            if self.scenario_id == "B01" and self.backend == "eve":
                if PROFILE not in self.inventory.get("images", []):
                    raise ValueError("Falta la imagen IOSv de B01.")
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
                for family in families - {"vpcs"}:
                    chosen = self.query_one("#image-" + family, Select).value
                    if not isinstance(chosen, str):
                        raise ValueError("Falta una imagen compatible para " + family)  # noqa: TRY004 — missing selection, not a programmer type error.
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
            self.query_one("#prepare-error", Static).update("Revisá los datos: " + str(exc))
            self.call_after_refresh(self.query_one("#prepare-error").scroll_visible)
            return
        self.query_one("#prepare-error", Static).update("Validando destino y recursos…")
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
            valid = any(
                p["image"] in result.get("images", []) for p in PROFILES.values() if p["image"]
            )
            enough = result.get("memory_mib", 0) >= 1536 and result.get("free_gib", 0) >= 2
            self.inventory = result if valid and enough else None
            self.query_one("#inventory", Static).update(
                ("LISTO PARA CONTINUAR\n\n" if valid and enough else "REQUIERE ATENCIÓN\n\n")
                + f"{'GNS3' if self.backend == 'gns3' else 'EVE-NG'} {result.get('version', '')}\n"
                f"{('[+]' if valid else '[!]')} Imágenes con perfil: "
                f"{'disponible' if valid else 'no instalada'}\n"
                f"RAM disponible: {result.get('memory_mib', '?')} MiB\n"
                f"Disco libre: {result.get('free_gib', '?')} GiB\n"
                + ("[+] Recursos suficientes" if enough else "[!] Recursos insuficientes")
            )
            self.refresh_scenario()
            self.query_one("#choose", Button).disabled = not self.inventory
            self.update_navigation()
            if self.inventory:
                self.query_one("#choose", Button).focus()
            else:
                self.query_one("#server-error", Static).update(
                    "Se necesita al menos una imagen con perfil y recursos libres.\n"
                    "Imágenes encontradas: " + (", ".join(result.get("images", [])) or "ninguna")
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
                f"Destino: {p['folder']}/{p['name']}{'' if self.backend == 'gns3' else '.unl'}\n"
                f"Equipos: {len(p['nodes'])} · {p['cpu']} vCPU · {p['ram_mib']} MiB RAM + margen\n"
                f"Modo: {'Práctica' if p['mode'] == 'practice' else 'Referencia'}\nEjercicio: "
                + p.get("exercise", CATALOG["B01"]["exercise"])
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
                "Cambio aplicado y registrado. Verificá el ejercicio para observar el resultado."
            )
        elif action == "verify":
            scope = "Ejercicio" if result.get("scope") == "exercise" else "Preparación"
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
                self.notify(f"No se pudo actualizar el resumen local: {exc}", severity="error")
            self.query_one("#check-result", Static).update(
                f"{scope}: {STATUS.get(result['status'], result['status'])}\n"
                f"Observación: {datetime.now():%H:%M:%S} · informe guardado en la receta."
            )

    def operation_failed(self, action, message):
        self.set_busy(False)
        if action == "deploy":
            record = str(self.out.resolve()) if self.out and self.out.exists() else "sin crear"
            created = next(
                (e.get("path") for e in self.events if e.get("event") == "created"),
                "No confirmado por el servidor",
            )
            self.query_one("#failure-summary", Static).update(
                f"{message}\n\nLaboratorio: {created}\nRegistro local: {record}\n\n"
                "Se conserva lo que haya quedado creado. No se repite ni se borra automáticamente.\n"
                "Si se interrumpió SSH, el estado remoto puede haber avanzado: revisalo en el servidor."
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
                self.query_one("#inventory", Static).update("[!] No se pudo completar la consulta.")
            self.update_navigation()

    @staticmethod
    def event_text(event):
        labels = {
            "created": "Laboratorio creado",
            "started": "Equipo iniciado",
            "waiting": "Esperando consola",
            "configured": "Base configurada",
            "verified": "Preparación comprobada",
            "result": "Resultado",
            "error": "Error",
        }
        detail = event.get("message") or event.get("node") or event.get("path") or ""
        status = event.get("status", "")
        return (
            f"{labels.get(event.get('event'), event.get('event', 'Evento'))}: {detail} "
            f"{STATUS.get(status, status)}"
        ).strip()

    def progress(self, event):
        self.events.append(event)
        self.last_event_at = time.monotonic()
        self.query_one("#events", RichLog).write(Text(self.event_text(event)))
        self.update_stages()

    def update_stages(self):
        created = any(e.get("event") == "created" for e in self.events)
        lines = [("[+]" if created else "[…] ") + " Crear topología y etiquetas"]
        for name in [n["name"] for n in self.plan["nodes"]] if self.plan else []:
            kinds = {e.get("event") for e in self.events if e.get("node") == name}
            status = (
                "Configurado"
                if "configured" in kinds
                else "Esperando consola"
                if "waiting" in kinds
                else "Iniciado"
                if "started" in kinds
                else "Pendiente"
            )
            lines.append(f"{name} · {status}")
        verified = next((e for e in reversed(self.events) if e.get("event") == "verified"), None)
        lines.append(
            "Preparación · "
            + (
                STATUS.get(verified["status"], verified["status"])
                if verified
                else "Pendiente de comprobar"
            )
        )
        self.query_one("#stages", Static).update("\n".join(lines))
        latest = self.events[-1] if self.events else {}
        kind = latest.get("event")
        message = {
            "created": "Iniciando los equipos…",
            "started": "Preparando las consolas…",
            "waiting": f"Esperando que {latest.get('node', 'el equipo')} termine de iniciar…",
            "configured": "Configurando y comprobando la maqueta…",
            "verified": "Finalizando las comprobaciones…",
        }.get(kind, "Validando el destino y creando la topología…")
        self.query_one("#deployment-status", Static).update(message)
        self.update_elapsed()

    def update_elapsed(self):
        if self.page != "deploy" or self.started_at is None:
            return
        now = time.monotonic()
        elapsed = int(now - self.started_at)
        last = (
            f"Último evento recibido hace {int(now - self.last_event_at)} s."
            if self.last_event_at is not None
            else "Esperando el primer evento del servidor."
        )
        self.query_one("#elapsed", Static).update(
            f"Transcurrido: {elapsed // 60:02}:{elapsed % 60:02} · {last}\n"
            "Algunas imágenes tardan varios minutos en iniciar; mostramos los eventos reales."
        )

    def server_destination(self):
        if hasattr(self.connector, "guest_id"):
            return f"GNS3 · VM {self.connector.guest_id} · acceso Proxmox: {self.connector.host}"
        return f"{'GNS3' if self.backend == 'gns3' else 'EVE-NG'}: {self.connector.host}"

    def render_result(self):
        r = self.result
        self.query_one("#result-title", Static).update(
            "Tu laboratorio está listo"
            if r.get("status") == "ready"
            else "Laboratorio creado · hay comprobaciones pendientes o fallidas"
        )
        prep = r.get("preparation", {}).get("status", "incomplete")
        exercise = r.get("exercise", {}).get("status", "pending")
        self.query_one("#result-summary", Static).update(
            self.server_destination() + f"\nRuta: {r.get('path', 'No confirmada')}\n"
            f"Preparación: {STATUS.get(prep, prep)}\nEjercicio: {STATUS.get(exercise, exercise)}\n\n"
            f"Receta y evidencias: {self.out.resolve()}\n"
            "Resultados de la última comprobación; no es monitorización continua."
        )
        names = [n["name"] for n in self.plan["nodes"]]
        for i in (1, 2):
            button = self.query_one(f"#console-{i}", Button)
            button.label = "Abrir " + names[i - 1]
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
            if self.result.get("status") == "incomplete":
                self.events = (
                    json.loads((path / "events.json").read_text())
                    if (path / "events.json").exists()
                    else []
                )
                self.operation_failed("deploy", self.result.get("reason", "Sin resultado final"))
            else:
                self.render_result()
                self.show_page("result")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.push_screen(Dialog("No se pudo abrir la receta", str(exc)))

    def authenticate(self):
        try:
            connector = self.make_connector()
            if not self.control:
                self.control = str(Path(tempfile.mkdtemp(prefix="nlf-ssh-")) / "session")
                connector.control = self.control
            args = connector.ssh_args()
            args[1:1] = ["-o", "ControlMaster=auto", "-o", "ControlPersist=3600"]
            with self.suspend():
                print("Autenticación SSH. Las contraseñas las gestiona SSH y no se guardan en NLF.")
                result = subprocess.run(args + ["true"], check=False)
            if result.returncode:
                raise RuntimeError("SSH no autenticó. Revisá el servidor y su clave de host.")
            self.connector = connector
            self.query_one("#server-error", Static).update(
                "Sesión autenticada. Pulsá Comprobar conexión para leer el inventario."
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
                raise ValueError("Puerto de consola inválido")
            args = self.connector.ssh_args()
            with self.suspend():
                print(f"Consola {node}. Para volver: Ctrl+] y luego quit.")
                completed = subprocess.run(
                    args[:-1] + ["-tt", args[-1], "telnet -K -c 127.0.0.1 " + str(port)],
                    check=False,
                )
            self.query_one("#check-result", Static).update(
                (
                    "Consola cerrada."
                    if completed.returncode == 0
                    else "La conexión de consola falló."
                )
                + " Verificá nuevamente para actualizar los resultados."
            )
        except (OSError, ValueError, KeyError, RuntimeError, SuspendNotSupported) as exc:
            self.query_one("#check-result", Static).update(str(exc))

    def action_theme_next(self):
        self.theme = THEMES[(THEMES.index(self.theme) + 1) % len(THEMES)]
        self.update_appearance_label()
        self.notify(
            {"nlf-dark": "Oscuro", "nlf-light": "Claro", "nlf-mono": "Monocromático"}[self.theme],
            title="Tema",
        )

    def update_appearance_label(self):
        label = {"nlf-dark": "Oscuro", "nlf-light": "Claro", "nlf-mono": "Mono"}[self.theme]
        self.query_one("#brand", Static).update(f"NLF  NETWORK LAB FACTORY     [{label}]")

    def action_help(self):
        self.push_screen(
            Dialog(
                "Atajos y alcance",
                "Tab / Shift+Tab: mover el foco\n"
                "Enter: activar · Flechas: elegir en un menú\nEsc: volver · Ctrl+T: cambiar tema\n"
                "Ctrl+C: salir o solicitar interrupción\nCtrl+Z: suspender en sistemas Unix\n\n"
                "Elegí uno de los 24 escenarios. Revisás y escribís DEPLOY antes de crear.\n"
                "Práctica deja el ejercicio pendiente; referencia lo configura y comprueba.\n"
                "La receta conserva eventos y resultados. Salir no elimina el laboratorio.",
            )
        )

    def action_back(self):
        if self.busy:
            self.notify("Hay una operación en curso. Ctrl+C permite interrumpirla.")
            return
        previous = {"scenario": "server", "prepare": "scenario", "review": "prepare"}
        if self.page in previous:
            self.show_page(previous[self.page])
        elif self.page == "server":
            self.action_request_exit()

    def request_cancel(self):
        self.push_screen(
            Dialog(
                "Interrumpir la operación",
                "Se cerrará la operación SSH local. "
                "Lo que ya se haya creado se conserva.\nEl servidor puede seguir trabajando: "
                "revisá el servidor antes de repetir una creación.",
                "Interrumpir",
            ),
            self.cancel_confirmed,
        )

    def cancel_confirmed(self, accepted):
        if accepted and self.busy:
            self.cancel_event.set()
            self.notify("Interrumpiendo y guardando el registro…")

    def action_request_exit(self):
        if self.busy:
            if len(self.screen_stack) == 1:
                self.request_cancel()
        else:
            failed = self.page == "failure" or (
                self.page == "result" and self.result.get("status") != "ready"
            )
            self.exit(return_code=1 if failed else 0)


def run_tui(*, resume=None, theme=None):
    app = WorkshopApp(resume=resume, theme=theme)
    app.run()
    if app.out:
        print(f"Receta y evidencias: {app.out.resolve()}")
        print("El laboratorio se conserva en el servidor.")
    return app.return_code
