# What the initial release verifies

This document distinguishes implementation tests from a real network experiment.

| Area | Evidence in this repository | Remaining evidence |
|---|---|---|
| Input model | Automated valid/invalid scenarios, duplicate YAML keys, addressing and wiring checks | Broader topology examples |
| Compiler | Deterministic files, matching inventory/configs, connected XML ports, hashes | Import and boot on a named EVE-NG build |
| Credentials | Private local bootstrap files, no secret in generated build, input injection rejection | First boot and SSH on a named IOSv image |
| Ansible | Syntax checks with installed Cisco/Ansible collections | Live configuration and second-run idempotence |
| Reports | Synthetic success, packet loss, neighbor failure, stale/missing/malformed evidence | Genuine router evidence |
| Failover | Manual experiment and recovery procedure | Measured traffic behavior and convergence |

CI never contacts your EVE-NG server or needs vendor images. Test fixtures are
synthetic; a passing CI run is evidence about software behavior, not a live lab.

## Local verification

```bash
python -m pip install -e '.[dev,ansible]'
ansible-galaxy collection install -r ansible/requirements.yml
ruff check src tests
pytest -q
nlf validate examples/dual-wan.yml
nlf build examples/dual-wan.yml --output build/review
ansible-inventory -i build/review/inventory.yml --list
ansible-playbook -i build/review/inventory.yml ansible/configure.yml --syntax-check
ansible-playbook -i build/review/inventory.yml ansible/verify.yml --syntax-check
ansible-playbook -i ansible/eve-host.example.yml ansible/provision.yml --syntax-check
```

The inventory command may expose values if you have already set credential variables.
Do not publish its output from a credentialed shell. All generated files and local
scenario copies are excluded from Git by default.

## Acceptance for a future live-validated release

Record the exact EVE-NG edition/version, IOSv image version, controller Python/Ansible
versions and collection versions. Do not upload the vendor image itself.

1. Provision a fresh lab and confirm node and interface mapping in the EVE UI.
2. Bootstrap all four management interfaces and verify host keys.
3. Apply the configuration, then repeat it and record whether changes are reported.
4. Collect all 8 directed OSPF neighbor checks and 12 directed loopback probes.
5. Complete primary-path failure and recovery, retaining the raw observations.
6. Publish reviewed, synthetic-lab-only evidence with the run identifier and commit.

The expected full baseline is 20 checks. Five ICMP replies do not establish application
availability, throughput, jitter, loss rate over time or an SLA. OSPF FULL establishes
an adjacency at collection time, not that every route or policy is correct.
