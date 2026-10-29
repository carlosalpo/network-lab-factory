# nlf-dual-wan-20261029 — verification

Status: **passed**

Run: `20261029T173935Z-d10039fa`

| Router | Check | Result |
|---|---|---|
| branch | OSPF FULL 198.19.0.2 | passed |
| branch | OSPF FULL 198.19.0.3 | passed |
| branch | Loopback ping 198.19.0.2 | passed |
| branch | Loopback ping 198.19.0.3 | passed |
| branch | Loopback ping 198.19.0.4 | passed |
| wan-primary | OSPF FULL 198.19.0.1 | passed |
| wan-primary | OSPF FULL 198.19.0.4 | passed |
| wan-primary | Loopback ping 198.19.0.1 | passed |
| wan-primary | Loopback ping 198.19.0.3 | passed |
| wan-primary | Loopback ping 198.19.0.4 | passed |
| wan-backup | OSPF FULL 198.19.0.1 | passed |
| wan-backup | OSPF FULL 198.19.0.4 | passed |
| wan-backup | Loopback ping 198.19.0.1 | passed |
| wan-backup | Loopback ping 198.19.0.2 | passed |
| wan-backup | Loopback ping 198.19.0.4 | passed |
| headquarters | OSPF FULL 198.19.0.2 | passed |
| headquarters | OSPF FULL 198.19.0.3 | passed |
| headquarters | Loopback ping 198.19.0.1 | passed |
| headquarters | Loopback ping 198.19.0.2 | passed |
| headquarters | Loopback ping 198.19.0.3 | passed |

This report covers observed OSPF neighbors and five-packet loopback probes.
It does not establish convergence time, throughput, SLA or application health.
