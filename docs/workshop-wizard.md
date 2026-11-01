# Asistente de laboratorios por terminal

Desde la versión 0.2.1, la interfaz y las preguntas de `--plain` se muestran en inglés. Esta guía conserva sus explicaciones en español y usa los nombres actuales de los controles.

El asistente prepara una maqueta para que puedas comenzar el ejercicio: crea los equipos,
conecta interfaces, asigna nombres y direcciones, aplica la configuración base y comprueba
el resultado. La topología ASCII y las etiquetas del laboratorio salen de la misma receta.

El [catálogo](catalog/README.md) contiene 24 variantes concretas, organizadas en básico,
intermedio y avanzado. La [matriz de validación](catalog-validation.md) separa lo implementado
de lo comprobado en equipos reales. No todas las imágenes de un fabricante son intercambiables.

## Recorrido

1. **Server.** Elegí EVE-NG o GNS3 y comprobá la conexión. Se consultan las imágenes
   compatibles instaladas y los recursos libres. Cambiar de plataforma invalida esa consulta.
2. **Scenario.** Elegí nivel y objetivo. La pantalla distingue qué prepara la herramienta
   de lo que te corresponde practicar.
3. **Preparation.** Definí nombre, carpeta, imágenes y modo. Podés ajustar los pools en
   Addressing. Solo aparecen versiones instaladas con un perfil explícito.
4. **Review.** Revisá plataforma, servidor o VM, destino, topología, puertos, direcciones,
   recursos y objetivo. Edit vuelve al formulario. Escribí `DEPLOY` y activá Create lab.
5. **Deployment.** Se comprueba nuevamente el destino y se crea una maqueta nueva. La pantalla
   informa los eventos de creación, arranque, configuración y comprobación, con tiempo transcurrido.
6. **Lab.** Obtenés la ruta y los resultados observados. Podés abrir consolas, consultar
   la topología y volver a comprobar la preparación o el ejercicio.

La barra inferior mantiene Back/Edit a la izquierda y la siguiente acción a la derecha.
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

En **Server**, escribí la IP, el usuario SSH y la contraseña en **SSH password**.
El campo oculta el valor. **Check connection** autentica sin salir del asistente.
Dejá la contraseña vacía para usar tus claves SSH o la sesión OpenSSH existente.
**SSH options** permite cambiar el puerto. La contraseña no se guarda.

Variables opcionales de conexión sin secretos: `NLF_EVE_HOST`, `NLF_EVE_USER` y
`NLF_SSH_CONTROL`. La clave del host debe estar previamente verificada en
`~/.ssh/known_hosts`; una clave desconocida o cambiada bloquea el acceso.

### GNS3

El asistente usa ahora el conector portable: **GNS3 2.2.x (API v2) o 3.x (API v3)**,
con comprobación de capacidades. Necesita un servidor Linux o una GNS3 VM con el
controlador y un compute local en ese mismo servidor, Python 3, `pexpect` y `telnet`.
No depende de Nexo, de nombres fijos de discos ni de una ruta fija de QEMU.

1. Seleccioná **GNS3 · installed templates**.
2. Completá **SSH server**, **User** y **SSH password**, o usá tu clave SSH existente.
3. Completá **API username** y **API password** con la cuenta de GNS3, distinta de SSH.
4. En **API and storage options**, dejá `http://127.0.0.1:3080` si la API escucha
   en ese puerto del servidor. La conexión hasta el servidor viaja cifrada por SSH.
   Podés cambiar el puerto o usar HTTPS en el mismo host SSH con certificado válido. HTTP fuera de
   loopback y redirecciones se rechazan; no existe una opción para omitir TLS.
5. Dejá **API version** en Auto o elegí v2/v3 explícitamente. API v2 permite campos
   de cuenta vacíos si la instalación no requiere autenticación; v3 exige cuenta.
6. **Projects directory** se descubre desde `/settings` cuando está disponible.
   Si la versión o los permisos no lo permiten, escribí la ruta existente de
   proyectos que usa GNS3 en ese servidor; no una ruta de tu PC.
7. Pulsá **Check connection**. En **Preparation**, seleccioná la plantilla correcta
   para cada familia del escenario, incluyendo VPCS cuando corresponda.

Las plantillas deben usar QEMU o VPCS, compute local y consola Telnet. Su sistema
operativo y numeración de interfaces deben coincidir con la receta: una plantilla
con un nombre parecido no demuestra compatibilidad. No se modifica la plantilla
original, no se descargan imágenes y no se conectan interfaces a redes externas.
Se verifican imágenes, cantidad de adaptadores y RAM de las plantillas elegidas;
si cambian después de Review, se bloquea el despliegue hasta revisarlas otra vez.

Las contraseñas se mantienen solo en memoria y no se incluyen en resultados,
comandos, capturas ni archivos de conexión. Al reabrir el laboratorio, el asistente
pide nuevamente los secretos. El modo `--plain` usa entradas ocultas equivalentes.

**Compatibilidad y pruebas:** el conector nuevo tiene pruebas automatizadas con
API v2/v3 y widgets reales. La campaña histórica 24/24 corresponde a Nexo 3.0.6,
no al nuevo conector portable. La validación real nueva está pendiente. Consultá
[configuración portable](portable-connections.md) para límites y diagnóstico.

#### Conexiones anteriores

Los registros existentes conservan el transporte anterior y sus parámetros.
El acceso Proxmox/QGA sigue siendo una opción avanzada explícita mediante
`NLF_GNS3_GUEST_ID`, `NLF_GNS3_HOST`, `NLF_GNS3_SSH_CONTROL` y
`NLF_GNS3_AUTH_FILE`. Ese transporte conserva su perfil original y utiliza una
sesión OpenSSH autorizada; no admite el nuevo campo de contraseña SSH.
El comando avanzado `nlf deploy` también conserva su contrato anterior;
para conexiones portables nuevas, usá `nlf wizard` o `nlf wizard --plain`.

## Práctica y referencia

| Modo | Preparación | Ejercicio |
|---|---|---|
| Práctica | Configura y comprueba los requisitos de la ficha | Queda pendiente para que lo configures |
| Referencia | Configura y comprueba los requisitos | Aplica también la solución y exige que sus pruebas pasen |

Por ejemplo, B01 en práctica deja interfaces habilitadas, direccionamiento y loopbacks;
vos configurás OSPF. B04 prepara puertos y hosts, pero reserva LACP para el ejercicio.
A07 comienza con una referencia funcional y permite introducir después una falla confirmada.

**Ready** en práctica significa que pasó la preparación. En referencia requiere preparación
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
