# The "Tested with x402-conformance" badge

Every matrix row with committed evidence has a badge:

    https://atsp-protocol.github.io/x402-conformance/badge/<row>.svg

It reads "Tested with x402-conformance" and links to the row in [MATRIX.md](MATRIX.md), which links to the run and its
hashes. `python3 tools/compat_matrix.py --write` builds it from the evidence, and CI fails if a badge is missing, stale
or has no row.

To embed it, link the badge to your row:

```
[![Tested with x402-conformance](https://atsp-protocol.github.io/x402-conformance/badge/<row>.svg)](https://github.com/atsp-protocol/x402-conformance/blob/main/docs/MATRIX.md#row-<row>)
```

## Terms

- Only the official badge URL above counts. A copy, a redrawn badge or a badge for a row that does not exist does not
  count.
- The badge says that a run of the suite exists for that row and links to it. It states no result on its own. It is
  not an endorsement by Optitransfer, and it says nothing on behalf of the x402 Foundation, Coinbase or any project
  listed.
- The wording stays descriptive. Please don't present the badge or the matrix as a grade, a pass mark or a seal of
  approval, and don't use the x402 logo with it.
- A row, and so its badge, exists only with the project's consent, recorded in the "Add or update my row" issue or the
  PR.
- The badge and the matrix data are CC BY 4.0 ([DATA-LICENSE](../DATA-LICENSE)): "x402-conformance by Optitransfer".

## Privacy

Embeds are counted only from the HTTP referrer in the Pages site's access data. The badge is a plain SVG: no tracking
pixel, no script, no cookie, nothing loaded from another host, and no third-party analytics on the Pages site.
