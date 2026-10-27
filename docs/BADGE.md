# The x402-conformance badge (Optitransfer)

The matrix is opt-in, and so is the badge: a project gets one only after it accepts a listing, and adds it to its own
README. Every listed project with results has a badge:

    https://atsp-protocol.github.io/x402-conformance/badge/<slug>.svg

It names the row's tier (see [MATRIX.md, Two tiers](MATRIX.md#two-tiers)), the suite tag and Optitransfer, then
checks passed out of applicable checks and the date:

| tier | left | right |
|---|---|---|
| tier 1, run from outside the project's stack against its public testnet endpoint | External-verified · x402-conformance <tag> · Optitransfer | 8/9 checks · 2026-10-20 |
| tier 2, the full suite in the project's own CI, attestation verified | Full suite (self-hosted) · x402-conformance <tag> · Optitransfer | 65/66 checks · 2026-10-22 |

(The counts above are illustrative.) A tier-1 badge covers only the external checks; the row shows how many checks
need the self-hosted run. The badge links to the project's row on the
[Pages matrix](https://atsp-protocol.github.io/x402-conformance/matrix/), which links to the run or the attestation.
When the row is stale (no run within 30 days of the weekly release check, or behind the latest release for 30 days or
more) the badge turns grey and reads "stale"; when a tier-2 attestation comes from an older suite release than the one
pinned, it turns grey and reads "rerun on current suite". `python3 tools/matrix_rows.py --write` builds it from `matrix/rows/<slug>.json`
and the evidence, and CI fails if a badge is missing, stale or has no listed row.

Listed projects display the badge in their README with attribution to Optitransfer/x402-conformance. Copy-paste
README snippet, with your slug (each row in MATRIX.md and on the Pages matrix shows its own). It stays the same when
your row moves from tier 1 to tier 2; the image shows the tier:

```
[![Tested with x402-conformance · Optitransfer](https://atsp-protocol.github.io/x402-conformance/badge/<slug>.svg)](https://atsp-protocol.github.io/x402-conformance/matrix/#<slug>) Conformance tested by [Optitransfer/x402-conformance](https://atsp-protocol.github.io/x402-conformance/matrix/#<slug>)
```

```
<a href="https://atsp-protocol.github.io/x402-conformance/matrix/#<slug>"><img src="https://atsp-protocol.github.io/x402-conformance/badge/<slug>.svg" alt="Tested with x402-conformance · Optitransfer"></a> Conformance tested by <a href="https://atsp-protocol.github.io/x402-conformance/matrix/#<slug>">Optitransfer/x402-conformance</a>
```

The weekly freshness check reads your public README through the GitHub API, a plain read with no referrer and nothing
embedded. If the README no longer links your row or badge, your row is flagged "badge in README: missing (flagged)".

## Terms

- Only the official badge URL above counts. A copy, a redrawn badge or a badge for a row that does not exist does not
  count.
- The badge says that a run of the suite exists for that row, at which tier and suite tag, and links to it. It is not a
  certification and not an endorsement by Optitransfer, and it says nothing on behalf of the x402 Foundation, Coinbase
  or any project listed.
- The wording stays descriptive. Please don't present the badge or the matrix as a grade, a pass mark or a seal of
  approval, and don't use the x402 logo with it.
- A row, and so its badge, exists only with the project's consent, recorded in the "Add or update my row" issue or the
  PR.
- The badge and the matrix data are CC BY 4.0 ([DATA-LICENSE](../DATA-LICENSE)): "Optitransfer/x402-conformance".

## Privacy

Embeds are counted only from the HTTP referrer in the Pages site's access data. The badge is a plain SVG: no tracking
pixel, no script, no cookie, nothing loaded from another host, and no third-party analytics on the Pages site.
