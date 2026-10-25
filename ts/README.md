# x402-conformance-svm

The resource-server probe of [x402-conformance](https://github.com/atsp-protocol/x402-conformance). It starts a
facilitator double on loopback, points your server at it through `X402_FACILITATOR_URL`, and pays your paid route
with test payloads on **Solana devnet** or **Base Sepolia** (`exact`; EVM via EIP-3009) under each fault below. The name
is historical: it grades Base Sepolia too. The double never touches a chain, a key or anything beyond loopback.

```
npx -y x402-conformance-svm probe --resource http://127.0.0.1:4020/paid --start "node server.js" --out results.json
npx -y x402-conformance-svm resource --url https://your.api/paid --out answer.json   # P1-P7: one unpaid GET, any network
npx -y x402-conformance-svm live --url https://your.api/paid --out live.json       # P1-P7, R24 (+ R16a with --operator-permission off loopback), 5 s apart
npx -y x402-conformance-svm mcp --url https://your.api/mcp --tool <paid-tool>       # X1, P3-P5, P7: one unpaid tools/call
npx -y x402-conformance-svm demo                                                     # R0-R10 against a bundled mock, no wallet
npx -y x402-conformance-svm --help
npx -y x402-conformance-svm --version
```

`demo --fault serve_on_any_settle` shows a failing run and its fix hints. `--share` on `probe` and `resource` also writes
an anonymised corpus case next to `--out` (or to `./x402-conformance-case.json`) and, when a check failed, prints a link
to a pre-filled GitHub issue; nothing is sent. `X402CONF_VIA` names the entry point in the report and the User-Agent.
`resource` and `demo` exit 0 when every check passes, 1 when one fails and 2 on a usage error. `resource` and `live`
wait at least `--min-interval` seconds (default 5) between requests to a host that is not loopback, stop before
`--max-requests` is exceeded, log each request on stderr and record the log under `pacing` in the JSON. Run `live`
only against a server whose operator agreed to it: it sends one `HEAD` and five malformed payment headers. `mcp` takes
`--tool`, `--arguments '<json>'` and `--no-initialize` (one `tools/call` without a session; 3 requests with one), and
is paced the same way; MCP is JSON-RPC over `POST`, so the same operator rule applies.

| id | what the double does on `/settle` | your server must |
|---|---|---|
| R0 | (unpaid request) | answer 402 with a `PAYMENT-REQUIRED` header offering `exact` on Solana devnet or Base Sepolia; if it offers neither, the result is **unsupported** |
| R1 | settles | serve the content, after calling the double (otherwise the probe stops: your server isn't using `X402_FACILITATOR_URL`) |
| R2 | settles once, then `duplicate_settlement` | serve the same payment at most once (F3) |
| R3 | never answers | not serve (F6) |
| R4 | HTML 502 | not serve (F6) |
| R5 | 503 with a body that reads as success | not serve (F9) |
| R6 | 200 with an HTML page | not serve (F9) |
| R7 | 200 with half a success body | not serve (F9) |
| R8 | `settlement_pending` with a transaction | not serve before the payment is final (F5) |
| R9 | `invalid_transaction_state` | not serve (F8) |
| R10 | (the R1 response) | carry a `PAYMENT-RESPONSE` header that decodes to `success: true` |

**Your server.** Any x402 resource server works if it reads its facilitator URL from `X402_FACILITATOR_URL` and offers
one of the two test networks. With the upstream Express middleware, unchanged:

```js
import express from "express";
import { paymentMiddleware, x402ResourceServer } from "@x402/express";
import { HTTPFacilitatorClient } from "@x402/core/server";
import { ExactEvmScheme } from "@x402/evm/exact/server";   // or ExactSvmScheme from "@x402/svm/exact/server"

const network = "eip155:84532";                              // or "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"
const server = new x402ResourceServer(new HTTPFacilitatorClient({ url: process.env.X402_FACILITATOR_URL }))
  .register(network, new ExactEvmScheme());
const app = express();
app.use(paymentMiddleware({ "GET /paid": { accepts: [{ scheme: "exact", price: "$0.001", network,
  payTo: "0xYourAddress" }], description: "paid route" } }, server));
app.get("/paid", (_req, res) => res.json({ content: "paid content" }));
app.listen(Number(process.env.PORT ?? 4020), "127.0.0.1");
```

This server passes R0-R10 in this repo's CI on both networks
([example/express-server.ts](https://github.com/atsp-protocol/x402-conformance/blob/main/ts/example/express-server.ts)).

**Options.** `--port` sets the double's loopback port (default 4402). `--start` runs your server with
`X402_FACILITATOR_URL` set; the probe refuses to run if something else already answers on your server's port, and stops
with an error if your server exits. `--network` picks `auto` (default), `solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1` or
`eip155:84532`. `--out` writes the results JSON, on errors too. Each R0-R10 request has a 60 s deadline, and each R14 request 30 s; a server still holding
a request then has served nothing.

**R11, payment-to-request binding.** Give the routes to bind, with or without `--resource`: `--cheap` and `--expensive`
are two paid routes at different prices (R11, R11a, R11b), `--by-method` a paid URL priced differently for `GET` and
`POST` (R11c), `--by-query` two paid URLs that differ only in the query, comma-separated (R11d), `--param` a paid
parameterised route with `{id}` where the parameter goes (R11e), and `--siwx-cheap` and `--siwx-expensive` two paid
routes at different prices that declare sign-in-with-x, on an EVM (`eip155:`) network such as Base Sepolia (R11f). R11f
needs `@x402/extensions` and `viem` installed next to the probe; without them it is reported unsupported, not failed.

**R14, a crash between `/settle` and the response (`--crash`).** After the other checks, and only when R1 passed (otherwise R14 is left out of the results), the probe kills your server twice, once
while `/settle` is answering and once as the response starts, restarts it and presents the same payment (with a
`payment-identifier` id if your route advertises that extension). Your server must not call `/settle` again or answer
402, and must either deliver once from its idempotency record or refuse and name the transaction or payment id so it
can be reconciled. With `--start` the probe restarts that command itself; for a server it didn't start, pass
`--crash-kill "<command>"` and `--crash-restart "<command>"`. The idempotency record has to survive the restart: see
[example/crash-server.ts](https://github.com/atsp-protocol/x402-conformance/blob/main/ts/example/crash-server.ts) and
[FIXES.md#r14](https://github.com/atsp-protocol/x402-conformance/blob/main/docs/FIXES.md#r14).

**Retry double-pay (R20).** `--retry` adds R20 on `--resource`: the double holds `/settle` past the client's 400 ms
timeout, the probe gives up and retries once the first payment has settled. R20a retries with a fresh payment under the
same payment-identifier id (and `Idempotency-Key`); R20b resends the same signed payment. Either way the request must be
settled once and the retry must get the earlier result or a `PAYMENT-RESPONSE` naming the first transaction. A stock
`@x402/express` server passes when it keeps an idempotency record keyed by the request
([example/retry-server.ts](https://github.com/atsp-protocol/x402-conformance/blob/main/ts/example/retry-server.ts));
with no record it pays twice. `checkClientRetry(client, url, double)` grades a client's own retry the same way: it must
resend the payment or keep the payment id.

**From code only (1.5.0): R12, R13, R15, R16, R16a, R21, R22, R23, R24 and C1 to C3.** These checks are exports of the
package, not commands: the CLI, the Action, `runConformance`, the pytest plugin and the MCP server don't run them. Each
takes the facilitator double from `startDouble()`, except `probeUnpaidHead`, and your server or client must use the
double's `url` as its facilitator. Each returns the same `Result[]` as `probe`, so `makeReport` and `explain` work on
them.

| id | export | what your server or client must do |
|---|---|---|
| R12 | `probeParallel(url, double, { parallel? })` | settle one payment-identifier id once when eight requests carry it at the same time, each with a fresh payment, and name that settlement in every served answer |
| R13 | `probeReplicas(urlA, urlB, double)` | settle one payment-identifier id once across two replicas: sent to one, then the other, then both at once |
| R15 | `probeDelivery({ error, redirect, throws }, double)` | not settle, and send no `PAYMENT-RESPONSE`, when the paid handler answers 5xx, redirects or throws |
| R16 | `probeHead(url, double)` | not settle a paid `HEAD`: no 2xx, no `/settle` call, no `PAYMENT-RESPONSE` |
| R16a | `probeUnpaidHead(url)` | answer an unpaid `HEAD` with the same 402 and `PAYMENT-REQUIRED` offer as `GET`, or refuse it with 405, so it never reaches the handler |
| D1 | `checkDiscovery(facilitatorUrl)` | serve `/discovery/resources` and `/discovery/search` in the V2 section 8 shapes, with complete items, and honour `limit` and the `network` filter. GET only, no double |
| G1 | `checkA2aMirrorsHttp({ a2aUrl, httpUrl })` | answer an unpaid A2A `message/send` with an `input-required` task whose `x402.payment.required` asks for the same `accepts` as the HTTP route's 402. Sends no payment |
| R17 | `probeCacheLeak(url, double)` | mark the paid response `private` or `no-store`, or vary it on the payment header, so a shared cache in front of the route never serves the paid content to an unpaid request (RFC 9111) |
| R18 | `probePending(url, double)` | never serve while a settlement is pending, late or unanswered, serve once after it is final, and surface the transaction on every refusal (V2 section 9) |
| R19 | `probeFlows(url, double)` | on an `upfront` or `escrow` offer, settle before the resource executes and reject an unsupported flow (V2 section 6.1) |
| R21 | `probePreempt(url, double)` | on a Base Sepolia Permit2 offer, serve only on its own successful settle: never on a settlement a third party made first, and never twice for a spent payment |
| R22 | `probeStatus(routes, double)`, each route `{ url, status, headers? }` | keep the handler's 2xx status and headers on the paid response: a 201 stays a 201 with its `Location` |
| R23 | `probeAbort(url, double)` | not charge a client that disconnects while `/settle` is in flight, or charge it once and give a resend of the same payment the settled result |
| R24 | `probeMalformedHeader(url, double)` | answer five malformed `PAYMENT-SIGNATURE` values with 402 or 400 and a structured error, never a 5xx, a dropped connection or the content |
| X1 | `checkMcpPaymentRequired({ url, tool })` | answer an unpaid call of a paid MCP tool with a tool result: `isError: true`, the `PaymentRequired` object in `structuredContent` and the same JSON in `content[0].text` (MCP transport). Sends no payment |
| X2 | `probeMcpTransport({ url, tool }, double)` | return a paid MCP tool's result only on a final first-time settle, with `_meta["x402/payment-response"]`, and nothing on a `/settle` timeout, a broken answer, `settlement_pending`, a failed settle or a duplicate |
| C1 | `checkClientHandles402(client, url, double)` | never hand a 402 to its caller as a success: pay and get a 2xx, or reject with an error |
| C2 | `checkClientOfferPolicy(client, url, double, { networks, maxAmount })` | pay one of several offers on its configured networks and within its maximum, and never sign for a network outside its set |
| C3 | `checkClientKeepsV2(client, url, double)` | pay with `PAYMENT-SIGNATURE` at `x402Version` 2 when the 402 also carries a V1 body |
| W1-W3 | `probeSiwx(url, double)` | on a paid route that declares sign-in-with-x: check `domain` and `uri` against the configured origin, never `Host` (W1); take each nonce once (W2); refuse a stale, future or expired message (W3). Needs `@x402/extensions` and `viem` |

C2 and C3 take `{ signsPayments: false }` for a client that has no payment path by design: if it signs nothing the
check is `not_applicable` (N/A in reports, never a failure); if it signs anyway it is graded as usual.

**The `upto` and `batch-settlement` schemes (unreleased): U1 to U3 and B1 to B3.** These take the scheme double from
`startSchemeDouble()` instead of `startDouble()`; it serves both schemes on Solana devnet and Base Sepolia and settles
whatever amount it is asked for, so the probe sees what your server asked. `probeBatch` also needs `redeem`, a function
that runs your server's redemption once and returns one `{ channelId, ok }` item per channel it tried.

| id | export | what your server must do |
|---|---|---|
| U1 | `probeUpto(url, double, { network? })` | settle at most the maximum the client signed; point `url` at a request whose usage you want graded |
| U2 | `probeUpto(url, double)` | report the settled `amount` and its transaction in `PAYMENT-RESPONSE` |
| U3 | `probeUpto(url, double)` | declare no `extra.paymentFlow` or the binding's own (`authorization` on EVM, `escrow` on Solana), never `upfront` |
| B1 | `probeBatch(url, double, { redeem })` | serve a deposit and each fresh voucher once, with a commitment identifier and a charge within the per-request amount, and refuse a voucher already paid with |
| B2 | `probeBatch(url, double, { redeem })` | claim each channel once per run, at its latest voucher, and nothing on a run with nothing new |
| B3 | `probeBatch(url, double, { redeem })` | when a claim batch fails, report each channel with its own outcome and claim only the failed ones on the next run |

A client check takes your client as a function that fetches a URL, pays and returns the final `Response`. The controls
and the faulty builds each check catches are in `example/` and `test/`, and
[docs/USING.md](https://github.com/atsp-protocol/x402-conformance/blob/main/docs/USING.md#checks-you-call-from-code) has
a complete example.

**In tests.** `x402-conformance-svm/testing` runs R0-R10 against a server you start in-process.
`runConformance({ start: (facilitatorUrl) => ({ url, close? }), network?, deadlineMs?, via? })` returns a report and never
throws for a failing server; `start` may also return a promise. `expect.extend(x402Matchers)` adds
`toPassX402Conformance()` and `toBeValidX402Challenge()` for vitest and jest, and `assertX402Conformance(report)` throws
the same message for node:test. `saveReport(report, { dir?, share?, stack? })` writes the report to `dir`, else
`X402CONF_REPORT_DIR`, else `./x402-conformance`, with `share: true` also an anonymised corpus case, and returns the paths
and the share link. `checkPaymentRequired(url)` is exported here too.

**Exit codes.** 0 all pass; 1 a check failed; 2 usage error, or the run couldn't complete (a port in use, your server
exited or never answered); 3 unsupported: your server offers no network the probe grades, or a check could not run
(R11f without `@x402/extensions` and `viem`); an unsupported result takes precedence over a failed one. `--help` and
`--version` exit 0.

In GitHub Actions use the action at the repository root:

```yaml
- uses: atsp-protocol/x402-conformance@v1
  with:
    resource-url: http://127.0.0.1:4020/paid
    start: node server.js
```

Apache-2.0. Ryan Gillespie / Optitransfer.
