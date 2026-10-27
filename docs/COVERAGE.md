# Coverage

What the suite checks, where each check runs, which networks, schemes, stacks and facilitators the evidence covers, and
what it does not cover. The block between the two marker comments is generated from `CATALOG` in
`src/x402conf/spec.py` by `tools/build_coverage.py`, and `tests/test_coverage_doc.py` fails CI when it is stale; the
other sections are reviewed against the code at each release. [RELEASES.md](RELEASES.md)
says which release added what, and [SPEC.md](SPEC.md) quotes the spec text behind every check.

<!-- generated from src/x402conf/spec.py by tools/build_coverage.py; edit RUNS there, not this block -->

## Checks: 83 in the catalogue

- **S**: Facilitator, `GET /supported` (S0 to S4 live; S5 offline): S0, S1, S2, S3, S4, S5 (6 checks)
- **P**: Any paid URL's 402 answer, one unpaid GET: P1, P2, P3, P4, P5, P6, P7, P9, P10 (9 checks)
- **F**: Facilitator safety, against doubles offline and on devnet: F1, F2, F3, F4, F5, F6, F7, F8, F9, F10, F11, F12, F13, F14, F14a, F15, F16 (17 checks)
- **D**: A facilitator's discovery API (Bazaar), GET only: D1 (1 checks)
- **R**: Resource server behind the facilitator double: R0, R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, R11a, R11b, R11c, R11d, R11e, R11f, R12, R13, R14, R15, R16, R16a, R17, R18, R19, R20, R20a, R20b, R21, R22, R23, R24 (34 checks)
- **G**: An A2A agent's paid skill, against the HTTP route it mirrors: G1 (1 checks)
- **C**: Client, through a recording proxy: C1, C2, C3, C4 (4 checks)
- **W**: Sign-in-with-x on a paid route, behind the facilitator double: W1, W2, W3 (3 checks)
- **U**: The upto scheme on a paid route, behind the scheme double: U1, U2, U3 (3 checks)
- **B**: The batch-settlement scheme on a paid route and its redemption runs, behind the scheme double: B1, B2, B3 (3 checks)
- **X**: Paid MCP tools, over the MCP transport (JSON-RPC over Streamable HTTP): X1, X2 (2 checks)

By profile: 41 normative (the spec says MUST), 27 security
profile (a hardening rule the spec leaves open), 15 resilience (behaviour under failure).
Every check has at least one control that passes and one faulty build it catches, and CI runs every one of them
(`tests/test_offline.py`, `ts/test/`).

| check | profile | basis | where it runs | controls | faulty builds |
|---|---|---|---|---|---|
| B1 | normative | batch-settlement: the settlement result MUST include a non-empty commitment identifier on success, the charge is at most the per-request amount, and the same authorization MUST NOT execute the handler twice | library only: `probeBatch` from `x402-conformance-svm` | 1 | 1 |
| B2 | security-profile | batch-settlement redemption: the server claims each channel's latest cumulative voucher, which supersedes the older ones, and a claim cannot advance accounting twice | library only: `probeBatch` from `x402-conformance-svm` | 1 | 1 |
| B3 | resilience | batch-settlement redemption in batches: a channel is not silently dropped from a batch, and a voucher whose claim failed stays claimable, so a partly failed run is reported and retried per item | library only: `probeBatch` from `x402-conformance-svm` | 1 | 1 |
| C1 | security-profile | V2 4 and HTTP transport: a 402 is Payment Required or Payment Failed, not Success, so a client pays and retries or raises an error | library only: `checkClientHandles402` from `x402-conformance-svm` | 3 | 3 |
| C2 | security-profile | given several offers a client pays one within its own networks and maximum amount, not the first; V2 12.1: spending controls are implementation-specific | library only: `checkClientOfferPolicy` from `x402-conformance-svm` | 1 | 2 |
| C3 | security-profile | V2 HTTP transport: PAYMENT-REQUIRED is canonical; V2 5.2.2 accepted is Required, and a V1 payload (V1 5.2.2) has none | library only: `checkClientKeepsV2` from `x402-conformance-svm` | 1 | 1 |
| C4 | security-profile | a client that resumes after a crash between settle and its own record reuses the settled result and does not sign a second payment for the same job key | `node --test` on `ts/test/c4-resume.test.ts` | 1 | 1 |
| D1 | normative | V2 8 and the bazaar extension: GET /discovery/resources returns x402Version, items and pagination (limit, offset, total), GET /discovery/search returns resources; every item has resource, type, x402Version, accepts and lastUpdated (8.3), and limit and the network filter are honoured | library only: `checkDiscovery` from `x402-conformance-svm` (GET only) | 1 | 2 |
| F1 | normative | V2 9 invalid_payload; V2 5.1.2 atomic units; SVM exact: fail closed | `x402conf offline`, `x402conf devnet` (real `/verify` and `/settle` on Solana devnet) | 1 | 2 |
| F2 | normative | SVM exact 1.1 and V2 9: an amount below the requirement is rejected | `x402conf offline`, `x402conf devnet` (real `/verify` and `/settle` on Solana devnet) | 1 | 1 |
| F3 | normative | SVM exact, Duplicate Settlement Mitigation: duplicate_settlement | `x402conf offline`, `x402conf devnet` (real `/verify` and `/settle` on Solana devnet) | 1 | 1 |
| F4 | security-profile | V2 10.1 replay prevention; one memo or nonce, one purchase | `x402conf offline`, `x402conf devnet` (real `/verify` and `/settle` on Solana devnet) | 1 | 1 |
| F5 | normative | V2 9: settlement_pending is non-terminal and MUST carry transaction and network | `x402conf offline`, `x402conf devnet` (real `/verify` and `/settle` on Solana devnet) | 1 | 2 |
| F6 | normative | Solana guide: a retry cannot settle or fulfil the same purchase twice; SVM exact: fail closed | `x402conf offline`, `x402conf devnet` (real `/verify` and `/settle` on Solana devnet) | 1 | 1 |
| F7 | normative | V2 9 settlement_pending: retry reaches the final outcome | `x402conf offline` | 1 | 1 |
| F8 | normative | V2 9 invalid_transaction_state is terminal | `x402conf offline` | 1 | 1 |
| F9 | resilience | SVM exact 2.1.2: a transient failure fails closed and stays retryable | `x402conf offline` | 1 | 2 |
| F10 | security-profile | V2 5.1.2 and 5.2.2: a payment is verified against the requirements it was quoted under | `x402conf offline` | 1 | 1 |
| F11 | normative | V2 7.1: /verify MUST NOT commit payment state | `x402conf offline` | 1 | 1 |
| F12 | security-profile | V2 7.1 and 7.3: /verify checks a payment against the kinds /supported advertises; an asset is a token contract on the network | `x402conf offline` | 1 | 1 |
| F13 | security-profile | V2 5.1.2: a payment settles the asset the requirement names; the amount and recipient alone do not bind the asset, so a different mint at the same price is a distinct payment | `x402conf offline` | 1 | 1 |
| F14 | security-profile | V2 5.1.2 and 11.1: the verifier binds the payment's authorized network to the requirement; a payment authorized for one network is not valid against a requirement on another, even when amount, asset and payTo match (facilitator-layer network substitution) | `x402conf offline` | 1 | 1 |
| F14a | security-profile | EIP-712 and EVM exact (EIP-3009): a signature is bound to a chain only by the domain's chainId; an authorization signed over a domain without chainId is valid on every chain with the same token address, so the verifier requires the domain's chainId to be the requirement's network and rejects a chainless domain replayed on another network | `x402conf offline` | 1 | 1 |
| F15 | resilience | V2 9: a non-object, empty-object or authorization-less payload is invalid_payload (HTTP 400, or isValid false), never an HTTP 5xx and never an uncaught exception | `x402conf offline` | 1 | 3 |
| F16 | security-profile | V2 7.3 and 11.1: a facilitator registered for one testnet does not accept a requirement for a different network in the same family; a family wildcard is not a registration | `python3 -m unittest tests.test_offline.F16` | 1 | 1 |
| G1 | security-profile | A2A transport: payment required is a task in input-required with x402.payment.status payment-required and the PaymentRequired in x402.payment.required; an agent that mirrors an HTTP route asks for the same requirements as its 402 | library only: `checkA2aMirrorsHttp` from `x402-conformance-svm` | 1 | 2 |
| P1 | normative | V2 HTTP transport: payment required is signalled with HTTP 402 | `x402conf resource`, `x402conf-svm resource`, Action `resources`, pytest `check_payment_required`, MCP `x402_check_payment_required` | 1 | 1 |
| P2 | normative | V2 HTTP transport: PAYMENT-REQUIRED carries base64 JSON; V1 5.1 body | `x402conf resource`, `x402conf-svm resource`, Action `resources`, pytest `check_payment_required`, MCP `x402_check_payment_required` | 2 | 1 |
| P3 | normative | V2 5.1.2: x402Version, resource and accepts are required | `x402conf resource`, `x402conf-svm resource`, Action `resources`, pytest `check_payment_required`, MCP `x402_check_payment_required` | 1 | 1 |
| P4 | normative | V2 5.1.2: required accepts fields; amount in atomic token units | `x402conf resource`, `x402conf-svm resource`, Action `resources`, pytest `check_payment_required`, MCP `x402_check_payment_required` | 1 | 1 |
| P5 | normative | EVM exact: extra.name and extra.version; SVM exact: extra.feePayer | `x402conf resource`, `x402conf-svm resource`, Action `resources`, pytest `check_payment_required`, MCP `x402_check_payment_required` | 1 | 2 |
| P6 | resilience | The spec sets no header budget; Node fetch fails above 16 KB of headers and aiohttp near 8 KB | `x402conf resource`, `x402conf-svm resource`, Action `resources`, pytest `check_payment_required`, MCP `x402_check_payment_required` | 1 | 1 |
| P7 | normative | V2 6.1: extra.paymentFlow MUST be present when the resolved flow is not authorization (a warning: the upto SVM scheme spec allows omitting it) | `x402conf resource`, `x402conf-svm resource`, Action `resources`, pytest `check_payment_required`, MCP `x402_check_payment_required` | 1 | 1 |
| P9 | normative | bazaar extension, Schema Validation: schema is JSON Schema Draft 2020-12 with same-document $ref only, and facilitators MUST validate info against schema before cataloging | `x402conf resource`, when the 402 carries the bazaar extension | 1 | 2 |
| P10 | resilience | draft-hawkins-x402-dns-discovery 3.2: resources are HTTPS on the manifest's own host, and a manifest that diverges from the live endpoint is a misconfiguration (a warning; the runtime 402 is authoritative) | `x402conf resource --well-known` | 1 | 2 |
| R0 | normative | V2 HTTP transport: an unpaid request gets 402 with PAYMENT-REQUIRED | `x402conf-svm probe`, Action `resource-url`, `runConformance`, pytest `probe`, MCP `x402_probe_resource_server` | 2 | 1 |
| R1 | normative | V2 7.2: the resource server settles through its facilitator | `x402conf-svm probe`, Action `resource-url`, `runConformance`, pytest `probe`, MCP `x402_probe_resource_server` | 2 | 1 |
| R2 | normative | F3, F5, F6, F8 and F9 applied to a running resource server | `x402conf-svm probe`, Action `resource-url`, `runConformance`, pytest `probe`, MCP `x402_probe_resource_server` | 2 | 2 |
| R3 | resilience | F3, F5, F6, F8 and F9 applied to a running resource server | `x402conf-svm probe`, Action `resource-url`, `runConformance`, pytest `probe`, MCP `x402_probe_resource_server` | 2 | 2 |
| R4 | resilience | F3, F5, F6, F8 and F9 applied to a running resource server | `x402conf-svm probe`, Action `resource-url`, `runConformance`, pytest `probe`, MCP `x402_probe_resource_server` | 2 | 2 |
| R5 | resilience | F3, F5, F6, F8 and F9 applied to a running resource server | `x402conf-svm probe`, Action `resource-url`, `runConformance`, pytest `probe`, MCP `x402_probe_resource_server` | 2 | 2 |
| R6 | resilience | F3, F5, F6, F8 and F9 applied to a running resource server | `x402conf-svm probe`, Action `resource-url`, `runConformance`, pytest `probe`, MCP `x402_probe_resource_server` | 2 | 2 |
| R7 | resilience | F3, F5, F6, F8 and F9 applied to a running resource server | `x402conf-svm probe`, Action `resource-url`, `runConformance`, pytest `probe`, MCP `x402_probe_resource_server` | 2 | 2 |
| R8 | normative | F3, F5, F6, F8 and F9 applied to a running resource server | `x402conf-svm probe`, Action `resource-url`, `runConformance`, pytest `probe`, MCP `x402_probe_resource_server` | 2 | 2 |
| R9 | normative | F3, F5, F6, F8 and F9 applied to a running resource server | `x402conf-svm probe`, Action `resource-url`, `runConformance`, pytest `probe`, MCP `x402_probe_resource_server` | 2 | 2 |
| R10 | normative | V2 HTTP transport: settlement results go in PAYMENT-RESPONSE | `x402conf-svm probe`, Action `resource-url`, `runConformance`, pytest `probe`, MCP `x402_probe_resource_server` | 2 | 1 |
| R11 | normative | control: each route is served and settled once with its own payment | `x402conf-svm probe` with the binding flags, Action `binding-*` | 1 | 1 |
| R11a | normative | V2 5.2.2: accepted is matched against the route's own requirements | `x402conf-svm probe` with the binding flags, Action `binding-*` | 1 | 1 |
| R11b | normative | V2 5.1.2 and 9: recipient, asset and network must match | `x402conf-svm probe` with the binding flags, Action `binding-*` | 1 | 1 |
| R11c | security-profile | a route priced by method is priced for the method used | `x402conf-svm probe` with the binding flags, Action `binding-*` | 1 | 1 |
| R11d | security-profile | a route priced by query is priced for the query sent | `x402conf-svm probe` with the binding flags, Action `binding-*` | 1 | 1 |
| R11e | security-profile | payment middleware and framework must agree on the path | `x402conf-svm probe` with the binding flags, Action `binding-*` | 1 | 1 |
| R11f | security-profile | sign-in-with-x: access is for the requested resource the server priced and settled | `x402conf-svm probe` with the binding flags, Action `binding-*` | 1 | 1 |
| R12 | security-profile | payment-identifier: the id is an idempotency key that deduplicates requests, so parallel requests with one id are charged once | library only: `probeParallel` from `x402-conformance-svm` | 1 | 1 |
| R13 | resilience | payment-identifier: the id deduplicates requests for the service, not per process, so its replicas charge one id once | library only: `probeReplicas` from `x402-conformance-svm` | 1 | 1 |
| R14 | resilience | payment-identifier: same id, same payload returns the cached response; V2 6.1: in the authorization flow funds move only after the resource completes; V2 9: a transaction is surfaced so the caller can reconcile | `x402conf-svm probe --crash`, Action `crash` | 1 | 3 |
| R15 | normative | V2 6.1: in the authorization flow funds move only after the resource completes successfully; a failed, redirected or thrown request is not settled | library only: `probeDelivery` from `x402-conformance-svm` | 1 | 2 |
| R16 | security-profile | RFC 9110 9.3.2: a HEAD response carries no content, so a HEAD carrying a payment has nothing to deliver and is not settled | library only: `probeHead` from `x402-conformance-svm` | 1 | 1 |
| R16a | security-profile | the paywall covers every method that reaches the protected handler: RFC 9110 9.3.2 HEAD is GET without the content, so an unpaid HEAD is answered 402 | `x402conf-svm live` and `x402conf resource --unpaid-head` (unpaid, paced; off loopback only with `--operator-permission`), and `probeUnpaidHead` from `x402-conformance-svm` | 1 | 1 |
| R17 | security-profile | RFC 9111: a shared cache may store a 200 that is not private or no-store and does not vary on the request header that decided it, so a paid response must say so or the next caller gets it for free | library only: `probeCacheLeak` from `x402-conformance-svm` | 1 | 2 |
| R18 | resilience | V2 9: settlement_pending carries the transaction so the caller can reconcile; a pending, late or unanswered settlement ends served once after it is final, or refused with the payment surfaced | library only: `probePending` from `x402-conformance-svm` | 1 | 2 |
| R19 | normative | V2 6.1: at least one check MUST run before the resource executes, and a server MUST reject an unsupported flow; on an upfront or escrow offer the check that gates execution is the settle | library only: `probeFlows` from `x402-conformance-svm` | 1 | 2 |
| R20 | security-profile | control: the route answers 402 with an exact offer the probe can pay | `x402conf-svm probe --retry`, Action `retry`; `checkClientRetry` for clients | 1 | 1 |
| R20a | security-profile | payment-identifier: a retry with the same id and a fresh payment is not charged again | `x402conf-svm probe --retry`, Action `retry`; `checkClientRetry` for clients | 1 | 2 |
| R20b | security-profile | a retry resending the same signed payment is settled once and gets the original result | `x402conf-svm probe --retry`, Action `retry`; `checkClientRetry` for clients | 2 | 2 |
| R21 | security-profile | EVM exact Permit2: the signed transfer names the x402ExactPermit2Proxy as spender, so anyone holding it can submit it first; a server grants only on a settlement it made, and a spent nonce never unlocks the resource again | library only: `probePreempt` from `x402-conformance-svm` | 1 | 2 |
| R22 | normative | after a successful settle the client receives the handler's own 2xx status code and headers, such as Location; a 201 stays a 201 and a 202 stays a 202, never a rewritten 200; a paid 3xx is not settled (R15) | library only: `probeStatus` from `x402-conformance-svm` | 1 | 2 |
| R23 | security-profile | a client that disconnects while /settle is in flight is not charged, or a resend of the same payment gets the settled result and is not charged again | library only: `probeAbort` from `x402-conformance-svm` | 1 | 2 |
| R24 | resilience | V2 HTTP transport, Error Handling: Invalid Payment (a malformed payment payload) is 400, Payment Required and Payment Failed are 402, and Server Error (500) is for the server's own failures | `x402conf-svm live` and `x402conf resource --malformed-header` (unpaid, paced), and `probeMalformedHeader` from `x402-conformance-svm` | 1 | 3 |
| S0 | normative | V2 7.3: GET /supported answers with a SupportedResponse | `x402conf live`, Action `facilitators` | 1 | 1 |
| S1 | normative | V2 7.3.1 SupportedResponse: kinds, extensions, signers; V1 7.3: kinds | `x402conf live`, Action `facilitators` | 2 | 2 |
| S2 | normative | V2 11.1: networks are CAIP-2 | `x402conf live`, Action `facilitators` | 1 | 1 |
| S3 | normative | V2 11.1 and SVM exact: Solana networks use the published CAIP-2 IDs | `x402conf live`, Action `facilitators` | 1 | 1 |
| S4 | normative | SVM exact: extra.feePayer is the sponsor's public key | `x402conf live`, Action `facilitators` | 2 | 2 |
| S5 | normative | V2 7.3: /supported lists the payment kinds the facilitator supports; V2 7.1: /verify answers isValid, with invalidReason when it is false | `x402conf offline` (needs `supported()` on the facilitator) | 1 | 2 |
| U1 | normative | upto, Core Property 4: the settled amount MUST be less than or equal to the authorized maximum; the settle-time requirements.amount is the actual charge (Core Property 5) | library only: `probeUpto` from `x402-conformance-svm` | 2 | 1 |
| U2 | normative | upto SettlementResponse: amount, the actual amount charged in atomic units (may be 0), is required on EVM and on Solana | library only: `probeUpto` from `x402-conformance-svm` | 1 | 1 |
| U3 | normative | upto, Payment Flow: upto cannot use upfront, because the amount is known only after the handler runs; Permit2 on EVM supports authorization, the Solana channel escrow (V2 6.1 extra.paymentFlow, as P7) | library only: `probeUpto` from `x402-conformance-svm` | 1 | 1 |
| W1 | normative | sign-in-with-x: domain MUST match the server's configured public origin host and the uri origin MUST match that origin, derived from the server's configuration, not from request headers such as Host | library only: `probeSiwx` from `x402-conformance-svm` | 1 | 1 |
| W2 | security-profile | sign-in-with-x: the nonce MUST be unique and the server SHOULD track used nonces, so one signed message signs in once | library only: `probeSiwx` from `x402-conformance-svm` | 1 | 1 |
| W3 | normative | sign-in-with-x: issuedAt MUST be recent (under five minutes) and MUST NOT be in the future, and a present expirationTime MUST be in the future | library only: `probeSiwx` from `x402-conformance-svm` | 1 | 1 |
| X1 | normative | MCP transport: a paid tool called without a payment MUST answer a tool result with isError true, the PaymentRequired object in structuredContent and the same object JSON-encoded in content[0].text | `x402conf-svm mcp` (one unpaid tools/call, paced), and `checkMcpPaymentRequired` from `x402-conformance-svm` | 1 | 2 |
| X2 | resilience | MCP transport: the server verifies, runs the tool and settles, and when the settle fails it returns only the payment error, never the tool's content; the R0-R10 faults on a paid tool call | library only: `probeMcpTransport` from `x402-conformance-svm` | 1 | 2 |

<!-- end generated -->

## Networks and schemes

| | covered | how |
|---|---|---|
| Solana devnet (`solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1`) | yes | the facilitator double, the probe and every resource-server and client check; F1 to F6 over real `/verify` and `/settle` against a self-hosted reference facilitator (`@x402/core` and `@x402/svm` 2.28.0) |
| Base Sepolia (`eip155:84532`) | yes | the double, the probe and every resource-server and client check, `exact` with EIP-3009 |
| `exact` scheme | yes | the only scheme the doubles implement; SVM and EVM |
| `upto` scheme | yes, against the scheme double | U1 to U3 on Solana devnet and Base Sepolia: the settled amount against the signed maximum, the reported amount and the declared flow; P7 reads `extra.paymentFlow` on any `upto` offer. No `upto` settlement reaches a chain |
| `batch-settlement` scheme | yes, against the scheme double | B1 to B3 on Solana devnet and Base Sepolia: commitments served once, one claim per channel per redemption run, and a partly failed run reported and retried per channel. No channel is opened on a chain |
| `upfront` and `escrow` flows | yes, from code | R19 (`probeFlows`): the settle gates execution on an `upfront` or `escrow` offer and an unsupported flow is rejected |
| Mainnet, any chain | never | the suite never pays or signs on mainnet |
| Other chains (Algorand, Polygon and the rest) | read-only | S0 to S4 and P1 to P7 read any facilitator's `/supported` and any paid URL's 402, whatever the network; nothing is paid |

## Transports and entry points

| | covered |
|---|---|
| HTTP, V2 headers (`PAYMENT-REQUIRED`, `PAYMENT-SIGNATURE`, `PAYMENT-RESPONSE`) | yes, every check |
| HTTP, V1 bodies and `X-PAYMENT` | S1 grades V1-only facilitators against V1; P1 to P7 read V1 answers; C3 catches a client that falls back to V1 |
| MCP transport (paid MCP tools) | no, planned (XC-33) |
| Entry points | `x402conf` and `x402conf-svm` CLIs, the GitHub Action, the vitest and jest matchers, node:test, pytest, the MCP server, the Vercel AI SDK and LangChain tools, the Docker image and a GitLab CI template; every one reports the same check ids |

## Stacks the controls and faulty builds run on

| stack | where | checks |
|---|---|---|
| `@x402/express` 2.28.0 | `ts/example/express-server.ts` and the binding, retry, crash, status, delivery, head, replica, cache, pending and flow servers | R0 to R11f, R12 to R19, R20, R22 to R24, on both networks |
| `@x402/hono` 2.28.0 | `ts/example/hono-server.ts`, the vitest quickstart | R0 to R10 |
| `@x402/core` with `node:http` | `ts/example/crash-server.ts`, the corpus case | R14 |
| `@x402/fetch` client | the C1, C2, C3 and R20 client checks | C1 to C3, R20b |
| x402 Python SDK 2.25.0, FastAPI | `examples/python/fastapi_server.py`, run by the pytest plugin test | R0 to R10 on Solana devnet |
| the reference facilitator (`@x402/core`, `@x402/svm` 2.28.0), self-hosted | `x402conf devnet` | F1 to F6 |
| the bundled mock server and facilitator | `x402conf-svm demo`, `x402conf demo` | R0 to R10, S1 to S4, P1 to P7 and the self-test |

Flask, Next and Go servers, and the compatibility matrix rebuilt in CI, are in the 1.6.0 task XC-48 (XC-19, XC-26, XC-28).

## Facilitators with published results

The live run of 2026-10-20 covers fifteen public facilitators with one `GET /supported` each (S0 to S4); the table is in
[../README.md](../README.md#results) and the raw bodies in [../evidence/2026-10-20-v1.3.0](../evidence/2026-10-20-v1.3.0).
The devnet safety run (F1 to F6) covers my self-hosted reference facilitator only; third-party facilitators are run only
with the operator's permission, and none has been asked yet ([MATRIX.md](MATRIX.md)). The matrix is opt-in, so it no
longer names open-source facilitators that have not accepted. Verify-only F checks against open-source facilitators
built at pinned commits and run on loopback as my own instances are signed as XC-51 and not built yet.

## Lean models

`lean/X402Conformance/`: the credit rule (`Settlement.lean`: `credit_sound`, `step_idem`, `step_nodup`, `run_nodup`),
nonces (`Nonce.lean`: `consume_once`, `only_open_consumes`), timeouts, `settlement_pending` reconciliation and concurrent
settles (`Pending.lean`: `pending_never_credits`, `timeout_never_credits`, `failure_never_credits`, `reconcile_credits_once`,
`resolved_final`, `failed_never_pending`, `failed_never_credits`, `concurrent_nodup`, `racy_not_nodup`) and, since 1.5.0,
n replicas (`Replicas.lean`: a shared atomic check-and-set admits at most one grant, partitioned caches admit a double
grant). They depend only on standard axioms, and CI fails on an unexpected one. They prove the rule the suite checks,
not anyone's code.

## Not covered

- The implementation matrix with Flask, Next and Go rows, framework quickstarts, docs examples run by CI, the
  compatibility matrix and the mutation matrix with the false-positive register: XC-48 (XC-19, XC-26 to XC-29).
- The MCP transport, settlement preemption (Permit2), A2A and discovery, and SIWX normative checks: signed tasks
  XC-33, XC-34, XC-36 and XC-37, not started.
- Certification: a pass is evidence about one property on one day. The badge says "tested with".
