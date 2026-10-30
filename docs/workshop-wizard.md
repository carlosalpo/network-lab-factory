# Asistente de laboratorios por terminal

El asistente prepara una maqueta para que puedas comenzar el ejercicio: crea los equipos,
conecta interfaces, asigna nombres y direcciones, aplica la configuración base y comprueba
el resultado. La topología ASCII y las etiquetas del laboratorio salen de la misma receta.

El [catálogo](catalog/README.md) contiene 24 variantes concretas, organizadas en básico,
intermedio y avanzado. La [matriz de validación](catalog-validation.md) separa lo implementado
de lo comprobado en equipos reales. No todas las imágenes de un fabricante son intercambiables.

## Recorrido

1. **Servidor.** Elegí EVE-NG o GNS3 y comprobá la conexión. Se consultan las imágenes
   compatibles instaladas y los recursos libres. Cambiar de plataforma invalida esa consulta.
2. **Escenario.** Elegí nivel y objetivo. La pantalla distingue qué prepara la herramienta
   de lo que te corresponde practicar.
3. **Preparación.** Definí nombre, carpeta, imágenes y modo. Podés ajustar los pools en
   Direccionamiento. Solo aparecen versiones instaladas con un perfil explícito.
4. **Revisión.** Revisá plataforma, servidor o VM, destino, topología, puertos, direcciones,
   recursos y objetivo. Editar vuelve al formulario. Escribí `DEPLOY` y activá Crear laboratorio.
5. **Despliegue.** Se comprueba nuevamente el destino y se crea una maqueta nueva. La pantalla
   informa los eventos de creación, arranque, configuración y comprobación, con tiempo transcurrido.
6. **Laboratorio.** Obtenés la ruta y los resultados observados. Podés abrir consolas, consultar
   la topología y volver a comprobar la preparación o el ejercicio.

La barra inferior mantiene Volver/Editar a la izquierda y la siguiente acción a la derecha.
El registro técnico está separado del resumen. No se muestra un porcentaje de avance inventado.

## Inicio y navegación

Requiere Python 3.11+ y las dependencias del proyecto instaladas:

```sh
nlf wizard
nlf wizard --theme light
nlf wizard --theme mono
nlf wizard --plain
```

Desde este checkout también podés usar:

```sh
PYTHONPATH=src .venv/bin/python -m netlab.cli wizard --theme dark
```

- Tab / Shift+Tab: mover el foco. Flechas: elegir opciones. Enter: activar.
- Enter dentro de un campo mueve el foco a la acción principal; no crea el laboratorio.
- Escape: volver antes del despliegue. F1: ayuda. Ctrl+T: cambiar tema.
- Ctrl+C: salir cuando está inactivo u ofrecer interrupción durante una operación.
- La vista se desplaza en terminales de 80×24; la barra de navegación permanece visible.
  Por debajo de 50×16 pide ampliar la ventana.
- `NO_COLOR` selecciona monocromo por defecto. Un tema elegido explícitamente puede activar color.
- `--plain` ofrece preguntas lineales y también admite los 24 casos.

## Conectores disponibles

### EVE-NG

Perfil EVE-NG Professional 7.2.0-4, usuario admin / tenant 0, acceso al host por SSH.
El host necesita Python 3, pexpect, telnet, sus plantillas y las imágenes declaradas.
El destino es `/opt/unetlab/labs/<carpeta>/<nombre>.unl`.

Variables opcionales: `NLF_EVE_HOST`, `NLF_EVE_USER` y `NLF_SSH_CONTROL`.
La autenticación interactiva se realiza en OpenSSH, fuera del formulario; no se guarda
la contraseña. Se mantiene la comprobación de identidad del servidor SSH.

### GNS3

Perfil explícito **GNS3 3.0.6 en el host Nexo**. Usa la API local del servidor y los perfiles
QEMU de esa instalación; no es un adaptador universal para cualquier instalación de GNS3.
Consulta las imágenes locales y crea nodos, conexiones y dibujos nativos en un proyecto nuevo.
El destino es `/srv/gns3/projects/<carpeta>/<nombre>`.

Admite dos accesos:

- SSH directo al servidor GNS3.
- Una sesión temporal de Proxmox autorizada, que ejecuta las operaciones dentro de la VM
  GNS3 mediante el agente del invitado. La pantalla identifica la VM y el host de acceso.

Variables: `NLF_GNS3_HOST`, `NLF_GNS3_SSH_CONTROL`, `NLF_GNS3_AUTH_FILE` y, para el segundo
acceso, `NLF_GNS3_GUEST_ID`. La ruta de configuración privada se interpreta en el servidor
GNS3; el archivo y su contraseña no se copian al equipo del usuario. La sesión administrativa
puede expirar y debe renovarse mediante el procedimiento autorizado; NLF no agrega claves,
usuarios ni permisos. La disponibilidad de ASA depende de que su imagen esté instalada.

Los perfiles, discos, BIOS y recursos declarados están en `gns3_profiles.py`. Se comprueba
la versión del servidor antes de crear; una versión diferente requiere adaptar y validar el perfil.

## Práctica y referencia

| Modo | Preparación | Ejercicio |
|---|---|---|
| Práctica | Configura y comprueba los requisitos de la ficha | Queda pendiente para que lo configures |
| Referencia | Configura y comprueba los requisitos | Aplica también la solución y exige que sus pruebas pasen |

Por ejemplo, B01 en práctica deja interfaces habilitadas, direccionamiento y loopbacks;
vos configurás OSPF. B04 prepara puertos y hosts, pero reserva LACP para el ejercicio.
A07 comienza con una referencia funcional y permite introducir después una falla confirmada.

**Listo** en práctica significa que pasó la preparación. En referencia requiere preparación
y ejercicio aprobados. Los resultados son una observación, no una vigilancia continua.

## Pools, versiones y aislamiento

Predeterminados del catálogo: tránsito `10.240.0.0/16` en /30, loopbacks `10.241.0.0/16`
en /32 y LAN `10.242.0.0/16` en /24. El asistente propone /24 para loopbacks, suficiente
para estas variantes. B01 original en EVE conserva su subred de enlace /30 o /31.
Los pools IPv4 deben ser privados, estar alineados y no superponerse.

VLAN, ASN, áreas, VRF y VNI están definidos por cada receta y se documentan en sus comandos.
IPv6 usa un prefijo de laboratorio ULA. La cantidad y distribución de equipos son las de
cada variante; no se ofrece todavía una cantidad arbitraria ni edición de todos los identificadores.
A08 exige dos versiones distintas. Las imágenes se seleccionan de lo instalado; no se descargan.

Cada maqueta tiene enlaces internos propios. No conecta automáticamente la red del laboratorio
a una red física o de producción. Las maquetas aisladas pueden reutilizar los mismos pools.
Las etiquetas de interfaces y direcciones usan 10 px y se colocan junto a sus conexiones;
el título y el objetivo tienen su propia ubicación.

## Consolas y acciones

El resultado permite elegir cualquiera de los equipos de la receta. Con SSH directo,
Ctrl+] seguido de `quit` cierra el cliente telnet y vuelve al asistente. En el acceso GNS3
mediante Proxmox, Ctrl+] vuelve directamente; el puente de consola tiene un límite de
20 minutos y no abre un puerto público nuevo.

Las acciones de falla y restauración solo aparecen cuando la receta define ambas. Requieren
confirmación. Tras una acción, el estado anterior queda sin comprobar hasta ejecutar las pruebas.
La parada se ofrece por comando explícito; no se eliminan automáticamente los proyectos.

```sh
nlf workshop build/workshops/<nombre>-<id>
nlf lab-action build/workshops/<nombre>-<id> check-base
nlf lab-action build/workshops/<nombre>-<id> check-exercise
```

Las mutaciones de `lab-action` requieren `--confirm` con el nombre exacto del laboratorio.
Consultá `nlf lab-action --help` para las acciones admitidas por la receta.

## Evidencia y fallos parciales

Cada despliegue conserva un directorio nuevo con receta, topología, comandos, eventos,
resultado inicial y metadatos de conexión sin credenciales. EVE exporta `.unl`; GNS3 exporta
`gns3-request.json`. Las comprobaciones incluyen salidas reales de interfaces, vecinos y pings.
Conservá el directorio completo para reabrir el menú.

Si falla o se interrumpe una etapa, los recursos creados y sus registros permanecen disponibles.
No se repite la creación, no se sobrescribe un destino y no se presume que todo quedó detenido.
Comprobá el estado antes de recuperar una operación. El asistente no reanuda automáticamente
una configuración parcial. La identidad del laboratorio se verifica antes de posteriores acciones.

Estas pruebas no miden rendimiento ni tiempo de convergencia. La evidencia histórica del primer
B01 permanece en [workshop-validation.md](workshop-validation.md); la del catálogo se registra
por separado en [catalog-validation.md](catalog-validation.md).

### Acceso inicial de los equipos virtuales

En las maquetas aisladas, NX-OS usa el usuario `admin` y ASA utiliza una clave de
modo privilegiado. La clave inicial del laboratorio es `Nlf-Workshop!2026`; es un
valor de práctica conocido, distinto de las credenciales de EVE-NG o GNS3. No se
debe reutilizar fuera de estas maquetas aisladas.
