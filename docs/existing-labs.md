# Prepare an existing lab

This preview adds IPv4 addressing to a topology you already built. It does not recreate the laboratory. The catalog wizard, saved workshops and legacy connections keep their existing behavior.

**Validation status:** automated tests and synthetic console/API fixtures only. Fresh EVE-NG/GNS3 hardware tests are deferred at the owner's request. Earlier catalog campaign results do not certify this feature.

## Start and connect

Install the branch under review, then run `nlf existing` in an interactive terminal. The same flow is available through **Prepare existing lab** on the regular `nlf wizard` server screen. Dark, light and monochrome themes remain available.

1. Enter the SSH server, user and password or use an existing SSH key. Known-host verification is required, as in the [portable connection guide](portable-connections.md).
2. For GNS3, enter the API credentials on the server form. For EVE-NG, the next screen asks for the separate EVE **web account**, password and API origin. EVE API sessions can end the same account's active browser session; consider a dedicated existing account with access to the intended labs.
3. Select **Prepare existing lab**, then **List laboratories**. GNS3 lists projects accessible to the API account. EVE lists the selected folder, its child folders and `.unl` labs; choose a child folder or type `/` to return to the root, then list again.
4. Start the devices yourself in EVE/GNS3 and open the GNS3 project. The assistant does not start devices, open closed projects, create links, or change platform resources.
5. If consoles require login, expand **Router login**. The initial version uses one device username/password/enable-password set for the lab. Password fields are masked and sent inside SSH; credentials are not saved in the exported plan.
6. Choose the laboratory and **Read topology and addresses**. Each device shows whether its complete configuration could be read. Failed reads are unknown state, never an empty configuration.

The server needs Python 3, `pexpect` and `telnet`. API HTTP is permitted only on server loopback inside SSH. HTTPS uses the server's trusted CA store; self-signed EVE Pro certificates must be trusted explicitly by the server administrator. There is no insecure TLS switch. API redirects are rejected and consoles must belong to the local SSH server.

## Add groups and choose connections

Groups are address-planning labels, for example `Internal`, `External`, `Site A` and `Management`. They do not create VLANs, VRFs, security boundaries or routing policy. Pools must not overlap in this first single-routing-domain version.

Add a group using an explicit network/prefix such as `10.10.30.0/24`. If you enter `10.10.30`, the form suggests `10.10.30.0/24` and asks you to select **Add or update group** again to confirm. Optional reserved ranges accept comma-separated CIDRs, including `/32` host reservations. Enter an existing group name to update its pool.

For a connection, select the group, an automatic subnet size (default `/30`) and optionally a fixed subnet. **Include / update connection** saves that choice into the plan. **Use group for eligible links** adds all eligible direct links without replacing previously saved choices. Shared segments and unmapped interfaces require individual review. **Remove connection from plan** excludes one from configuration.

Under **Endpoint mapping and fixed addresses**, select the platform endpoint and its observed IOS interface. GNS3 port names do not always match IOS interface names; this mapping must be reviewed by the operator. Optionally set a fixed host IP. Select **Set endpoint override**, then **Include / update connection**. A fixed host address must fit the chosen or allocated subnet; specifying the subnet explicitly is the clearest way to pin a host outside the first available subnet.

Example with two groups:

| Connection | Group pool | Choice | Result |
| --- | --- | --- | --- |
| R1–R2 | Internal · `10.10.30.0/24` | Automatic `/30` | `10.10.30.4/30` |
| R3–R4 | Internal · `10.10.30.0/24` | Fixed `10.10.30.0/30`, R3 fixed `.2` | R3 `.2`, R4 `.1` |
| A separate WAN link | External · `10.20.0.0/24` | Automatic `/30` | `10.20.0.0/30` |

Manual and existing subnets are reserved **before** automatic allocation. Rebuilding the same snapshot and choices produces the same plan. Existing IP addresses are preserved; this preview does not renumber them. An existing address outside the selected pool requires a suitable group pool. Conflicting existing masks or addresses block the plan.

## Segment and device limits

| Area | Supported in this preview |
| --- | --- |
| GNS3 | 2.2.x/API v2 or 3.x/API v3 through direct SSH; opened project, local QEMU compute, running Telnet consoles and recognized IOS/IOS XE CLI |
| EVE-NG | Authenticated web API folder/lab/node/interface discovery; running `vios` routers with local Telnet consoles; isolated `bridge` networks |
| Interfaces | Observed physical routed IPv4 interfaces; existing address retained or one missing primary address added |
| Addressing | Non-overlapping group pools, reserved ranges, fixed subnet/host overrides, deterministic allocation, `/31` for two-endpoint links only |
| Shared segments | EVE bridge with multiple router endpoints, explicit operator confirmation and sufficient host capacity |
| Scale | Up to 64 nodes and 256 segments per laboratory |

GNS3 links through switches/hubs are **not collapsed automatically** into broadcast domains. Virtual switch VLANs, external clouds, EVE OVS/pnet networks, L2 interfaces, VRFs, subinterfaces, secondary/dynamic/unnumbered addresses, port channels, IPv6, loopback creation, distributed compute and non-Telnet consoles are outside this first version. Unselected interfaces with readable IPv4 addresses still reserve their observed networks to help prevent conflicts.

If any lab node is unsupported or unreadable, eligible connections can still be reviewed/exported, but **application is blocked for the entire lab**: unknown nodes can contain conflicting addresses. This is intentionally stricter than export. The tool does not discover devices outside the chosen laboratory and does not replace an authoritative IPAM system.

## Review, apply and save

**Build addressing preview** shows every included endpoint's group, old address, proposed address and Add/Keep decision, followed by the exact generated IOS commands. Form edits must be saved with the corresponding group, endpoint and connection buttons before building the preview. Pool overlap, exhausted capacity, duplicate hosts, reserved addresses, reused interfaces or unresolved mappings prevent review.

**Export plan and commands** creates a unique local folder under `build/existing/`, mode `0700`, with files mode `0600`: `plan.json`, `review.md`, and numbered device `.cfg` snippets. These contain addressing and generated commands, not raw configurations or passwords. The plan retains the group/connection intent for inspection and reproducibility; reopening a saved plan in the UI is not part of this preview.

To apply, type the **exact laboratory name**. The assistant:

1. Re-reads topology and console identity and locks its own per-lab operation journal.
2. Reads every node again and compares the full normalized running-configuration hash with the reviewed snapshot.
3. Writes private running-configuration backups before any device configuration commands.
4. Rechecks topology, then adds only missing primary IPv4 addresses. Existing addresses, routing, descriptions and interface shutdown state remain unchanged.
5. Reads the resulting configuration and verifies the planned addresses and preserved shutdown state. It does **not** claim ping reachability or protocol convergence, and does not enable shutdown interfaces.

Backups and the durable operation journal remain on the SSH server under `~/.local/state/network-lab-factory/existing/<run-id>/` (directory `0700`, files `0600`). They can contain device secrets. Do not commit, publish or copy them into documentation. There is no automatic retention deletion or automatic rollback in this feature.

After a completely verified application, **Save permanently** becomes available. Type `SAVE` to persist running configuration on changed devices. Before writing, the assistant rechecks topology and configuration hashes and privately backs up their existing startup configurations. IOS `write memory` saves **all current settings**, including pre-existing unsaved changes; it is not limited to the new IP commands. A successful console acknowledgement is required for each device.

If a command fails or the connection disappears, stop and inspect the lab plus its private journal. The UI disables immediate retries of uncertain writes. Partial application/save results list attempted or confirmed devices; they never become a success or automatically roll back. A local lock prevents concurrent NLF operations using the same SSH account, but cannot lock out other platform accounts or manual console users. Use the lab exclusively during application.

## Automated evidence and references

Tests cover allocation invariants, preserved addresses, both platform discovery formats, unknown devices, drift before mutation, private backups, partial failure journals, save gating, secret-safe console errors, a local pseudo-terminal IOS login/enable/read exchange, and the real Textual widget flow. UI captures use an explicitly synthetic topology and no live server.

- [EVE-NG API documentation](https://www.eve-ng.net/index.php/how-to-eve-ng-api/)
- [GNS3 v2 node and console schema](https://api.gns3.net/en/latest/api/v2/controller/node/projectsprojectidnodesnodeid.html)
- [GNS3 v3 controller API](https://apiv3.gns3.net/)
