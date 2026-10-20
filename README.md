# x402 Conformance

**Prove your x402 payments can't double-credit, credit too early or credit on a broken answer, in one CI step.**

[![ci](https://github.com/atsp-protocol/x402-conformance/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/atsp-protocol/x402-conformance/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/atsp-protocol/x402-conformance)](https://github.com/atsp-protocol/x402-conformance/releases/latest)
[![GitHub Marketplace](https://img.shields.io/badge/Marketplace-x402%20Conformance-blue?logo=github)](https://github.com/marketplace/actions/x402-conformance)
[![licence](https://img.shields.io/github/license/atsp-protocol/x402-conformance)](LICENSE)
[![Tested with x402-conformance](https://img.shields.io/badge/tested%20with-x402--conformance-2ea44f)](https://github.com/atsp-protocol/x402-conformance)

An open set of conformance and safety checks for [x402](https://github.com/coinbase/x402) V2 facilitators and
resource servers, starting with Solana. It checks the properties a seller's money depends on. It never signs, pays or
touches mainnet. It complements x402 and its facilitators and doesn't replace them.

**Experimental.** Passing a check is evidence about one property. It doesn't certify conformance to x402.
— Ryan Gillespie, Optitransfer

Project page with the checks and the latest results: https://atsp-protocol.github.io/x402-conformance/

## Install

| how | command | needs |
|---|---|---|
| GitHub Action | `uses: atsp-protocol/x402-conformance@v1` (see [below](#github-action)) | nothing |
| Python CLI, one-off | `pipx run --spec "git+https://github.com/atsp-protocol/x402-conformance@v1" x402conf offline` | [pipx](https://pipx.pypa.io) or [uv](https://docs.astral.sh/uv/) |
| Python CLI, installed | `pip install "git+https://github.com/atsp-protocol/x402-conformance@v1"` | Python 3.10+, no dependencies |
| TypeScript runner | `git clone` this repo, then `cd ts && npm ci && npm run build` | Node 20+ |

The packages aren't on PyPI (`x402-conformance`) or npm (`x402-conformance-svm`) yet, so `pip install x402-conformance`
and `npx x402conf-svm` don't work today. Install from the release tag as shown. `@v1` follows the latest 1.x release;
pin `@v1.2.0` if you want a fixed version.

## Quickstart

```
pipx run --spec "git+https://github.com/atsp-protocol/x402-conformance@v1" x402conf offline
uvx --from "git+https://github.com/atsp-protocol/x402-conformance@v1" x402conf live https://x402.org/facilitator
```

The first runs the F1-F9 safety suite against the built-in reference and fault-injected facilitator doubles. The
second reads `GET /supported` from a facilitator and runs S1-S4. Both print JSON.

## GitHub Action

Save this as `.github/workflows/x402-conformance.yml`. It runs as is:

```yaml
name: x402 conformance
on: [push, pull_request]
jobs:
  x402:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: atsp-protocol/x402-conformance@v1
        with:
          facilitators: https://x402.org/facilitator   # swap in your facilitator; GET /supported only
```

With no inputs it runs only the F1-F9 safety suite. `facilitators` adds the live `GET /supported` checks. To test
your own resource server, point the Action at your paid route and give it the command that starts the server:

```yaml
      - uses: atsp-protocol/x402-conformance@v1
        with:
          resource-url: http://127.0.0.1:4020/paid
          start: node server.js            # your server must use X402_FACILITATOR_URL as its facilitator
```

| input | default | what it does |
|---|---|---|
| `facilitators` | empty | Space-separated facilitator base URLs, checked with `GET /supported` only (S1-S4) |
| `resource-url` | empty | Your paid route; the Action puts a facilitator double in front of it and runs R0-R9 |
| `start` | empty | Command that starts your server; it receives `X402_FACILITATOR_URL` |
| `port` | `4402` | Loopback port for the facilitator double |
| `offline` | `true` | Run the F1-F9 suite against the reference and fault-injected doubles |
| `results-dir` | `x402-conformance` | Where `live.json`, `resource-server.json` and `offline.json` are written |
| `fail-on-error` | `true` | Fail the job when any error-severity check fails |

| output | value |
|---|---|
| `result` | `pass` when every requested check passed, otherwise `fail` |
| `results-dir` | the directory holding the results JSON |
| `sarif` | `<results-dir>/x402-conformance.sarif`, SARIF 2.1.0 of the failed checks |
| `junit` | `<results-dir>/junit.xml`, one test case per check |

**Example job summary** (abridged):

```
## x402 Conformance: pass
| target                       | check                                                         | result |
| https://x402.org/facilitator | S1 SupportedResponse shape: kinds[], extensions[], signers{}  | pass   |
| https://x402.org/facilitator | S4 Solana exact kinds advertise a valid extra.feePayer ...    | pass   |
| reference double             | F3 the same payload settled twice succeeds at most once ...   | pass   |
| reference double             | F9 a 503, non-JSON or truncated /settle answer is never ...   | pass   |
| fault-injected doubles       | every fault caught by at least one check                      | pass   |
```

**Failures in code scanning.** Every failed check can show up in your repo's Security tab, with a link to what
failed and how to fix it. Add `permissions: { security-events: write, contents: read }` to the job, `id: x402` and
`fail-on-error: false` to the step above, then:

```yaml
      - uses: github/codeql-action/upload-sarif@v3
        if: always()
        with:
          sarif_file: ${{ steps.x402.outputs.sarif }}
          category: x402-conformance
      - run: test "${{ steps.x402.outputs.result }}" = pass
```

The `junit` output works with any JUnit test-report viewer.

## CLI

```
x402conf live https://x402.org/facilitator     # S1-S4, GET /supported only
x402conf offline                               # F1-F9 against the reference and fault-injected doubles
x402conf report --dir DIR --sarif out.sarif --junit junit.xml
x402conf devnet --faults --keys DIR            # F1-F6 over real /verify and /settle on Solana devnet
```

`live` and `offline` print JSON with one entry per check (`check`, `pass`, `severity`, `detail`). Save them as
`live.json` and `offline.json` in one directory and `report` converts them to SARIF and JUnit, printing a one-line
summary such as `{"checks": 14, "failed": 0, "failed_ids": []}`. `devnet` runs against a self-hosted reference
facilitator on loopback with throwaway keys from `--keys`, and refuses any other facilitator unless you pass
`--operator-permission` with the operator's written permission. It needs Node 20+ and a funded devnet fee payer;
[evidence/devnet](evidence/devnet) shows a full run.

**Exit codes.**

| command | 0 | non-zero |
|---|---|---|
| `x402conf offline` | the reference double passes every check and every fault-injected double is caught | `1` otherwise |
| `x402conf live` | always, even when a check fails or the facilitator can't be reached | read the `pass` fields, or use the Action, which does |
| `x402conf report` | the reports were written | `2` when the directory holds no results JSON |
| `x402conf devnet` | the facilitator under test passes every check, and with `--faults` every fault-injected build is caught | `1` otherwise (the current reference exits `1` on F4, see [Results](#results)) |
| `x402conf-svm probe` (TypeScript) | R0-R9 all pass | `1` when a check fails, `2` on an error |

Usage errors exit `2`.

**TypeScript runner** for resource servers on `@x402/core` and `@x402/svm`, from a clone of this repo:

```
cd ts && npm ci && npm run build
node dist/src/cli.js probe --resource http://127.0.0.1:4020/paid --start "node your-server.js" --out results.json
```

[ts/README.md](ts/README.md) explains what the double does for each of R0-R9.

## What it catches

**Live, read-only (`GET /supported`):**
- **S1** the response is missing `kinds`, `extensions` or `signers`
- **S2** a V2 network isn't written as a CAIP-2 ID
- **S3** a Solana kind uses an old V1 name such as `solana-devnet` instead of the published ID
- **S4** a Solana `exact` kind has no valid fee payer, or one that isn't a listed signer

**Safety, against doubles, on devnet and in your resource server:**
- **F1** a malformed payment is accepted instead of rejected
- **F2** an underpayment or dust amount is accepted
- **F3** the same payment is settled, or served, twice
- **F4** a used memo or nonce is replayed in a new transaction
- **F5** a payment counts as settled before it's confirmed, or `settlement_pending` comes without a transaction
- **F6** a facilitator timeout or garbage answer turns into a credit
- **F7** a pending payment retried with the same body never reaches its final result, or is credited more than once
- **F8** a payment that failed on chain stays "pending" instead of failing
- **F9** a 503, an HTML page or a truncated `/settle` answer is credited, or the payment can't be retried afterwards

**Resource servers (R0-R9).** The TypeScript runner puts a facilitator double in front of your server and requests your
paid route under each of the faults above. Your server must answer an unpaid request with a 402 and must not serve
content on a timeout, a broken `/settle` answer, `settlement_pending`, a failure or a duplicate.

[docs/SPEC.md](docs/SPEC.md) quotes the spec text behind every check, and [docs/FIXES.md](docs/FIXES.md) explains, for
every check, what failed, why it matters and how to fix it.

## Results

### Live, 2026-10-20, `GET /supported` only

| facilitator | HTTP | S1 | S2 | S3 | S4 | Solana kinds advertised |
|---|---|---|---|---|---|---|
| x402.dexter.cash | 200 | pass | pass | pass | pass | exact (mainnet, devnet), tab, bridge |
| facilitator.payai.network | 200 | pass | pass | pass | pass | exact and batch-settlement (mainnet, devnet) |
| x402.org/facilitator | 200 | pass | pass | pass | pass | exact (devnet) |

Raw bodies, `run.json` and `SHA256SUMS` are in [evidence/2026-10-20](evidence/2026-10-20).

### Devnet, 2026-10-20, F1-F6 over real `/verify` and `/settle`

I ran F1 to F6 on Solana devnet against my self-hosted reference facilitator (`@x402/core` and `@x402/svm` 2.28.0),
then against fault-injected builds of it.

| facilitator | F1 | F2 | F3 | F4 | F5 | F6 |
|---|---|---|---|---|---|---|
| self-hosted reference, `@x402/svm` 2.28.0 | pass | pass | pass | **fail** | pass | pass |

F4 fails because the reference facilitator deduplicates by transaction but not by memo, so two different
transactions with the same memo both settled. The payer paid twice, so the seller lost nothing, but a resource server
that ties one purchase to one memo has to enforce that itself. Every fault-injected build was caught by the check
it targets. Transaction links, the full `run.json` and its hash are in [evidence/devnet](evidence/devnet). Results for
other facilitators go in the [facilitator matrix](docs/MATRIX.md), and I run them against a third party only with the
operator's permission.

## How this repo is verified

Scope and acceptance criteria live in [`proofline.json`](proofline.json), a [Proofline](https://github.com/Optitransfer/proofline)
contract. It's signed with my owner key: the signature is in `proofline.json.sig` and the public key is pinned in
[`guard/owner.pub`](guard/owner.pub). On every push to `main` and on every pull request, CI checks that signature and then runs `tools/vv.py`, which checks
every acceptance criterion and uploads a receipt ([docs/VV.md](docs/VV.md)). Any change to the contract has to be
re-signed before CI passes again. You can check the signature yourself from a clone:

```
node tools/verify-sig.mjs                                       # no dependencies; exits 0 when the signature matches
npx -y @optitransfer/proofline@next contract verify-sig         # the Proofline CLI (Node 22+), same check
```

The Lean 4 models in [`lean/`](lean) cover the credit rule, nonces, timeouts, `settlement_pending` reconciliation and
concurrent settles. They use only standard axioms and contain no `sorry`. They model the rule the suite checks, not any
facilitator's code.

## Add the badge

If your project runs the suite in CI, add this to your README:

```markdown
[![Tested with x402-conformance](https://img.shields.io/badge/tested%20with-x402--conformance-2ea44f)](https://github.com/atsp-protocol/x402-conformance)
```

## Who uses it

No public users yet. I only list a user once they've said so publicly. If you run it, open an issue and I'll add you
here and to [docs/ADOPTION.md](docs/ADOPTION.md).

**Free run for your project.** Open an issue with your repo or facilitator URL and I'll run the suite against it,
post the results, and send a tests-only pull request with the Action and badge. It's free, with no conditions.

## Managed services

The core is free and stays free. If you'd rather not run it yourself, or you need more than the open suite, I offer:
- **Hosted continuous monitoring** of your live endpoints, with alerts on regressions
- **Signed conformance reports** for each release, with a public verify link
- **Custom checks** for your scheme, chain or extensions
- **Priority support** with an agreed response time

The first three customers get design-partner pricing. Monitoring is a monthly subscription, reports are priced per
release, and custom checks are fixed-scope work quoted up front. Details are in [docs/MANAGED.md](docs/MANAGED.md). To get
in touch, open a [Managed services enquiry](https://github.com/atsp-protocol/x402-conformance/issues/new?template=managed-services.yml)
or email data@optitransfer.ch.

## Safety

The suite holds no keys of yours and never signs or pays. Live mode is GET-only, and that's tested. The devnet
runner refuses mainnet and any third-party facilitator without written permission.

## Security

Please report vulnerabilities through GitHub private vulnerability reporting
([Security → Report a vulnerability](https://github.com/atsp-protocol/x402-conformance/security/advisories/new)), not in
a public issue. When the suite finds a failing safety check in someone else's facilitator, I tell the operator
privately first. The full policy is in [SECURITY.md](SECURITY.md).

## Contributing

Issues and pull requests are welcome, and new checks especially. Propose one with the check-proposal issue template,
quoting the x402 spec text it rests on. Every check needs a test that fails against a faulty double and passes against
the reference. [CONTRIBUTING.md](CONTRIBUTING.md) lists the local checks to run before you push, and everyone taking
part follows the [Code of Conduct](CODE_OF_CONDUCT.md). Changes are listed in [CHANGELOG.md](CHANGELOG.md).

## Licence

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE) (Ryan Gillespie / Optitransfer).
