# Synthetic existing-lab fixture

These four routers are fictional. No EVE/GNS3 instance was contacted to create this fixture. It contains no credentials or private device configurations.

`snapshot.json` represents the read-only addressing observation. `intent.json` uses one group pool and two links: R3–R4 has a fixed subnet and R3 has a pinned host address; R1–R2 receives the next available subnet automatically. The public fixture drives the actual UI screenshot script.

Regenerate captures after installing development dependencies:

```sh
python scripts/capture_existing.py
```

Do not use this snapshot to configure real devices. Live application requires a fresh read and review of the actual target laboratory.
