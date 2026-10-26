# x402 Conformance

**Prove your x402 payments can't double-credit, credit too early or credit on a broken answer, in one CI step.**

[![ci](https://github.com/atsp-protocol/x402-conformance/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/atsp-protocol/x402-conformance/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/atsp-protocol/x402-conformance?cacheSeconds=3600)](https://github.com/atsp-protocol/x402-conformance/releases/latest)
[![PyPI](https://img.shields.io/pypi/v/x402-conformance?label=PyPI&cacheSeconds=3600)](https://pypi.org/project/x402-conformance/)
[![npm](https://img.shields.io/npm/v/x402-conformance-svm?label=npm&cacheSeconds=3600)](https://www.npmjs.com/package/x402-conformance-svm)
[![GitHub Marketplace](https://img.shields.io/badge/Marketplace-x402%20Conformance-blue?logo=github)](https://github.com/marketplace/actions/x402-conformance)
[![licence](https://img.shields.io/github/license/atsp-protocol/x402-conformance)](LICENSE)
[![Tested with x402-conformance](https://img.shields.io/badge/tested%20with-x402--conformance-2ea44f)](https://github.com/atsp-protocol/x402-conformance)

An open set of conformance and safety checks for [x402](https://github.com/x402-foundation/x402) facilitators and
resource servers. It checks the properties a seller's money depends on. It never signs, pays or touches mainnet. It
complements x402 and its facilitators and doesn't replace them.

**Experimental.** Passing a check is evidence about one property. It doesn't certify conformance to x402.
— Ryan Gillespie, Optitransfer

Project page with the checks and the latest results: https://atsp-protocol.github.io/x402-conformance/
Release map: [RELEASES.md](RELEASES.md). What the suite covers, check by check: [docs/COVERAGE.md](docs/COVERAGE.md).

<!-- docs-aligned:counts -->
The catalogue has 79 checks in 11 families: 41 normative, 24 security profile and 14 resilience ([docs/COVERAGE.md](docs/COVERAGE.md)). The contract, `proofline.json`, has 106 tasks and 742 acceptance criteria; 46 tasks are claimed done, and CI holds each of them to every criterion ([docs/VV.md](docs/VV.md)).
<!-- /docs-aligned:counts -->

## 60-second quickstart

See it work first, with nothing to set up: no project, no wallet, no chain, a few seconds each.

```
npx -y x402-conformance-svm demo                       # R0-R10 against a bundled mock server behind a facilitator double
pipx run --spec x402-conformance x402conf demo         # S1-S4, P1-P7 against a bundled mock, then the F1-F14 and S5 self-test
npx -y x402-conformance-svm demo --fault serve_on_any_settle   # what a failure looks like, with a fix link per check
```

Then point it at your own code:

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

**From your test suite, agent or CI system:** [docs/USING.md](docs/USING.md) covers vitest, jest, node:test, Hono,
Express, pytest (FastAPI, Flask), MCP clients (Claude, Cursor), the Vercel AI SDK, LangChain, Docker and GitLab CI, with the same checks and
report everywhere. Failures you choose to share build the public
[corpus](corpus) of real x402 failures.

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
- **P6** the `PAYMENT-REQUIRED` header is over 8 KB (warning) or 16 KB (error): common proxies and servers reject
  headers that large
- **P7** an offer whose scheme defaults to a non-authorization flow (`upto` on Solana) doesn't declare
  `extra.paymentFlow` (warning; V2 §6.1 says it must, the upto SVM scheme text says it may be omitted)
- **P9** the bazaar discovery `info` in the 402 (the `info.input` example) doesn't validate against the `schema` that
  ships with it, so a catalog that validates it may skip the listing (only when the 402 carries the extension)
- **P10** with `--well-known`: the host's `/.well-known/x402` doesn't list the paid URL, lists URLs off its own host,
  or declares terms no live offer matches (warning; one extra `GET` per origin)

Live targets are paced: at least 5 s between requests to a non-loopback host (`--min-interval`), an optional cap on the
whole run (`--max-requests`), and one line per request on stderr. `x402conf-svm live --url <paid-url>` adds R16a and
R24 to P1-P7 against a server you may test, unpaid, in 7 requests; `x402conf resource --malformed-header --unpaid-head`
does the same in Python. HEAD is not a GET, so off loopback R16a runs only with `--operator-permission <ref>` (the
operator's written permission) and is skipped without it. `x402conf-svm mcp --url <mcp-endpoint> --tool <name>`
calls a paid MCP tool once, unpaid, and grades X1 and P3-P5 and P7 on the offer in its result (`--no-initialize` for a
server that needs no session: one request).

**Your resource server, under fault injection (`x402conf-svm probe`, R0-R11, R14 and R20):** the probe starts a facilitator double
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
- **R11** bind each payment to the request it pays for (give the routes with the binding options): a payment for a
  cheap route is refused on a dearer one (R11a), an altered `payTo`, asset or network is refused before `/settle`
  (R11b), a payment for the cheaper method (R11c) or query (R11d) is refused on the dearer one, an encoded separator
  or dot segment in a parameter never reaches a paid handler unpaid (R11e), and sign-in-with-x access is recorded for
  the route that was priced and settled, not the client's `resource.url` (R11f)
- **R14** survive a crash between a successful `/settle` and the response (add `--crash`): the probe kills your server
  while `/settle` is answering and again as the response starts, restarts it and presents the same payment. It must
  not settle again or ask for payment again, and must either deliver once (from an idempotency record) or refuse and
  name the transaction or payment id so it can be reconciled. With `--start` the probe restarts that command; for a
  server it didn't start, give `--crash-kill` and `--crash-restart`
- **R20** with `--retry`, never charge one request twice when the client times out before `/settle` answers and
  retries: a retry with a fresh payment under the same payment-identifier id is not settled again (R20a), and a retry
  resending the same signed payment is refused as a duplicate by `/settle`; both get the earlier result (R20b). The
  same check grades a client's own retry (`checkClientRetry`): it must resend the payment or keep the payment id

**Your resource server and client, from code (new in 1.5.0, R17 to R19 in 1.6.0):** these checks are functions that
`x402-conformance-svm` exports. The CLIs, the Action, `runConformance`, the pytest plugin and the MCP server don't run
them. Start the facilitator double with `startDouble()`, point your server or client at its `url` and pass the double
to each check ([docs/USING.md](docs/USING.md#checks-you-call-from-code) has an example). Your server must:
- **R12** settle one payment-identifier id once when eight requests carry it at the same time, each with a fresh
  payment, and serve no response that doesn't name that settlement (`probeParallel`)
- **R13** settle one payment-identifier id once across two replicas: sent to one, then the other, then both at once
  (`probeReplicas`)
- **R15** not settle or send a `PAYMENT-RESPONSE` when the paid handler answers 5xx, redirects or throws
  (`probeDelivery`)
- **R16** not settle a paid `HEAD`: no 2xx, no `/settle` call and no `PAYMENT-RESPONSE` (`probeHead`)
- **R16a** never let an unpaid `HEAD` reach the handler: answer it with the same 402 and `PAYMENT-REQUIRED` offer as
  `GET`, or refuse it with 405 (`probeUnpaidHead`, which needs no double)
- **R17** mark the paid response `private` or `no-store`, or vary it on the payment header, so a shared cache in front
  of the route never serves the paid content to an unpaid request (`probeCacheLeak`)
- **R18** never serve while a settlement is pending, late or unanswered, serve once after it is final, and name the
  transaction on every refusal (`probePending`)
- **R19** on an `upfront` or `escrow` offer, settle before the resource executes, and reject a flow it doesn't support
  (`probeFlows`)
- **R21** on a Base Sepolia offer that uses Permit2, serve only on its own successful settle: never on a settlement a
  third party made first with the same signature, and never a second time for a spent payment (`probePreempt`)
- **R22** keep the handler's 2xx status and headers on the paid response: a 201 stays a 201 with its `Location`, and a
  202 stays a 202 with its `Content-Location` (`probeStatus`)
- **R23** not charge a client that disconnects while `/settle` is in flight, or charge it once and give a resend of the
  same payment the settled result (`probeAbort`)
- **R24** answer five malformed `PAYMENT-SIGNATURE` values (not base64, not JSON or not an object) with 402 or 400 and
  a structured error, never a 5xx, a dropped connection or the content (`probeMalformedHeader`)

On a paid route that declares sign-in-with-x (unreleased), your server must (`probeSiwx`):
- **W1** check the message's `domain` and `uri` against its configured public origin, never against `Host` or
  `X-Forwarded-Host`
- **W2** let one signed message in once: a nonce it has seen is refused
- **W3** refuse a message whose `issuedAt` is over five minutes old or in the future, or whose `expirationTime` has
  passed

Your client must:
- **C1** never hand a 402 to its caller as a success: pay and get a 2xx, or reject with an error
  (`checkClientHandles402`)
- **C2** given several offers, pay one on its configured networks and within its maximum, not the first, and never sign
  for a network outside its set (`checkClientOfferPolicy`)
- **C3** pay with `PAYMENT-SIGNATURE` at `x402Version` 2 when the 402 also carries a V1 body, and never fall back to V1
  (`checkClientKeepsV2`)

A client that has no payment path by design (it hands a 402 back to its caller as an error) is graded **not
applicable** on C2 and C3 when you pass `{ signsPayments: false }` and it signs nothing; the report lists it under
`summary.not_applicable` and it does not fail the run.

On the `upto` and `batch-settlement` schemes (unreleased), your server must:
- **U1** never settle more than the maximum the client signed, whatever the metered usage (`probeUpto`)
- **U2** report the amount it settled in `PAYMENT-RESPONSE` (`probeUpto`)
- **U3** declare only a payment flow `upto` allows on its network, never `upfront` (`probeUpto`)
- **B1** serve each `batch-settlement` commitment once, with its commitment identifier and a charge within the
  per-request amount, and refuse a voucher it has already been paid with (`probeBatch`)
- **B2** claim each channel once per redemption run, at its latest voucher (`probeBatch`)
- **B3** report a partly failed redemption run per channel, and claim only the failed channels again (`probeBatch`)

Your facilitator's discovery API and your A2A agent (unreleased) must:
- **D1** answer `/discovery/resources` and `/discovery/search` in the V2 section 8 shapes, every item complete, and
  honour `limit` and the `network` filter (`checkDiscovery`, GET only, no double)
- **G1** answer an unpaid A2A `message/send` with an `input-required` task whose `x402.payment.required` asks for the
  same offers as the HTTP route's 402 (`checkA2aMirrorsHttp`, which sends no payment)

Your paid MCP tools (unreleased), over Streamable HTTP, must:
- **X1** answer an unpaid call with a tool result, not a JSON-RPC error: `isError: true`, the `PaymentRequired` object
  in `structuredContent` and the same JSON in `content[0].text` (`checkMcpPaymentRequired`, which sends no payment and
  needs no double)
- **X2** return the tool's result only on a final first-time settle, with `_meta["x402/payment-response"]`, and nothing
  on a `/settle` timeout, a broken answer, `settlement_pending`, a failed settle or a duplicate (`probeMcpTransport`)

Every result carries its **profile** (`normative`: the spec says MUST; `security-profile`: a hardening rule the spec
leaves open; `resilience`: behaviour under failure), its spec **basis** and a **fix** link (results format
`x402-conformance-evidence/2`).

**Safety suite (`x402conf offline` and `devnet`, F1-F14 and S5):** a malformed payment accepted (F1), an underpayment
accepted (F2), a payment settled twice (F3), a memo or nonce replayed (F4), success before confirmation, or
`settlement_pending` without a transaction and network (F5), a timeout or garbage answer credited (F6), a pending
payment never finalised or credited twice (F7), a failure stuck pending (F8), a broken `/settle` transport credited
(F9), a payment accepted under requirements it wasn't made for (F10), `/verify` committing payment state (F11),
`/verify` accepting, or refusing without a reason, a payment on a network the facilitator doesn't advertise or in an
asset with no token contract (F12), a payment in a different asset at the quoted amount and recipient accepted (F13), a
payment authorized for another network accepted when amount, recipient and asset match (F14), and a facilitator whose
`/supported` lists no kinds, or a listed kind that `/verify` answers with an exception or with `isValid: false` and no
`invalidReason` (S5). F13 and F14 are new in 1.6.0, F12 and S5 in 1.5.0. `offline` runs them against built-in doubles:
it's a self-test of the suite and doesn't test your code. `devnet` runs F1-F6 over real `/verify` and `/settle` on
Solana devnet.

[docs/SPEC.md](docs/SPEC.md) quotes the spec text behind every check, and [docs/FIXES.md](docs/FIXES.md) explains, for
every check, what failed, why it matters and how to fix it.

## Install

| how | command | needs |
|---|---|---|
| GitHub Action | `uses: atsp-protocol/x402-conformance@v1` (see [below](#github-action)) | python3 3.10+ on the runner (GitHub-hosted runners have it) |
| Python CLI, one-off | `pipx run --spec x402-conformance x402conf --help` or `uvx --from x402-conformance x402conf --help` | [pipx](https://pipx.pypa.io) or [uv](https://docs.astral.sh/uv/) |
| Python CLI, installed | `pip install x402-conformance` | Python 3.10+, no dependencies |
| TypeScript probe | `npx -y x402-conformance-svm --help` | Node 20+ |
| pytest plugin | `pip install x402-conformance pytest` (the `x402` fixture, see [docs/USING.md](docs/USING.md#pytest-fastapi-flask-and-any-python-server)) | Python 3.10+; `x402.probe` also needs Node 20+ |
| MCP server | `npx -y x402-conformance-mcp` | Node 20+ |

Packages: [x402-conformance on PyPI](https://pypi.org/project/x402-conformance/) (command `x402conf`) and
[x402-conformance-svm on npm](https://www.npmjs.com/package/x402-conformance-svm) (command `x402conf-svm`; the name is
historical, it grades Base Sepolia too). `x402conf --version` and `x402conf-svm --version` print the version.

<!-- docs-aligned:pins -->
Pin `x402-conformance==1.6.0`, `x402-conformance-svm@1.6.0` or the Action at `@v1.6.0` if you want a fixed version; `@v1` follows the latest 1.x release.
<!-- /docs-aligned:pins -->

## CLI

```
x402conf demo [--fault no_fee_payer|no_402] [--dir DIR] # a bundled mock on loopback, then the self-test
x402conf live https://x402.org/facilitator             # S0-S4, GET /supported only
x402conf resource https://api.example.com/paid         # P1-P7, one unpaid GET
x402conf offline                                       # F1-F14 and S5 self-test against the built-in doubles
x402conf report --dir DIR --sarif out.sarif --junit junit.xml --badge badge.json
x402conf pr-comment DIR/pr-comment.md                  # sticky PR comment (GITHUB_TOKEN, in a pull_request run)
x402conf devnet --faults --keys DIR                    # F1-F6 over real /verify and /settle on Solana devnet
x402conf-svm demo [--fault serve_on_any_settle] [--out file] # R0-R10 against a bundled mock server
x402conf-svm probe --resource http://127.0.0.1:4020/paid --start "node server.js" --out resource-server.json
x402conf-svm probe --resource http://127.0.0.1:4020/paid --start "node server.js" --crash   # R0-R10, then R14
```

`live`, `resource` and `offline` print JSON with one entry per check (`check`, `pass`, `severity`, `detail`). Save them
as `live.json`, `resource-402.json` and `offline.json` (and the probe's `--out` as `resource-server.json`) in one
directory, and `report` converts them to SARIF and JUnit, printing a one-line summary such as
`{"checks": 14, "failed": 0, "failed_ids": []}`. Add `--fail-on-error` to `live`, `resource` or `report` to exit 1 when
an error-severity check fails; without it they exit 0 so existing scripts keep working. Warnings never fail a run.

`devnet` runs against a self-hosted reference facilitator on loopback with throwaway keys from `--keys`, and refuses any
other facilitator (`--facilitator URL`) unless you pass `--operator-permission` with the operator's written permission.
`--rpc` picks the devnet RPC (default `https://api.devnet.solana.com`). It needs Node 20+ and a funded devnet fee payer;
[evidence/devnet](evidence/devnet) shows a full run. `live --evidence DIR` and `devnet --evidence DIR` also write the raw
bodies, `run.json` and `SHA256SUMS` to `DIR`.

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
| `x402conf-svm probe` | every requested check (R0-R10, R11, R14, R20) passes | a check failed | usage error, or the run couldn't complete: a port in use, your `--start` server exited or never answered | unsupported: your server offers no network the probe grades |
| `x402conf --help`, `--version`, `x402conf-svm --help`, `--version` | always | – | – | – |

With `--out`, the probe writes its results file on every outcome, errors included.

## GitHub Action

The [quickstart](#60-second-quickstart) workflow runs as is. Inputs:

| input | default | what it does |
|---|---|---|
| `facilitators` | empty | Space-separated facilitator base URLs, checked with `GET /supported` only (S0-S4) |
| `facilitator-auth-host` | empty | The one host that gets `X402C_FACILITATOR_AUTHORIZATION` (set it in the step's `env` from a secret) |
| `resources` | empty | Space-separated paid URLs, one unpaid `GET` each (P1-P7) |
| `resource-url` | empty | Your paid route; the Action puts a facilitator double in front of it and runs R0-R10 |
| `binding-cheap-url`, `binding-expensive-url` | empty | Two paid routes at different prices (R11, R11a, R11b) |
| `binding-method-url` | empty | A paid URL priced differently for `GET` and `POST` (R11c) |
| `binding-query-urls` | empty | Two paid URLs that differ only in the query, comma-separated (R11d) |
| `binding-param-url` | empty | A paid parameterised route with `{id}` for the parameter (R11e) |
| `binding-siwx-urls` | empty | Two paid sign-in-with-x routes, cheap first, comma-separated, Base Sepolia (R11f) |
| `crash` | `false` | `true` also runs R14: the probe kills your server after `/settle` succeeds and before the response, restarts it and presents the same payment (needs `resource-url`, and `start` or the two commands below) |
| `crash-kill`, `crash-restart` | empty | For a server `start` didn't launch: a command that kills it hard and returns once it's gone, and one that starts it again in the background (R14) |
| `retry` | `false` | `true` also checks R20 retry double-pay on `resource-url` (`--retry`) |
| `start` | empty | Command that starts your server; it receives `X402_FACILITATOR_URL` |
| `network` | `auto` | Which offered network the probe pays on: `auto`, `solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1` or `eip155:84532` |
| `port` | `4402` | Loopback port for the facilitator double |
| `offline` | `true` | Also run the F1-F14 and S5 self-test of the suite (it tests the suite, not your code; set `false` to skip) |
| `results-dir` | `x402-conformance` | Where `live.json`, `resource-402.json`, `resource-server.json` and `offline.json` are written |
| `fail-on-error` | `true` | Fail the job when a check fails, a requested run left no results, or the probe found nothing to grade |
| `pr-comment` | `false` | `true` posts one sticky pull request comment with the result and a fix link per failed check (needs `permissions: { pull-requests: write }`) |
| `github-token` | the job token | Token used for `pr-comment`; the default job token is enough |
| `evidence` | `false` | `true` writes the run as one matrix row's evidence bundle (`run.json`, a README and `SHA256SUMS`) in `<results-dir>/evidence-bundle/<row>` and uploads it as an artifact; testnet and devnet only, a mainnet network is refused before any request ([docs/RUN-IT-YOURSELF.md](docs/RUN-IT-YOURSELF.md)) |
| `row` | empty | The matrix row name for `evidence` and `attest`, for example `myserver-1.2.0` |
| `evidence-upload` | `true` | `false` keeps the evidence bundle in the `evidence-dir` output without uploading it |
| `attest` | `false` | `true` writes and signs (GitHub artifact attestations) an attestation of a full run for the matrix's tier 2, Full suite (self-hosted); run it on a tag, with `row` set and `permissions: { id-token: write, attestations: write, contents: read }` |
| `not-applicable` | empty | With `attest`, the checks that don't apply to your project and why, as `<check id>: <reason>` separated by `;` or new lines |

| output | value |
|---|---|
| `result` | `pass` when every requested check passed, `unsupported` when the probe found nothing it could grade, otherwise `fail` |
| `results-dir` | the directory holding the results JSON |
| `badge` | `<results-dir>/badge.json`, a shields.io endpoint badge |
| `pr-comment` | `<results-dir>/pr-comment.md`, the sticky comment body |
| `sarif` | `<results-dir>/x402-conformance.sarif`, SARIF 2.1.0 of the failed checks |
| `junit` | `<results-dir>/junit.xml`, one test case per check |
| `evidence-dir` | with `evidence: true`, the directory holding the row's evidence bundle |
| `attestation` | with `attest: true`, the path of `x402-conformance-attestation.json` (signed and uploaded as an artifact) |

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

**A comment on the pull request.** Set `pr-comment: "true"` and give the job `permissions: { pull-requests: write }`.
The action posts one comment with the result and a fix link for each failed check, and updates that same comment on
every push instead of adding new ones. It's off by default; on a fork's pull request the token can't comment, so it
only warns.

## Results

The full results, with raw bodies and hashes, are on the [project page](https://atsp-protocol.github.io/x402-conformance/#results).

### Live, 2026-10-20, `GET /supported` only, one request per facilitator

| facilitator | HTTP | S0 | S1 | S2 | S3 | S4 | note |
|---|---|---|---|---|---|---|---|
| x402.org/facilitator | 200 | pass | pass | pass | pass | pass | |
| facilitator.payai.network | 200 | pass | pass | pass | pass | pass | |
| x402.dexter.cash | 200 | pass | pass | pass | pass | pass | |
| facilitator.ultravioletadao.xyz | 200 | pass | pass | pass | pass | warning | devnet fee payer not listed under `signers` (inferred rule) |
| facilitator-A (name withheld) | 200 | pass | pass | pass | pass | pass | |
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
other facilitators go in the [matrix](docs/MATRIX.md), which is opt-in: a project is listed only after it accepts, and I
run the suite against a third party only with the operator's permission. Verify-only F checks against open-source
facilitators built at a pinned commit and run on loopback as my own instance are signed as XC-51 and not built yet.

## Roadmap

Depth first, then breadth. 1.4.0 (2026-10-22) tests that a payment for one route, price, recipient or method never
unlocks another, on a real resource server rather than only on the facilitator double (R11), adds a crash between
settling and serving (R14) and retry double-pay (R20), and makes the suite's own oracle fail closed on malformed
amounts. 1.5.0 (2026-10-23) adds parallel and multi-replica replay (R12, R13), payment versus delivery (failed handlers
R15, `HEAD` R16 and R16a, the paid 2xx status R22), a client abort during settle (R23), malformed payment headers (R24),
three client checks (C1-C3), and a `/verify` answer for every advertised kind (S5) and for an unsupported network or
asset (F12), with the n-replica Lean models (`Replicas.lean`) and the R20 corpus case. 1.6.0 (2026-10-24) adds caches
and late settlement (R17, R18), `upfront` and `escrow` flows (R19), asset and network substitution at the facilitator
(F13, F14), and the adoption track: framework quickstarts, docs examples run by CI, the implementation and compatibility
matrices and the published mutation matrix. On `main` since 1.6.0, not released yet: the MCP transport (X1, X2) and
`x402conf-svm mcp`, settlement preemption (R21), the `upto` and `batch-settlement` schemes (U1 to U3, B1 to B3), A2A and
discovery (D1, G1), SIWX normative checks (W1 to W3), P9 and P10, paced live targets, and the opt-in two-tier matrix.
Next: the release gate for dropping the experimental label (XC-32). Every check is labelled normative, security profile or resilience, and every check ships with a
passing control and a faulty build it catches. The plan and the release gate for dropping the experimental label are in
[docs/ROADMAP.md](docs/ROADMAP.md); every release and what it added is in [docs/RELEASES.md](docs/RELEASES.md).

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

For a badge that shows the latest result (`pass 32/32` or `2 failing`), publish the action's `badge` output somewhere
public, for example with GitHub Pages or a gist, and point shields.io at it:

```markdown
[![x402 conformance](https://img.shields.io/endpoint?url=https://YOU.github.io/YOUR-REPO/x402-badge.json)](https://github.com/atsp-protocol/x402-conformance)
```

`x402conf report --dir x402-conformance --badge x402-badge.json` writes the same file outside the action.

## Who uses it

No public users yet. I only list a user once they've said so publicly. If you run it, open an issue or say so in
[Discussions](https://github.com/atsp-protocol/x402-conformance/discussions) and I'll add you here and to
[docs/ADOPTION.md](docs/ADOPTION.md).

**Free run for your project.** Open an issue with your repo or facilitator URL and I'll run the suite against it,
post the results, and send a tests-only pull request with the Action and badge. It's free, with no conditions.

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
