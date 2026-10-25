# The "Tested with x402-conformance · Optitransfer" badge

The matrix is opt-in, and so is the badge: a project gets one only after it accepts a listing, and adds it to its own
README. Every listed project with committed evidence has a badge:

    https://atsp-protocol.github.io/x402-conformance/badge/<slug>.svg

It reads "Tested with x402-conformance · Optitransfer" and the version tested, and links to the project's row on the
[Pages matrix](https://atsp-protocol.github.io/x402-conformance/matrix/), which links to the run and its hashes. When
the row is stale (no run within 30 days of the weekly release check, or behind the latest release for 30 days or more)
the badge turns grey and reads "stale". `python3 tools/matrix_rows.py --write` builds it from `matrix/rows/<slug>.json`
and the evidence, and CI fails if a badge is missing, stale or has no listed row.

Copy-paste, with your slug (each row on the Pages matrix shows its own):

```
[![Tested with x402-conformance · Optitransfer](https://atsp-protocol.github.io/x402-conformance/badge/<slug>.svg)](https://atsp-protocol.github.io/x402-conformance/matrix/#<slug>)
```

```
<a href="https://atsp-protocol.github.io/x402-conformance/matrix/#<slug>"><img src="https://atsp-protocol.github.io/x402-conformance/badge/<slug>.svg" alt="Tested with x402-conformance · Optitransfer"></a>
```

## Terms

- Only the official badge URL above counts. A copy, a redrawn badge or a badge for a row that does not exist does not
  count.
- The badge says that a run of the suite exists for that row and which version it tested, and links to it. It is not a
  certification and not an endorsement by Optitransfer, and it says nothing on behalf of the x402 Foundation, Coinbase
  or any project listed.
- The wording stays descriptive. Please don't present the badge or the matrix as a grade, a pass mark or a seal of
  approval, and don't use the x402 logo with it.
- A row, and so its badge, exists only with the project's consent, recorded in the "Add or update my row" issue or the
  PR.
- The badge and the matrix data are CC BY 4.0 ([DATA-LICENSE](../DATA-LICENSE)): "x402-conformance by Optitransfer".

## Privacy

Embeds are counted only from the HTTP referrer in the Pages site's access data. The badge is a plain SVG: no tracking
pixel, no script, no cookie, nothing loaded from another host, and no third-party analytics on the Pages site.
