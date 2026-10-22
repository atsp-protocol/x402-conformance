# Live run, 2026-10-20, x402-conformance 1.3.0

`GET /supported` only, one request per facilitator. One operator is listed as `facilitator-A` with its name withheld.
Its response body, `supported-facilitator-A.json`, is unchanged byte for byte and still matches the `body_sha256`
recorded in `run.json`. Only that entry's `target` label in `run.json` was changed, so `SHA256SUMS` was regenerated.
Check it with `sha256sum -c SHA256SUMS` from this directory.
