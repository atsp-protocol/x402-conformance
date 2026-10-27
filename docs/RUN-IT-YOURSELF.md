# Run it yourself

Facilitators, SDKs, merchants and vendors can run x402-conformance on their own code and put the result in the
[matrix](MATRIX.md) themselves. Run it on your own testnet or devnet endpoint, or on a local build. Never run it on
mainnet, and never against a facilitator you don't operate. Nothing here pays, and the live checks are unpaid GETs (plus
one unpaid HEAD for R16a, only with the operator's permission).

## CLI

Try it first against the bundled mock: no project, no wallet, no chain.

<!-- runnable: cli subst="npx -y x402-conformance-svm=node ts/dist/src/cli.js;pipx run --spec x402-conformance x402conf=python3 -m x402conf" -->
```
npx -y x402-conformance-svm demo                       # R0-R10 against a bundled mock resource server
pipx run --spec x402-conformance x402conf demo         # S1-S4, P1-P7 and the F self-test against a bundled mock
```

Then your own server, on loopback, behind the facilitator double (Solana devnet or Base Sepolia ids):

```
npx -y x402-conformance-svm probe --resource http://127.0.0.1:4020/paid --start "PORT=4020 node server.js" --out run.json
```

Or the unpaid 402 of your public testnet endpoint (one GET, paced, never pays):

```
pipx run --spec x402-conformance x402conf resource --min-interval 5 --max-requests 3 https://sandbox.example.com/paid
```

## GitHub Action

The same checks in CI. With `evidence: true` the Action also writes your row's evidence bundle (the run.json as the
tool wrote it, a README and `SHA256SUMS`) and uploads it as an artifact. Evidence mode refuses a mainnet network
before it sends any request.

<!-- runnable: actions -->
```yaml
on: [push, pull_request]
jobs:
  x402:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: atsp-protocol/x402-conformance@v1
        with:
          resource-url: http://127.0.0.1:4020/paid
          start: PORT=4020 node server.js
          evidence: true
          row: myserver-1.2.0
```

`evidence-upload: false` keeps the bundle in the `evidence-dir` output without uploading it, if you'd rather seal or
filter it yourself first.

For tier 2 of the matrix, Full suite (self-hosted), run it on each release with `attest: true`. The Action writes one
entry per catalogue check (with a reason for each check you list in `not-applicable`), signs it with GitHub artifact
attestations and uploads it as `x402-conformance-attestation-<row>`. The job needs `id-token: write` and
`attestations: write`:

<!-- runnable: actions -->
```yaml
on:
  release:
    types: [published]
jobs:
  x402:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write
      attestations: write
    steps:
      - uses: actions/checkout@v4
      - uses: atsp-protocol/x402-conformance@v1
        with:
          resource-url: http://127.0.0.1:4020/paid
          start: PORT=4020 node server.js
          retry: true
          attest: true
          not-applicable: "U1: no upto scheme; X1: no paid MCP tools"
          row: myserver
```

The job summary lists every check and ends with the "Tested with x402-conformance" line and the version. The
`evidence`, `row`, `attest` and `not-applicable` inputs come with the first release after 1.6.0; until then use
`@main` (an attestation made with `@main` is listed as "rerun on current suite" until a release is pinned).

## MCP

In any MCP client, add the server and ask it to check your endpoint:

<!-- runnable: json -->
```json
{ "mcpServers": { "x402-conformance": { "command": "npx", "args": ["-y", "x402-conformance-mcp"] } } }
```

See [USING.md](USING.md) for the tools it offers.

## Get listed or update your row

Open the [Add or update my row](https://github.com/atsp-protocol/x402-conformance/issues/new?template=matrix-row.yml)
form: project name, type, repository, languages, chain families and networks, the environments you offer, your
public testnet endpoint, version or commit, a public contact handle (no emails) and the four consents. Then pick a
tier (or both):

1. **External-verified**: tick the notify hook and give the testnet endpoint. The run queue checks it from outside
   your stack on each new release: P1 to P7, P9, P10 and R24 from unpaid GETs, and R16a from one unpaid HEAD if you
   tick the box that allows it. At most eight requests, paced, never your code.
2. **Full suite (self-hosted)**: link a release run of the Action with `attest: true` in your own repository. The
   workflow downloads the attestation, checks its signature (`gh attestation verify`: a workflow in your repository,
   at the attested commit and tag) and its contents (`tools/attestation.py`: the pinned suite, every applicable check
   present) and upgrades your row. Nothing is rerun on our side. The signature shows where and on which commit the
   run happened; the row reads as your own signed report.

Can't add a CI step? A full run against a hosted testnet staging stack is possible by arrangement, with written
permission. It is the exception, not part of the queue.

A workflow checks the issue and opens a pull request with your row for review. Your row shows its tier, checks
passed out of applicable checks, the failed count, the denominator (exercised / not applicable / needs the
self-hosted run), the suite tag, the version tested and the date, with a link to the evidence. It never shows a score
or a rank. If a check fails, I tell you privately first (SECURITY.md). Once your row is listed you display its badge
([BADGE.md](BADGE.md)). The public results are CC BY 4.0 ([DATA-LICENSE](../DATA-LICENSE)).

Is a check missing? Propose one with the
[check proposal](https://github.com/atsp-protocol/x402-conformance/issues/new?template=check-proposal.yml) form.

## Keep your row fresh

Copy [templates/x402-conformance.yml](templates/x402-conformance.yml) into your repository as
`.github/workflows/x402-conformance.yml` and set your slug. It runs the full suite on your own code, on loopback with
testnet ids, on every push to your default branch, on every release or tag, and weekly, and on a release signs and
uploads the attestation. Each week the matrix's freshness job (`tools/matrix_freshness.py`) checks your latest release
or tag and default-branch commit against the version tested, verifies the attestation of your newest release run
(tier 2), asks the run queue for a tier-1 rerun of a new release, and opens a pull request updating your row, its
release alignment (current, behind or stale) and your badge. It reads the GitHub API only; it never calls your
endpoints.

## Free run program

For six months from your consent, free: tier-1 external runs of your public testnet endpoint (one initial run, then
one per new release), and verification and listing of your tier-2 attestations. Tier-1 runs are unpaid GETs (and one HEAD only if
you allow it) from outside your stack, with no hosted facilitator, no mainnet and no spend, and the queue never runs your code. Full
tier-1 results go to you privately first. In return your project is listed with its results and displays the badge in
its README with attribution to Optitransfer/x402-conformance. You also install the notify hook,
[templates/x402-conformance-notify.yml](templates/x402-conformance-notify.yml), as
`.github/workflows/x402-conformance-notify.yml`; it runs on release published only, asks for the tier-1 rerun and,
with `X402_CONFORMANCE_FULL_SUITE` set, runs the full suite and submits its attestation. After six months the row stays
listed with its last result, marked stale. Self-runs with the Action above stay free and unlimited. See
[MATRIX.md, Free run program](MATRIX.md#free-run-program).
