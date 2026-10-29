# Validation scope

Version 0.1.1 combines offline implementation tests with a
[recorded live experiment](live-validation.md) on EVE-NG Professional 7.2.0-4 and
IOSv 15.9(3)M6. Evidence for one combination does not establish compatibility with
every emulator or image version.

| Area | Evidence in this repository | Remaining boundary |
|---|---|---|
| Input model | Automated valid/invalid scenarios, duplicate YAML keys, addressing and wiring checks | Broader topology examples |
| Compiler | Deterministic artifacts, integrity hashes, four routers booted in EVE | Other EVE versions and templates |
| Credentials | Private bootstrap files, input rejection, live SSH with keys verified against consoles | Enterprise credential management |
| Ansible | Live apply and second run with zero changes on four routers | Reconciliation of arbitrary pre-existing configurations |
| Reports | Synthetic edge cases plus replay of genuine baseline/fault/recovery output | Continuous monitoring |
| Failover | Primary/backup/primary next-hop observations; 20/18/20 passed checks across the three phases | Measured convergence and traffic loss during switchover |

CI never contacts the EVE-NG server or needs vendor images. Replaying captured
device output checks the evaluator; it does not constitute another live run.
The live reports deliberately include a failed baseline during the injected fault.

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
scenario copies are excluded from Git by default. Only reviewed evidence is
explicitly included under `docs/evidence/`.

## Acceptance for another live compatibility run

Record the exact EVE-NG edition/version, IOSv image version, controller Python/Ansible
versions and collection versions. Do not upload the vendor image itself.

1. Provision a fresh lab and confirm node/interface mapping and boot.
2. Bootstrap all four management interfaces and verify host keys.
3. Apply the configuration, then repeat it and record whether changes are reported.
4. Collect all 8 directed OSPF neighbor checks and 12 directed loopback probes.
5. Complete primary-path failure and recovery, retaining the raw observations.
6. Review evidence for private data before publishing run identifiers and source hashes.
7. Restore the experiment, stop dedicated resources and verify existing labs were preserved.

The expected full baseline is 20 checks. Five ICMP replies do not establish application
availability, throughput, jitter, loss rate over time or an SLA. OSPF FULL establishes
an adjacency at collection time, not that every route or policy is correct.
