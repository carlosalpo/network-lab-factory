# Native platform captures

## EVE-NG · I01 three-tier campus

![Native EVE-NG topology: seven devices and nine links](eve-ng-topology.png)

The native EVE-NG canvas shows the I01 campus reference scenario: one core switch, two distribution switches, two access switches and two hosts. Its nine links have generated interface and address labels.

This is a historical topology capture from the catalog QA campaign. It shows the generated layout; it does not establish protocol state, current availability or a new validation run. The separate [I01 device observations](../../evidence/catalog/eve-i01-reference.json) contain the recorded checks. See the [scenario guide](../../catalog/I01.md) and [full validation matrix](../../catalog-validation.md) for their scope.

### Provenance

- Original file date: **29 October 2026**, based on filesystem creation/modification metadata, not an embedded capture timestamp.
- Documentation preparation: **30 October 2026**.
- Documentation reference: **v0.2.0**, commit `0e9055867835522c0ca909f341f9a857645104e4`. The source commit at the moment of the original screenshot is not established.
- Method: privacy crop of an existing native screenshot, retaining the EVE controls and the complete topology. Browser chrome and administration details are excluded. No topology, labels or device states were redrawn.
- Visible addresses belong to the synthetic catalog pools. The private full-screen source is not distributed.
- Dimensions: **1100 × 850**. Exact crop coordinates, original-source hash and delivered-image hash are in [manifest.json](manifest.json).

## GNS3

A native GNS3 screenshot is not included yet. The [GNS3 validation records](../../catalog-validation.md) remain available independently; those device observations are not screenshots of its interface.

## Verify the files

From this directory:

```sh
shasum -a 256 -c SHA256SUMS.txt
```

The hashes detect file changes relative to this record; they are not a signed attestation.
