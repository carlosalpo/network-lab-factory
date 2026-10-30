# Catalog validation

**24/24 reference scenarios passed on each backend: 48 recorded deployments.**

One concrete variant per scenario was tested. Each linked record contains observed preparation and exercise checks. These results do not certify arbitrary OS images, custom topologies, production readiness, performance or convergence time.

| Case | Objective | EVE-NG 7.2.0-4 PRO | GNS3 3.0.6 |
|---|---|---|---|
| [B01](catalog/B01.md) | OSPF punto a punto | [Passed](evidence/catalog/eve-b01-reference.json) | [Passed](evidence/catalog/gns3-b01-reference.json) |
| [B02](catalog/B02.md) | Rutas estáticas | [Passed](evidence/catalog/eve-b02-reference.json) | [Passed](evidence/catalog/gns3-b02-reference.json) |
| [B03](catalog/B03.md) | VLAN y trunk | [Passed](evidence/catalog/eve-b03-reference.json) | [Passed](evidence/catalog/gns3-b03-reference.json) |
| [B04](catalog/B04.md) | Port Channel con LACP | [Passed](evidence/catalog/eve-b04-reference.json) | [Passed](evidence/catalog/gns3-b04-reference.json) |
| [B05](catalog/B05.md) | Spanning Tree con dos switches | [Passed](evidence/catalog/eve-b05-reference.json) | [Passed](evidence/catalog/gns3-b05-reference.json) |
| [B06](catalog/B06.md) | Anillo de tres switches | [Passed](evidence/catalog/eve-b06-reference.json) | [Passed](evidence/catalog/gns3-b06-reference.json) |
| [B07](catalog/B07.md) | Anillo de cuatro switches | [Passed](evidence/catalog/eve-b07-reference.json) | [Passed](evidence/catalog/gns3-b07-reference.json) |
| [B08](catalog/B08.md) | Enrutamiento entre VLAN | [Passed](evidence/catalog/eve-b08-reference.json) | [Passed](evidence/catalog/gns3-b08-reference.json) |
| [I01](catalog/I01.md) | Campus de tres capas | [Passed](evidence/catalog/eve-i01-reference.json) | [Passed](evidence/catalog/gns3-i01-reference.json) |
| [I02](catalog/I02.md) | OSPF con varias áreas | [Passed](evidence/catalog/eve-i02-reference.json) | [Passed](evidence/catalog/gns3-i02-reference.json) |
| [I03](catalog/I03.md) | Sucursal con doble WAN | [Passed](evidence/catalog/eve-i03-reference.json) | [Passed](evidence/catalog/gns3-i03-reference.json) |
| [I04](catalog/I04.md) | Gateway redundante | [Passed](evidence/catalog/eve-i04-reference.json) | [Passed](evidence/catalog/gns3-i04-reference.json) |
| [I05](catalog/I05.md) | BGP entre sistemas autónomos | [Passed](evidence/catalog/eve-i05-reference.json) | [Passed](evidence/catalog/gns3-i05-reference.json) |
| [I06](catalog/I06.md) | VRF y aislamiento | [Passed](evidence/catalog/eve-i06-reference.json) | [Passed](evidence/catalog/gns3-i06-reference.json) |
| [I07](catalog/I07.md) | ACL y NAT de laboratorio | [Passed](evidence/catalog/eve-i07-reference.json) | [Passed](evidence/catalog/gns3-i07-reference.json) |
| [I08](catalog/I08.md) | IPv6 y doble pila | [Passed](evidence/catalog/eve-i08-reference.json) | [Passed](evidence/catalog/gns3-i08-reference.json) |
| [A01](catalog/A01.md) | Nexus vPC | [Passed](evidence/catalog/eve-a01-reference.json) | [Passed](evidence/catalog/gns3-a01-reference.json) |
| [A02](catalog/A02.md) | Leaf spine con VXLAN EVPN | [Passed](evidence/catalog/eve-a02-reference.json) | [Passed](evidence/catalog/gns3-a02-reference.json) |
| [A03](catalog/A03.md) | MPLS L3VPN | [Passed](evidence/catalog/eve-a03-reference.json) | [Passed](evidence/catalog/gns3-a03-reference.json) |
| [A04](catalog/A04.md) | Redistribución controlada | [Passed](evidence/catalog/eve-a04-reference.json) | [Passed](evidence/catalog/gns3-a04-reference.json) |
| [A05](catalog/A05.md) | Multihoming BGP | [Passed](evidence/catalog/eve-a05-reference.json) | [Passed](evidence/catalog/gns3-a05-reference.json) |
| [A06](catalog/A06.md) | Segmentación con firewall | [Passed](evidence/catalog/eve-a06-reference.json) | [Passed](evidence/catalog/gns3-a06-reference.json) |
| [A07](catalog/A07.md) | Troubleshooting guiado | [Passed](evidence/catalog/eve-a07-reference.json) | [Passed](evidence/catalog/gns3-a07-reference.json) |
| [A08](catalog/A08.md) | Comparación entre versiones | [Passed](evidence/catalog/eve-a08-reference.json) | [Passed](evidence/catalog/gns3-a08-reference.json) |

## Additional observations

- GNS3 practice samples: B04, A02, A03, A06 and I08. Their preparation passed; their exercise remains pending by design. See the [evidence index](evidence/catalog/index.json).
- Fault/recovery: B04 and A07 on EVE-NG; B04, I03, A05 and A07 on GNS3. The LACP fault disconnects both ends of one member link. See the corresponding `fault-recovery.json` files in the [evidence directory](evidence/catalog/).
- [Nexus automatic restart](evidence/catalog/nxos-restart.json) retained the selected boot image without manual loader intervention.
- 217 local tests passed. These test generation, real terminal widgets with fixture inventory, validation, transports and failure behavior; they do not replace the live network observations.
- The original B01 practice/reference experiment is documented in [workshop-validation.md](workshop-validation.md).

## What changed during validation

Live testing found and corrected console prompt handling, ASA enable initialization, NX-OS initial boot and boot-image persistence, explicit EVE power-off semantics, source addresses for BGP/MPLS probes, two-ended LACP fault injection, and IPv6 VPCS reply detection. VXLAN uses IOSv endpoints with routing disabled after packet inspection exposed a VPCS/9000v ARP interoperability issue. OSPF observations allow up to 120 seconds for adjacency formation; preparation probes allow up to 90 seconds. A timeout or incomplete result is not a pass.

Some attempts failed and were repeated as separate isolated labs after corrections. This table links the final successful observations; it is not a claim of failure-free deployment on every attempt.

## Scope and cleanup

EVE uses admin / tenant 0. GNS3 uses the documented 3.0.6 installation profile through direct SSH or an explicitly authorized guest-agent transport. Compatible images must already exist; the assistant does not download proprietary operating systems.

[All owned test labs were deleted](cleanup-validation.md): 41 EVE-NG labs and 49 GNS3 projects, with zero remaining QA emulators or lab files. Eighteen pre-existing GNS3 projects were preserved. Local evidence and base images remain available.

## Reproduction

Use an authorized isolated laboratory and the documented image profiles. The [wizard guide](workshop-wizard.md) covers setup. `scripts/validate_catalog_live.py` accepts case IDs, backend, host and an authenticated SSH control socket; it creates new QA resources and stops them after each case. It does not delete them. `scripts/validate_fault_live.py` deliberately changes links in its own new labs. Neither script should target production infrastructure.
