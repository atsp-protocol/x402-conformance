# x402 Conformance

**Prove your x402 payments can't double-credit, credit too early or credit on a broken answer, in one CI step.**

[![ci](https://github.com/atsp-protocol/x402-conformance/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/atsp-protocol/x402-conformance/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/atsp-protocol/x402-conformance)](https://github.com/atsp-protocol/x402-conformance/releases/latest)
[![PyPI](https://img.shields.io/pypi/v/x402-conformance?label=PyPI)](https://pypi.org/project/x402-conformance/)
[![npm](https://img.shields.io/npm/v/x402-conformance-svm?label=npm)](https://www.npmjs.com/package/x402-conformance-svm)
[![GitHub Marketplace](https://img.shields.io/badge/Marketplace-x402%20Conformance-blue?logo=github)](https://github.com/marketplace/actions/x402-conformance)
[![licence](https://img.shields.io/github/license/atsp-protocol/x402-conformance)](LICENSE)
[![Tested with x402-conformance](https://img.shields.io/badge/tested%20with-x402--conformance-2ea44f)](https://github.com/atsp-protocol/x402-conformance)

An open set of conformance and safety checks for [x402](https://github.com/x402-foundation/x402) facilitators and
resource servers. It checks the properties a seller's money depends on. It never signs, pays or touches mainnet. It
complements x402 and its facilitators and doesn't replace them.

**Experimental.** Passing a check is evidence about one property. It doesn't certify conformance to x402.
— Ryan Gillespie, Optitransfer

Project page with the checks and the latest results: https://atsp-protocol.github.io/x402-conformance/

## 60-second quickstart

```
pipx run --spec x402-conformance x402conf live https://x402.org/facilitator        # a facilitator's GET /supported
pipx run --spec x402-conformance x402conf resource https://your.api/paid-route      # your 402 answer, one unpaid GET
npx -y x402-conformance-svm probe --resource http://127.0.0.1:4020/paid --start "node server.js"   # fault injection
```

In CI, save this as `.github/workflows/x402-conformance.yml`:

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
          resource-url: http://127.0.0.1:4020/paid   # your paid route
          start: node server.js                      # must use X402_FACILITATOR_URL as its facilitator
```

## Who should use this

- **Resource-server builders** selling an API over x402. The probe puts a misbehaving facilitator in front of your paid
  route and fails your build if you would serve content on a `/settle` timeout, a broken answer, `settlement_pending`,
  an on-chain failure or a duplicate payment. `resource` checks that your 402 answer is well formed on any network.
- **Facilitator operators.** `live` checks your public `GET /supported` (shape, CAIP-2 IDs, Solana fee payers) with one
  GET, and `devnet` runs the safety suite over real `/verify` and `/settle` against a facilitator you run.
- **SDK and middleware maintainers.** Run the probe against your framework's example server in CI. The repo's own CI
  runs it against the stock `@x402/express` middleware on Solana devnet and Base Sepolia.

## What it catches

**Facilitators, live, read-only (`x402conf live`, one `GET /supported` each):**
- **S0** the endpoint doesn't answer HTTP 200 with a JSON object (unreachable, an error page, or credentials needed)
- **S1** the response is missing `kinds`, `extensions` or `signers` (a V1-only facilitator is graded against V1, which defines `kinds` only)
- **S2** a V2 network isn't written as a CAIP-2 ID
- **S3** a Solana kind uses an old V1 name such as `solana-devnet` instead of the published ID
- **S4** a Solana `exact` kind has no valid fee payer (error), or its fee payer isn't listed under `signers` (warning:
  the spec doesn't say it must be, I infer it from what `signers` is for)

**Any paid URL, read-only (`x402conf resource`, one unpaid `GET` each), any network, V1 or V2:**
- **P1** an unpaid request isn't answered with HTTP 402
- **P2** there's no `PAYMENT-REQUIRED` header (V2) or V1 JSON body, or it doesn't decode
- **P3** `x402Version`, `resource` or a non-empty `accepts` is missing
- **P4** an `accepts` entry lacks a required field or has the wrong type (amount in atomic units, CAIP-2 network, timeout)
- **P5** a scheme-specific field is missing: `extra.name` and `extra.version` for EVM `exact` (EIP-3009),
  `extra.feePayer` for Solana `exact`

**Your resource server, under fault injection (`x402conf-svm probe`, R0-R10):** the probe starts a facilitator double
on loopback, points your server at it through `X402_FACILITATOR_URL` and pays your route with test payloads on
**Solana devnet or Base Sepolia (`exact`; EVM via EIP-3009)**. Your server must:
- **R0** answer an unpaid request with a 402 offering one of those networks. If it offers neither, the result is
  **unsupported**, not failed: nothing was graded
- **R1** serve a settled payment, and use the double (if it serves without calling the double, the probe stops: the
  remaining checks would mean nothing)
- **R2** serve the same payment at most once
- **R3-R9** not serve when `/settle` never answers, answers an HTML 502, a 503 with a success body, a non-JSON page, a
  truncated body, `settlement_pending` or `invalid_transaction_state`
- **R10** send a `PAYMENT-RESPONSE` header that decodes to `success: true` with the content

**Safety suite (`x402conf offline` and `devnet`, F1-F9):** a malformed payment accepted (F1), an underpayment accepted
(F2), a payment settled twice (F3), a memo or nonce replayed (F4), success before confirmation (F5), a timeout or
garbage answer credited (F6), a pending payment never finalised or credited twice (F7), a failure stuck pending (F8),
a broken `/settle` transport credited (F9). `offline` runs them against built-in doubles: it's a self-test of the suite
and doesn't test your code. `devnet` runs F1-F6 over real `/verify` and `/settle` on Solana devnet.

[docs/SPEC.md](docs/SPEC.md) quotes the spec text behind every check, and [docs/FIXES.md](docs/FIXES.md) explains, for
every check, what failed, why it matters and how to fix it.

## Install

| how | command | needs |
|---|---|---|
| GitHub Action | `uses: atsp-protocol/x402-conformance@v1` (see [below](#github-action)) | python3 3.10+ on the runner (GitHub-hosted runners have it) |
| Python CLI, one-off | `pipx run --spec x402-conformance x402conf --help` or `uvx --from x402-conformance x402conf --help` | [pipx](https://pipx.pypa.io) or [uv](https://docs.astral.sh/uv/) |
| Python CLI, installed | `pip install x402-conformance` | Python 3.10+, no dependencies |
| TypeScript probe | `npx -y x402-conformance-svm --help` | Node 20+ |

Packages: [x402-conformance on PyPI](https://pypi.org/project/x402-conformance/) (command `x402conf`) and
[x402-conformance-svm on npm](https://www.npmjs.com/package/x402-conformance-svm) (command `x402conf-svm`; the name is
historical, it grades Base Sepolia too). `x402conf --version` and `x402conf-svm --version` print the version. Pin
`x402-conformance==1.3.0`, `x402-conformance-svm@1.3.0` or the Action at `@v1.3.0` if you want a fixed version; `@v1`
follows the latest 1.x release.

## CLI

```
x402conf live https://x402.org/facilitator             # S0-S4, GET /supported only
x402conf resource https://api.example.com/paid         # P1-P5, one unpaid GET
x402conf offline                                       # F1-F9 self-test against the built-in doubles
x402conf report --dir DIR --sarif out.sarif --junit junit.xml
x402conf devnet --faults --keys DIR                    # F1-F6 over real /verify and /settle on Solana devnet
x402conf-svm probe --resource http://127.0.0.1:4020/paid --start "node server.js" --out resource-server.json
```

`live`, `resource` and `offline` print JSON with one entry per check (`check`, `pass`, `severity`, `detail`). Save them
as `live.json`, `resource-402.json` and `offline.json` (and the probe's `--out` as `resource-server.json`) in one
directory, and `report` converts them to SARIF and JUnit, printing a one-line summary such as
`{"checks": 14, "failed": 0, "failed_ids": []}`. Add `--fail-on-error` to `live`, `resource` or `report` to exit 1 when
an error-severity check fails; without it they exit 0 so existing scripts keep working. Warnings never fail a run.

`devnet` runs against a self-hosted reference facilitator on loopback with throwaway keys from `--keys`, and refuses any
other facilitator unless you pass `--operator-permission` with the operator's written permission. It needs Node 20+
and a funded devnet fee payer; [evidence/devnet](evidence/devnet) shows a full run.

**Facilitators that need credentials** (Coinbase CDP, for example): put the full `Authorization` header value in
`X402C_FACILITATOR_AUTHORIZATION` and the facilitator's host name in `X402C_FACILITATOR_AUTH_HOST`. The header goes to
that host only, never to the others in the same run, and is never printed or written to evidence. A credential without
a host is a usage error. CDP uses short-lived JWTs, so mint one just before the run.

**Exit codes.**

| command | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| `x402conf live`, `x402conf resource` | done (with `--fail-on-error`: no error-severity check failed) | with `--fail-on-error`, an error-severity check failed, S0 included | usage or configuration error | – |
| `x402conf offline` | the reference passes every check and every fault-injected double is caught | otherwise | usage error | – |
| `x402conf report` | reports written (with `--fail-on-error`: and nothing failed) | with `--fail-on-error`, an error-severity check failed | usage error, or no results JSON in the directory | – |
| `x402conf devnet` | the facilitator under test passes, and with `--faults` every fault-injected build is caught | otherwise (the current reference exits `1` on F4, see [Results](#results)) | usage error | – |
| `x402conf-svm probe` | R0-R10 all pass | a check failed | usage error, or the run couldn't complete: a port in use, your `--start` server exited or never answered | unsupported: your server offers no network the probe grades |
| `x402conf --help`, `--version`, `x402conf-svm --help`, `--version` | always | – | – | – |

With `--out`, the probe writes its results file on every outcome, errors included.

## GitHub Action

The [quickstart](#60-second-quickstart) workflow runs as is. Inputs:

| input | default | what it does |
|---|---|---|
| `facilitators` | empty | Space-separated facilitator base URLs, checked with `GET /supported` only (S0-S4) |
| `facilitator-auth-host` | empty | The one host that gets `X402C_FACILITATOR_AUTHORIZATION` (set it in the step's `env` from a secret) |
| `resources` | empty | Space-separated paid URLs, one unpaid `GET` each (P1-P5) |
| `resource-url` | empty | Your paid route; the Action puts a facilitator double in front of it and runs R0-R10 |
| `start` | empty | Command that starts your server; it receives `X402_FACILITATOR_URL` |
| `network` | `auto` | Which offered network the probe pays on: `auto`, `solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1` or `eip155:84532` |
| `port` | `4402` | Loopback port for the facilitator double |
| `offline` | `true` | Also run the F1-F9 self-test of the suite (it tests the suite, not your code; set `false` to skip) |
| `results-dir` | `x402-conformance` | Where `live.json`, `resource-402.json`, `resource-server.json` and `offline.json` are written |
| `fail-on-error` | `true` | Fail the job when a check fails, a requested run left no results, or the probe found nothing to grade |

| output | value |
|---|---|
| `result` | `pass` when every requested check passed, `unsupported` when the probe found nothing it could grade, otherwise `fail` |
| `results-dir` | the directory holding the results JSON |
| `sarif` | `<results-dir>/x402-conformance.sarif`, SARIF 2.1.0 of the failed checks |
| `junit` | `<results-dir>/junit.xml`, one test case per check |

**It fails closed.** If the probe can't run (its port is taken, your server exits or never answers, the build fails),
the job fails with the reason; a run that left no results is never reported as a pass. **It leaves your toolchain
alone.** It doesn't run `setup-python` or `setup-node`: the Python checks use the runner's `python3`, and the probe runs
on a pinned, checksum-verified Node in `RUNNER_TEMP` that is never put on your `PATH`, so your server and later steps
keep your Node.

**Example job summary** (abridged):

```
## x402 Conformance: pass
| target                          | check                                                          | result |
| http://127.0.0.1:4020/paid      | R1 a settled payment is served, and the server used the facilitator double | pass |
| http://127.0.0.1:4020/paid      | R3 /settle never answers: content not served (F6)              | pass   |
| https://x402.org/facilitator    | S1 SupportedResponse shape: kinds[], extensions[], signers{} ... | pass |
```

**Failures in code scanning.** Every failed check can show up in your repo's Security tab, with a link to what failed
and how to fix it. Add `permissions: { security-events: write, contents: read }` to the job, `id: x402` and
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

## Results

The full results, with raw bodies and hashes, are on the [project page](https://atsp-protocol.github.io/x402-conformance/#results).

### Live, 2026-10-20, `GET /supported` only, one request per facilitator

| facilitator | HTTP | S0 | S1 | S2 | S3 | S4 | note |
|---|---|---|---|---|---|---|---|
| x402.org/facilitator | 200 | pass | pass | pass | pass | pass | |
| facilitator.payai.network | 200 | pass | pass | pass | pass | pass | |
| x402.dexter.cash | 200 | pass | pass | pass | pass | pass | |
| facilitator.ultravioletadao.xyz | 200 | pass | pass | pass | pass | warning | devnet fee payer not listed under `signers` (inferred rule) |
| pay.openfacilitator.io | 200 | pass | pass | pass | pass | pass | |
| facilitator.xpay.sh | 200 | pass | pass | pass | pass | pass | |
| x402.polygon.technology | 200 | pass | pass | pass | pass | pass | |
| facilitator.goplausible.xyz | 200 | pass | pass | **fail** | pass | pass | Algorand IDs use the full 44-character genesis hash; the x402 Algorand spec uses `algorand:wGHE2Pwdvd7S12BL5FaOP20EGYesN73k` |
| facilitator.pieverse.io | 200 | pass | pass | pass | pass | pass | |
| facilitator.x402.rs | 200 | pass | pass | pass | pass | pass | |
| facilitator.daydreams.systems | 200 | pass | pass | pass | pass | pass | |
| facilitator.mogami.tech | 200 | pass | pass | pass | pass | pass | V1-only, graded against V1 |
| api.cdp.coinbase.com/platform/v2/x402 | 401 | **fail** | – | – | – | – | needs credentials; not run with any |
| facilitator.cascade.fyi | – | **fail** | – | – | – | – | TLS handshake failed |
| facilitator.corbits.dev | – | **fail** | – | – | – | – | TLS handshake failed |

Raw bodies, `run.json` and `SHA256SUMS` for this run are in [evidence/2026-10-20-v1.3.0](evidence/2026-10-20-v1.3.0). A
failed check is evidence about one property on one day, not a verdict on a facilitator; operators can
[report a false positive](https://github.com/atsp-protocol/x402-conformance/issues/new?template=false-positive.yml).

The first run, with 1.2.0, is in [evidence/2026-10-20](evidence/2026-10-20).
Want your facilitator listed? [Open a request](https://github.com/atsp-protocol/x402-conformance/issues/new?template=add-facilitator.yml).

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

If your project runs the suite in CI, you can say so. It means "tested with", not "certified":

```markdown
[![x402 conformance: tested](https://img.shields.io/badge/x402%20conformance-tested-2ea44f)](https://github.com/atsp-protocol/x402-conformance)
```

[![x402 conformance: tested](https://img.shields.io/badge/x402%20conformance-tested-2ea44f)](https://github.com/atsp-protocol/x402-conformance)

## Who uses it

No public users yet. I only list a user once they've said so publicly. If you run it, open an issue or say so in
[Discussions](https://github.com/atsp-protocol/x402-conformance/discussions) and I'll add you here and to
[docs/ADOPTION.md](docs/ADOPTION.md).

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

The suite holds no keys of yours and never signs or pays. `live` and `resource` are GET-only, and that's tested. The
probe's facilitator double listens on loopback only and never touches a chain. A facilitator credential, if you give
one, comes from the environment, goes only to the host you name and is never printed. The devnet runner refuses
mainnet and any third-party facilitator without written permission.

## Security

Please report vulnerabilities through GitHub private vulnerability reporting
([Security → Report a vulnerability](https://github.com/atsp-protocol/x402-conformance/security/advisories/new)), not in
a public issue. When the suite finds a failing safety check in someone else's facilitator, I tell the operator
privately first. The full policy is in [SECURITY.md](SECURITY.md).

## Contributing

Questions and ideas are welcome in [Discussions](https://github.com/atsp-protocol/x402-conformance/discussions).
Issues and pull requests are welcome, and new checks especially: propose one with the check-proposal issue template,
quoting the x402 spec text it rests on. If a check flags something you believe is correct, open a
[false positive report](https://github.com/atsp-protocol/x402-conformance/issues/new?template=false-positive.yml). Every check needs a test that fails against a faulty double and passes against
the reference. [CONTRIBUTING.md](CONTRIBUTING.md) lists the local checks to run before you push, and everyone taking
part follows the [Code of Conduct](CODE_OF_CONDUCT.md). Changes are listed in [CHANGELOG.md](CHANGELOG.md).

## Licence

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE) (Ryan Gillespie / Optitransfer).
