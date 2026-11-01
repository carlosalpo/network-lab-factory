# Terminal interface captures

These English SVGs were exported from the actual Textual widgets at 150 × 44 cells, using fixture inventory (`lab.example`). First captured in 0.2.1 and refreshed for 0.3.0rc2, they show B03 scenario selection, preparation and review. They are interface demonstrations, not live EVE-NG or GNS3 captures or protocol test evidence.

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
`connection.svg` is exported by `scripts/capture_connections.py` from the actual Textual widgets. It uses `gns3.example`, public fixture account labels and masked fixture passwords. The export is checked for literal secret strings. No network authentication or deployment is performed. It was refreshed for 0.3.0rc2, including the entry to the existing-lab assistant.

## Existing-lab addressing review

`scripts/capture_existing.py` exports the actual new assistant widgets from the public, synthetic four-router example in `examples/existing-lab/`. It performs no network requests or device changes. These captures demonstrate UI behavior, not live platform validation:

- [Dark review, 150 × 58 cells](existing-review.svg)
- [Light review, 150 × 58 cells](existing-review-light.svg)
- [Compact review, 80 × 32 cells](existing-review-narrow.svg); scroll vertically for export/application controls.

The reviewed layout shows automatic and fixed subnets together, with generated IOS commands behind an expandable disclosure. Original catalog captures retain their historical provenance.
