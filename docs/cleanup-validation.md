# QA cleanup

On October 29, 2026, **41 EVE-NG labs and 49 GNS3 projects** created for validation were powered off and removed. This includes unsuccessful attempts, repeats, practice samples and fault/recovery tests.

The final ownership-scoped check observed zero QA lab definitions, zero QA runtime/project directories and zero QA emulators. Eighteen pre-existing GNS3 projects were preserved. See the [public cleanup summary](evidence/catalog/cleanup.json).

Before removal, the cleanup verified the expected identity, location and nodes. EVE used explicit power-off; GNS3 confirmed stopped nodes before project deletion. Empty QA parent folders were removed. No server was shut down and no unrelated project was deleted.

Local results and screenshots were retained. Base operating-system images, including the ASA image added with authorization, remain installed for future labs. The private ownership manifest and administration records are excluded from the public repository.

Historical result files are evidence, not active labs: their old consoles no longer exist. Create a new lab through the [wizard](workshop-wizard.md) to try the tool.
