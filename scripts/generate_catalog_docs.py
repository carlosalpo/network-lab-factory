"""Document the actual executable variants, allocations and acceptance commands."""

from pathlib import Path

from netlab.catalog import CATALOG
from netlab.catalog_render import ascii_topology
from netlab.gns3_profiles import GNS3_PROFILES
from netlab.recipes import make_catalog_plan

root = Path("docs/catalog")
root.mkdir(exist_ok=True)
rows = []
for sid, scenario in CATALOG.items():
    p = make_catalog_plan(sid, "example-" + sid.lower(), mode="reference")
    gp = make_catalog_plan(sid, "example-" + sid.lower(), mode="reference", backend="gns3")
    rows.append(
        f"| [{sid}]({sid}.md) | {scenario['level']} | {scenario['title']} | {len(p['nodes'])} | {p['ram_mib']} / {gp['ram_mib']} |"
    )
    lines = [
        f"# {sid} · {p['title']}",
        "",
        scenario["purpose"],
        "",
        "## Variante implementada",
        "",
        f"Topología fija: {len(p['nodes'])} equipos y {len(p['networks'])} enlaces. Recursos EVE: {p['cpu']} vCPU y {p['ram_mib']} MiB; GNS3: {gp['cpu']} vCPU y {gp['ram_mib']} MiB; se exige 1024 MiB de margen adicional y disco libre antes de crear.",
        "",
        "```text",
        ascii_topology(p, 80, details=False),
        "```",
        "",
        "## Preparación y ejercicio",
        "",
        "**Preparación automática:** " + p["prepare"],
        "",
        "**Ejercicio:** " + p["exercise"],
        "",
        "Práctica aplica la base y comprueba su estado; referencia aplica también la solución y exige que las comprobaciones del ejercicio pasen."
        if sid != "A07"
        else "Este caso siempre empieza en referencia. La falla se introduce únicamente después de la creación, mediante una acción confirmada.",
        "",
        "## Equipos y versiones",
        "",
        "| Equipo | Perfil | Imagen | RAM MiB |",
        "|---|---|---|---|",
    ]
    for n in p["nodes"]:
        lines.append(
            f"| {n['name']} | {n['profile']} | {n['device']['image'] or 'VPCS instalado'} | {n['device']['ram']} |"
        )
    lines += [
        "",
        "### Perfil GNS3 3.0.6",
        "",
        "| Equipo | Disco instalado | RAM MiB | vCPU |",
        "|---|---|---|---|",
    ]
    for n in gp["nodes"]:
        profile = GNS3_PROFILES[n["gns3_profile"]]
        lines.append(
            f"| {n['name']} | {profile.get('image') or 'VPCS instalado'} | {n['device']['ram']} | {n['device']['cpu']} |"
        )
    lines += [
        "",
        "Se ofrecen únicamente imágenes instaladas con perfil explícito. La compatibilidad declarada no sustituye la validación real de la versión: consultar [estado de validación](../catalog-validation.md).",
        "",
        "## Direccionamiento y conexiones",
        "",
        "Pools predeterminados: tránsito `10.240.0.0/16` dividido en /30; loopbacks `10.241.0.0/16` asignadas como /32; LAN `10.242.0.0/16` dividida en /24. El asistente propone un pool de loopbacks /24, suficiente para estas variantes. Son editables, privados y no se superponen.",
        "",
        "```text",
        ascii_topology(p).split("CONEXIONES\n", 1)[1],
        "```",
        "",
        "VLAN, áreas, ASN, identificadores VRF y VNI son valores definidos por la receta; se incluyen en la configuración exportada. IPv6 utiliza el prefijo de laboratorio `fd42:4e4c:4600::/48`. No se reservan direcciones fuera de esta maqueta aislada.",
        "",
        "## Comprobaciones observadas",
        "",
    ]
    for scope, label in [("preparation", "Preparación"), ("exercise", "Ejercicio")]:
        lines += ["### " + label, "", "| Equipo | Comando | Criterio |", "|---|---|---|"]
        for c in p["checks"][scope]:
            criterion = (
                c["pattern"]
                if c["kind"] == "regex"
                else "Tres respuestas / 100 % de éxito"
                if c["kind"] == "ping"
                else "Fallo explícito sin respuestas"
            )
            lines.append(
                f"| {c['node']} | `{c['command'].replace('|', '&#124;')}` | {criterion.replace('|', '&#124;')} |"
            )
        lines += [""]
    if p["actions"]:
        lines += ["## Cambios reversibles", ""]
        for action in p["actions"]:
            for a in [action] + (
                [dict(action["peer"], label=action["label"] + " · extremo remoto")]
                if "peer" in action
                else []
            ):
                lines += [
                    f"**{a['label']} · {a['node']}**",
                    "",
                    "```text",
                    "\n".join(a["commands"]),
                    "```",
                    "",
                    "Restauración:",
                    "",
                    "```text",
                    "\n".join(a["inverse"]),
                    "```",
                    "",
                ]
    lines += [
        "## Límites",
        "",
        "La cantidad de equipos y la estructura son las de esta variante. No incluye todas las variantes pedagógicas posibles del escenario. Las pruebas son funcionales; no miden rendimiento ni tiempo de convergencia.",
        "",
        "EVE: laboratorio nuevo en la carpeta elegida, tenant admin 0, sin enlaces externos. No se sobrescriben laboratorios. Una falla conserva el registro y los recursos creados para inspección; no se reintenta automáticamente.",
        "",
        "GNS3: proyecto nuevo mediante el perfil 3.0.6 Nexo; acceso SSH directo o sesión temporal de Proxmox. No agrega enlaces externos ni instala imágenes. Si falta una imagen o su BIOS, la creación se detiene antes de crear recursos.",
        "",
        "La preparación completa, la solución y las pruebas se exportan con `nlf plan "
        + sid
        + " --name ejemplo-"
        + sid.lower()
        + " --mode reference --output build/ejemplo-"
        + sid.lower()
        + "`.",
        "",
    ]
    if sid == "B03":
        lines += [
            "Los hosts de VLAN 100 y 101 usan el mismo prefijo IP en dominios separados. Es intencional: el ping negativo detecta una mezcla accidental de VLAN y no solo la ausencia de una ruta. No hay gateway.",
            "",
        ]
    if sid == "A02":
        lines += [
            "Los hosts H01/H02 usan IOSv con `no ip routing`, como endpoints. La captura QA detectó respuestas ARP incompatibles entre VPCS y el plano virtual NX-OS; esta variante conserva resolución dinámica y pruebas bidireccionales, sin ARP estático ni sondas omitidas.",
            "",
        ]
    if any(n["device"]["console"] == "nxos" for n in p["nodes"]):
        lines += [
            "La preparación NX-OS reconoce el cargador inicial, selecciona únicamente la imagen instalada que coincide con el perfil y guarda `boot nxos` para el siguiente encendido.",
            "",
        ]
    (root / (sid + ".md")).write_text("\n".join(lines))
(root / "README.md").write_text(
    "# Catálogo ejecutable · 24 escenarios\n\nCada ficha describe la variante que genera el código actual: base, ejercicio, topología, imágenes, recursos, asignaciones y criterios observables. Consultá el [estado de validación real](../catalog-validation.md) antes de elegir una receta.\n\n| Caso | Nivel | Objetivo | Equipos | RAM MiB EVE / GNS3 |\n|---|---|---|---|---|\n"
    + "\n".join(rows)
    + "\n\nEl alcance es una variante concreta por caso. El catálogo de planificación conserva variantes futuras; estas fichas distinguen lo que realmente genera la implementación.\n"
)
