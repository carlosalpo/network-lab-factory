# Recorded EVE-NG / IOSv validation — 2026-10-29

Network Lab Factory v0.1.1 completed a live four-router experiment on EVE-NG
Professional 7.2.0-4 and IOSv 15.9(3)M6. This records one tested combination,
including a deliberate failure and recovery. It is not a claim of universal
compatibility or a convergence-time benchmark.

## Environment and isolation

| Component | Observed version / setting |
|---|---|
| EVE-NG | Professional 7.2.0-4 |
| IOSv | 15.9(3)M6, four routers |
| QEMU | 2.4.0, one vCPU and 512 MiB per router |
| Controller Python | 3.12.3 |
| Ansible Core | 2.19.14 |
| Cisco IOS collection | 11.6.0 |
| Ansible netcommon / utils | 8.7.1 / 6.1.1 |
| SSH client | Paramiko 3.5.1, host-key checking enabled |
| Controller network | Temporary Linux network namespace with no default route |

The synthetic scenario used an unused management bridge with no physical uplink,
documentation addresses for management and benchmarking addresses for the data
plane. Device host keys were read through SSH and compared with RSA public keys
obtained independently through the EVE consoles before authentication.

Provisioning used the shipped Ansible playbook with a local connection on the EVE
host. The remote-SSH transport for provisioning was not exercised in this run.
Node startup and console entry used a private test harness. The public release
still requires the documented manual startup/bootstrap workflow and does not
ship automatic lifecycle management.

## Results

| Experiment | Observed result | Evidence |
|---|---|---|
| Provision a fresh lab | One file installed; no failures | [Provision recap](evidence/2026-10-29/provision-fixed-recap.txt) |
| Repeat provisioning to the same name | Rejected with zero changes | [Refusal recap](evidence/2026-10-29/provision-existing-recap.txt) |
| Configure the data plane | Four routers configured successfully | [First apply](evidence/2026-10-29/configure-first-recap.txt) |
| Repeat the same configuration | `changed=0` on all four routers | [Second apply](evidence/2026-10-29/configure-second-recap.txt) |
| Baseline | 8/8 directed OSPF adjacencies FULL; 12/12 five-packet probes passed | [20-check report](evidence/2026-10-29/baseline/report.md) |
| Disable branch Gi0/1 | Route to headquarters moved from `198.18.0.2` to `198.18.0.10` | [Route and ping observations](evidence/2026-10-29/failover-observations.json) |
| Verify during the fault | 18 checks passed, 2 adjacency checks failed; all 12 loopback probes passed | [Deliberately failed report](evidence/2026-10-29/fault/report.md) |
| Restore branch Gi0/1 | Primary next hop returned; all 20 checks passed again | [Recovery report](evidence/2026-10-29/recovery/report.md) |

The fault report is an expected **failure**, not an error hidden by the release.
The baseline requires every original adjacency to exist. Successful forwarding
over an alternate path must not hide the missing primary-link adjacencies.
Ansible completed collection successfully in all three phases; `nlf verify`
returned exit codes 0, 1 and 0 because of the observed checks.

Verification reports show a changed task for saving evidence on the controller.
That task does not modify router configuration. The separate configuration rerun
is the evidence for idempotence.

## Corrections found by live testing

1. **Disconnected ports:** EVE rejected interface records with `network_id=0`.
   The generator now omits those records while keeping four adapters on each node.
2. **Bootstrap password length:** the tested IOSv command rejects secrets longer
   than 25 characters. Local validation now accepts only 12–25 supported characters.
3. **Repeated interface changes:** IOS omits `no shutdown` from the running config
   for enabled interfaces. A text-based task resent it on every run. The playbook
   now uses `cisco.ios.ios_interfaces` with `enabled: true` to compare interface state.

After the third correction, the synthetic data interfaces, loopbacks and OSPF
processes were reset on the dedicated routers; management access was retained.
The published first/second-apply recaps come from the corrected playbook.

## Evidence and reproducibility

The [evidence directory](evidence/2026-10-29/) includes JSON/Markdown reports,
per-router neighbor and ping output, route observations, environment metadata,
the [exact synthetic scenario](evidence/2026-10-29/scenario.yml), its manifest and
[SHA-256 hashes of tested source files](evidence/2026-10-29/tested-source-sha256.json).
Per-router exports preserve device stdout and run/scenario identifiers; Ansible
invocation metadata is omitted. No credentials, host addresses, private inventories
or vendor images are included.

The offline test suite replays the three recorded report sets. This guards against
parser regressions in actual IOS output; it does not rerun the live experiment.

The four dedicated routers were stopped after recovery and the temporary
controller network was removed. Existing lab files were compared with their
pre-test hashes. The new topology and saved router configurations were retained
for local review. See the [cleanup result](evidence/2026-10-29/cleanup-summary.json).

## Boundaries

Probes were collected after allowing OSPF to settle, including a 45-second wait
after the fault and after restoration. That wait is **not a measured convergence
time**. No continuous traffic capture, zero-loss failover, throughput, jitter,
application availability or SLA was measured. The run does not validate other
IOSv/EVE versions, GNS3, production networks or reconciliation of arbitrary
pre-existing configurations.
