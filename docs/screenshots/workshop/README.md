# Terminal interface captures

These English SVGs were exported from the actual Textual widgets in version 0.2.1 at 150 × 44 cells, using fixture inventory (`lab.example`). They show B03 scenario selection, preparation and review. They are interface demonstrations, not live EVE-NG or GNS3 captures or protocol test evidence.

Reproduce them from an installed checkout:

```sh
python scripts/capture_workshop.py
```

The harness uses `WorkshopApp.run_test`, allows only fixture discovery/preflight, and refuses deployment or other mutations. It creates no lab or deployment record.

- [Choose a scenario](scenario.svg)
- [Prepare the lab](prepare.svg)
- [Review before deployment](review.svg)

Network validation is recorded separately in [the catalog evidence](../../evidence/catalog/README.md). The [native EVE-NG capture](../platforms/README.md) keeps its original provenance.
