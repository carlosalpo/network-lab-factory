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


## Connection form (portable connector)
`connection.svg` is exported by `scripts/capture_connections.py` from the actual Textual widgets. It uses `gns3.example`, public fixture account labels and masked fixture passwords. The export is checked for literal secret strings. No network authentication or deployment is performed. The earlier scenario/preparation/review captures remain historical English UI examples.
