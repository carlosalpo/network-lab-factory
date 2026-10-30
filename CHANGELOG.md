# Changelog

## 0.2.1 — 2026-10-30

- English terminal interface, plain wizard prompts, help, progress, validation and recovery messages.
- English summaries and exercise instructions for all 24 scenarios, with Basic, Intermediate and Advanced selectors.
- English display of known editorial text in saved Spanish recipes without rewriting their records. Commands, graph integrity checks, identities and explicit deployment/fault confirmations are preserved.
- Refreshed README screenshots and a reproducible fixture-only capture harness.

Validation: the existing 217 offline tests plus one saved-recipe compatibility regression passed. Compared 96 plans (24 scenarios × 2 backends × 2 modes) with the preceding commit: commands, allocations, graphs, checks, actions and identities are unchanged, and all preceding plans still validate. No new live platform campaign was run for this interface-only update.

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
