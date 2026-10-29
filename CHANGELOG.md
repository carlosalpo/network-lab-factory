# Changelog

## 0.1.0 — 2026-10-29

Initial public implementation for review.

- Strict YAML scenario validation, IPv4 address checks and topology checks.
- Deterministic EVE-NG topology, Ansible inventory and IOS routing previews.
- Non-overwriting Ansible provisioning with image and bridge preflight checks.
- Private local SSH bootstrap snippets and dedicated IOSv configuration playbook.
- Read-only OSPF/ICMP evidence collection with unique-run JSON and Markdown reports.
- 61 offline tests, three playbook syntax checks and a GitHub Actions Python matrix.
- Deployment, failover/recovery and validation-boundary documentation.

Local checks used Python 3.12.14, ansible-core 2.19.14, cisco.ios 11.6.0,
ansible.netcommon 8.7.1 and ansible.utils 6.1.1. The CI run records its own resolved
versions. No EVE-NG/IOSv live compatibility run has been performed for this release.
