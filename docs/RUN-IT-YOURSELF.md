# Run it yourself

Facilitators, SDKs, merchants and vendors can run x402-conformance on their own code and put the result in the
[matrix](MATRIX.md) themselves. Run it on your own testnet or devnet endpoint, or on a local build. Never run it on
mainnet, and never against a facilitator you don't operate. Nothing here pays, and the live checks are GET-only.

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

The job summary lists every check and ends with the "Tested with x402-conformance" line and the version. The
`evidence` and `row` inputs come with the first release after 1.6.0; until then use `@main`.

## MCP

In any MCP client, add the server and ask it to check your endpoint:

<!-- runnable: json -->
```json
{ "mcpServers": { "x402-conformance": { "command": "npx", "args": ["-y", "x402-conformance-mcp"] } } }
```

See [USING.md](USING.md) for the tools it offers.

## Get listed or update your row

1. Run it with the Action's evidence mode, or keep the `run.json` from the CLI.
2. Open the [Add or update my row](https://github.com/atsp-protocol/x402-conformance/issues/new?template=add-or-update-row.yml)
   form: entity name, type, languages, networks, environment, endpoint, version or commit, contact, and your consent
   to be listed.
3. Open a PR that adds the bundle as `evidence/impl-matrix/<row>/`, then run `python3 tools/compat_matrix.py --write`.
   Or link the artifact in the issue and I'll open the PR. CI rebuilds the row and its badge from the evidence.

Your row shows the environment, checks passed out of checks run, the failed count, the version tested and the run date
with a link to the evidence. It never shows a score or a rank. If a check fails, I tell you privately first
(SECURITY.md). Once your row is listed you can embed its badge ([BADGE.md](BADGE.md)). The public results are CC BY 4.0
([DATA-LICENSE](../DATA-LICENSE)).

Is a check missing? Propose one with the
[check proposal](https://github.com/atsp-protocol/x402-conformance/issues/new?template=check-proposal.yml) form.
