# Network Lab Factory · terminal workshop

## Product intent

Help a network learner or engineer spend time on the exercise instead of wiring,
naming and addressing a lab. The user chooses a scenario and installed compatible
images, reviews the resolved topology, explicitly confirms creation, and receives
the location and observed preparation status. Practice prepares prerequisites;
reference also configures and checks the exercise.

## Existing interface contract

- Operate mode: Spanish terminal assistant, six steps, keyboard first.
- Keep the incumbent Textual interface and its dark, light and monochrome themes.
- Fixed bottom navigation: Back/Edit on the left, the next action on the right.
- Tab/Shift+Tab move focus; arrows select; Enter activates; Escape goes back before
  deployment; F1 opens help; Ctrl+T changes theme. Field submission only moves to
  the primary action. Creation requires typing DEPLOY and activating that action.
- Scenario entry focuses Level first so Basic, Intermediate and Advanced are
  discoverable. Changing a scenario updates its description and required images.
- Preparation separates lab identity, system versions, practice/reference mode,
  and optional address pools. Review shows a compact ASCII graph with expandable
  interfaces and addresses. Progress and results come from server observations.
- Preserve partial failures and never silently repeat creation or overwrite labs.
- Target scene: macOS Terminal, 150 columns × 40 rows. Support 80×24 through vertical
  scrolling and a hidden sidebar; below 50×16 show a resize message. No web/mobile
  design conventions are substituted for terminal behavior.

## Scope and evidence

The catalog implements one concrete variant per each of 24 scenarios. A generated
recipe is not a live validation. See docs/catalog/README.md for executable scope
and docs/catalog-validation.md for observed results and outstanding validation.
The EVE adapter uses the documented admin tenant 0 SSH profile. GNS3 uses an
explicit 3.0.6 Nexo host profile, either direct SSH or the authorized temporary
Proxmox guest-agent session. Platform selection clears previous inventory; the
connection label distinguishes the GNS3 VM from its Proxmox access host. Backend
validation results are tracked separately.

UI captures under .impeccable/review and outputs/catalog-ui are actual Textual
widgets driven by fixture inventory. They verify presentation and interaction,
not server provisioning. Live network evidence is stored separately under
outputs/catalog-qa. Existing theme colors and terminal controls remain the visual
baseline; this work extends the catalog and navigation, not the brand identity.
