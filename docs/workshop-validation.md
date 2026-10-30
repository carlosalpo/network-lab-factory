# B01 live validation — 2026-10-29

The new wizard's deployment routine was exercised on EVE-NG Professional 7.2.0-4
using `vios-adventerprisek9-m.spa.159-3` (IOSv 15.9(3)M6), admin tenant 0 over SSH.
Two separate, isolated two-router labs were created. The test runner called the
same deployment routine as the interactive wizard; it did not click through the
complete wizard. Interactive cancellation is covered by the local tests.

| Observation | Practice lab | Reference lab |
|---|---|---|
| New lab, two nodes started and base configured | Passed | Passed |
| Assigned Gi0/1 and Loopback0 up/up on both routers | Passed | Passed |
| Transit reachability, five pings from each end | 5/5 each | 5/5 each |
| OSPF FULL neighbor, expected router ID | Pending by design | Passed on both |
| Remote loopback reachability | Pending by design | 5/5 each |
| Exercise check before the learner configures OSPF | Failed as expected | Not applicable |

Evidence: [practice result](evidence/workshop-b01/practice-result.json),
[reference result](evidence/workshop-b01/reference-result.json), and
[negative exercise check](evidence/workshop-b01/practice-before-exercise.json).
Each contains observed command output. Connection credentials are not included.

The practice lab was opened in the EVE web interface. Both routers, the cable,
native Gi0/1 badges and all seven generated text objects rendered successfully.
After user review, interface addresses and loopback text were reduced to 10 px,
matching the router name, and aligned near each port badge. The revised layout
was applied to both test labs and to the generator, then rechecked in the browser.

Local validation after the layout change: **81 tests passed**, Ruff passed and
`git diff --check` passed. The tests cover existing dual-WAN behavior plus the
workshop's pools, isolation, modes, consistent generated labels, invalid plans,
host validation, cancellation and partial failure records.

These two historical labs were deleted during the final QA cleanup:

- `nlf-b01-practice-review-1029.unl`
- `nlf-b01-reference-review-1029.unl`

No claim is made about other images, EVE editions, user tenants, GNS3, switching,
NX-OS, performance or convergence. Carlos subsequently completed the original
linear wizard and confirmed that it worked.
The resumed menu was exercised in a real PTY: option 1 reached `r01#`, Ctrl+]
and `quit` returned to the menu, and option 0 exited while preserving the lab.

## Full-screen terminal interface · 2026-10-29

The Textual interface reuses the same B01 deployment engine. Validation after the
interface change: **90 tests passed**, Ruff passed and `git diff --check` passed.
The app harness exercises real widgets with a simulated EVE adapter: review and
edit, exact confirmation, practice/reference modes, verification, reopening a
recipe, no compatible image, validation errors, partial failure, cancellation,
console handoff, themes, input preservation and 120/80/60/50-column layouts.
Below 50×16 the interface requests a larger terminal. A separate subprocess test
checks streaming and cancellation while the child is silent.

A real PTY started the new interface, exited with Ctrl+C and restored the original
terminal settings and screen buffer. Live SSH inventory and preflight checks
succeeded against the existing EVE host (7.2.0-4-PRO, validated IOSv image).
No new remote lab was created for this interface revision; its complete deployment
and failure paths were tested with the simulated adapter. Interactive acceptance
of the new full-screen interface remains for Carlos's next run.

## Navigation revision after macOS screenshots

The revision keeps Back/Continue in a fixed bottom bar, preserves form values on
backtracking, replaces the single-image selector with a fixed description, and
shows practice/reference choices directly. Future scenarios and editable default
pools are grouped into expandable sections. The deployment view opens on progress
instead of the interruption button, with elapsed time and the age of the last
server event. An explicit theme selection can restore color after `NO_COLOR`.

Validation: **93 tests passed**, Ruff and whitespace checks passed. Additional
keyboard tests cover the full forward flow, backtracking, pinned actions while
scrolling at 60 columns, explicit confirmation and restoring color. A real PTY
started the revised UI and exited with the original terminal settings restored.
Screens at 150×40 and 60×24 were reviewed. These checks used simulated deployment
data and did not create or alter an EVE-NG laboratory.


The later 24-scenario campaign and both backends are documented in [catalog-validation.md](catalog-validation.md). Earlier counts and limitations above describe their original validation stage.
