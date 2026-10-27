# What failed and how to fix it

One section per check. Each failed check in the job summary, in SARIF (GitHub code scanning) and in JUnit links to
its section here. [SPEC.md](SPEC.md) quotes the spec text behind each check. These are fixes for the property a check
tests. Passing a check is evidence about that property only, not certification of conformance to x402.

Checks run in five places: **S** checks read a facilitator's `GET /supported`, and S5, which runs offline with the F
checks, also sends `/verify` once for each kind it lists; **P** checks read the 402 answer of a paid URL; **F** checks
drive a facilitator (a double offline, or a facilitator you run on devnet) and the resource-server guard in front of
it; **R** checks put a facilitator double in front of your resource server and request your paid route; **C** checks
put a recording proxy in front of a paid route and grade the client that pays it.

Severity: an **error** fails the run (with `--fail-on-error` or in the Action); a **warning** is reported and never
fails it. A probe result of **unsupported** means nothing was graded.

## S0
**What failed.** `GET <facilitator>/supported` didn't answer HTTP 200 with a JSON object: a timeout, DNS or TLS error,
a non-2xx status, a body over 1 MiB or a body that isn't a JSON object. No other S check could run.
**How to fix it.** Check the URL is the facilitator's base URL (the suite appends `/supported`). Serve `/supported`
with `content-type: application/json`. If the endpoint answers 401 or 403 because it needs credentials (Coinbase CDP,
for example), set `X402C_FACILITATOR_AUTHORIZATION` to the full `Authorization` header value and
`X402C_FACILITATOR_AUTH_HOST` to the facilitator's host name. The credential goes to that host only and is never
printed.

## S1
**What failed.** A response with any `x402Version: 2` kind is missing `kinds` (array), `extensions` (array) or
`signers` (object). A response whose kinds are all `x402Version: 1` is graded against V1 §7.3, which defines `kinds`
only; it fails S1 only if a kind lacks `scheme` or `network`.
**Why it matters.** V2 §7.3.1 makes all three required. Clients and resource servers read `signers` to check who will
pay fees and sign; without it they can't verify a fee payer.
**How to fix it.** Return all three, even when empty: `{"kinds": [...], "extensions": [], "signers": {}}`. A
facilitator that adds V2 kinds has to return the V2 shape.

## S2
**What failed.** A kind with `x402Version: 2` names its network without CAIP-2, for example `base-sepolia`.
**How to fix it.** Use `namespace:reference` IDs (V2 §11.1): `eip155:84532`, `solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1`.
Keep V1 names only on `x402Version: 1` kinds.

## S3
**What failed.** A Solana V2 kind uses a V1 name such as `solana-devnet`, or a `solana:` ID that isn't mainnet
(`solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp`) or devnet (`solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1`).
**How to fix it.** Use the published genesis-hash IDs from the Solana x402 guide. A typo here makes clients that match
networks exactly skip your facilitator.

## S4
**What failed.** Error: a Solana `exact` kind has no `extra.feePayer`, or the value isn't a 32-byte base58 key.
Warning: the fee payer isn't listed in `signers` under a pattern that matches the kind's network (the exact CAIP-2 ID
or `solana:*`). The spec doesn't say the fee payer must be listed; I infer it from V2 §7.3.1, which describes `signers`
as the facilitator's public signer addresses, so on its own it is a warning.
**Why it matters.** The client builds the transaction with this fee payer. A wrong or unlisted key means payments that
fail to settle, or a fee payer clients can't verify.
**How to fix it.** Set `extra.feePayer` to the key that will sign as fee payer and list it in `signers` under
`solana:*` or the kind's exact network ID.

## S5
**What failed.** A kind that `/supported` advertises got no structured `/verify` answer: the call raised or answered
5xx, the connection dropped, or the answer was `isValid: false` with no `invalidReason`. S5 also fails when
`/supported` itself fails or lists no kinds, because nothing could be graded.
**Why it matters.** A resource server and its clients read `/supported` to choose a kind and expect `/verify` to give
a verdict for it. A kind that errors at `/verify` looks supported but fails every payment, and a refusal with no reason
can't be acted on.
**How to fix it.** Advertise only the kinds your `/verify` has a handler for. For each one, answer `isValid: true`, or
`isValid: false` with an `invalidReason`, and keep 5xx for the facilitator's own failures.

## F1
**What failed.** A malformed payment payload was accepted (`isValid: true`) instead of rejected.
**How to fix it.** Validate the payload's shape and decoding before anything else and answer `invalid_payload` on any
error. Parse failures, missing fields and transient decode errors must fail closed (SVM exact §2.1.2).

## F2
**What failed.** A transfer below `PaymentRequirements.amount`, or a dust amount, was accepted.
**How to fix it.** Compare the decoded transfer amount with `amount` as integers in base units, after decimals, and
reject anything lower (SVM exact §1.1, §1.4). Check the mint and destination at the same time.

## F3
**What failed.** The same payment payload settled successfully twice, or a resource server served it twice.
**Why it matters.** A replayed payment (the `PAYMENT-SIGNATURE` header in V2, `X-PAYMENT` in V1) buys the resource twice for one payment.
**How to fix it.** Keep a duplicate-settlement cache keyed by the transaction (SVM exact, Duplicate Settlement
Mitigation) and answer `duplicate_settlement` on a hit. Make check-and-insert atomic: a read followed by a separate
write double-credits under concurrency (see `racy_not_nodup` in the Lean models). Record the key once the outcome is
final, so a retried `settlement_pending` still reaches its result (F7).

## F4
**What failed.** A memo or nonce that was already used settled again in a new transaction.
**Why it matters.** If your server ties one purchase to one memo, two transactions with the same memo can unlock two
purchases' worth of state. On devnet, the reference facilitator (`@x402/svm` 2.28.0) deduplicates by transaction but
not by memo, so this is yours to enforce.
**How to fix it.** Record consumed memos or nonces and reject a second use, atomically, in the facilitator or in the
resource server that maps memos to purchases.

## F5
**What failed.** A payment counted as settled before it was confirmed, or `settlement_pending` came back without a
non-empty `transaction` or without the `network`.
**How to fix it.** Return `success: true` only after the confirmation level you require. When you can't confirm in
time, return `settlement_pending` with the transaction signature and the network it was submitted on (V2 §9), so the
caller can reconcile on chain.

## F6
**What failed.** A facilitator timeout or malformed response was treated as a successful settlement.
**How to fix it.** In the resource server, credit only on a well-formed `success: true` answer. Treat timeouts, network
errors and unparsable bodies as "not settled" and keep the payment retryable.

## F7
**What failed.** A `settlement_pending` settle retried with the same body didn't reach its final result, came back with
a different transaction, or was credited more than once.
**How to fix it.** Treat `settlement_pending` as non-terminal (V2 §9). On retry, look up the same transaction and
return its final outcome; don't answer `duplicate_settlement` for a payment that never finished. Credit once, on the
final success.

## F8
**What failed.** A transaction that failed on chain after `settlement_pending` was still reported as pending.
**How to fix it.** Once the chain shows the transaction failed, answer `invalid_transaction_state` and keep that answer
for every later retry.

## F9
**What failed.** A 503, an HTML or other non-JSON page, or a truncated `/settle` body was credited, or the payment
couldn't be retried afterwards.
**How to fix it.** Check the status code, the content type and that the body parses before reading `success`. A 5xx
with a success-looking body is still a failure. Keep the payment retryable so a later well-formed answer credits it
exactly once.

## FX
**What failed.** A fault-injected facilitator double passed every check, so the suite would have missed that fault.
This is a bug in the suite, not in your code.
**How to fix it.** Open an issue with the `offline.json` output. Don't rely on that run's other results.

## F10

**What failed.** The verifier accepted a payload it had already settled under a different PaymentRequirements set, so the payment was treated as authorising a request it was never made for.

**How to fix it.** Record a requirements hash (canonical JSON of the requirements) for every transaction at first verification, and refuse the same transaction against any different hash. Fail closed when the requirements are missing or malformed. Keep the existing duplicate-settlement and memo checks: a legitimate retry of the same request keeps its idempotency contract, and a fresh payment for the new requirements settles normally.

## F11
**What failed.** Calling `/verify` changed payment state: a second `/verify` of the same payment failed as a
duplicate, or the payment could no longer settle, or it settled at verify time.
**Why it matters.** Resource servers call `/verify` before they run the handler and may call it again on retry. If
verification commits anything, a payment can be burned without being settled, or counted twice.
**How to fix it.** Keep `/verify` read-only (V2 §7.1): check signature, amount, recipient, asset and expiry, and record
nothing. Record the transaction, nonce and requirements hash in `/settle` only.

## P1
**What failed.** An unpaid `GET` of your paid URL wasn't answered with HTTP 402. A 200 means content is served without
payment; a 404 or 5xx means the probe didn't reach a paid route.
**How to fix it.** Put the payment middleware in front of the route and check the URL.

## P2
**What failed.** The 402 carried no `PAYMENT-REQUIRED` header (V2) and no V1 `PaymentRequired` JSON body, or the header
isn't base64-encoded JSON.
**How to fix it.** V2 servers send the `PaymentRequired` object base64-encoded in `PAYMENT-REQUIRED` (V2 HTTP
transport). If a proxy strips custom headers, allow it, and expose it to browsers with
`Access-Control-Expose-Headers: PAYMENT-REQUIRED`.

## P3
**What failed.** The `PaymentRequired` object has no `x402Version` of 1 or 2, no `resource.url` (V2), or an empty
`accepts`; or a V2 object was found in the body instead of the header.
**How to fix it.** Follow V2 §5.1.2: `{"x402Version": 2, "resource": {"url": ...}, "accepts": [...]}`.

## P4
**What failed.** An `accepts` entry lacks `scheme`, `network`, `asset`, `payTo`, `amount` (V2; `maxAmountRequired` in
V1) or `maxTimeoutSeconds`, or has the wrong type: the amount must be a string of atomic units above 0 (`"10000"`, not
`"0.01"`), the network a CAIP-2 ID in V2, the timeout a positive integer.
**How to fix it.** Let your x402 SDK build the requirements from a route config rather than writing them by hand.

## P5
**What failed.** A scheme-specific field is missing. EVM `exact` with EIP-3009 (the default transfer method) needs
`extra.name` and `extra.version`, the token's EIP-712 domain; Solana `exact` needs `extra.feePayer`.
**Why it matters.** Without them a client can't build a payment that verifies.
**How to fix it.** For USDC on Base Sepolia, `"extra": {"name": "USDC", "version": "2"}`. For Solana, take the fee
payer from your facilitator's `GET /supported`.

## P6
**What failed.** The base64 `PAYMENT-REQUIRED` header is larger than 8 KB (warning) or 16 KB (error).
**Why it matters.** Common proxies, CDNs and servers cap header size around 8-16 KB; past the cap the 402 is dropped or
replaced with a 4xx/5xx, and clients never see the offer.
**How to fix it.** Offer fewer `accepts` entries per route, keep `description` and extension `info` short, and move large
schemas (Bazaar `outputSchema` and the like) out of the header into the response body or a linked document.

## P7
**What failed.** An offer whose scheme defaults to a non-authorization flow (`upto` on Solana defaults to escrow) has no
`extra.paymentFlow`.
**Why it matters.** V2 §6.1 says `extra.paymentFlow` MUST be present when the flow isn't authorization, and clients and
facilitators that read it fall back to authorization semantics when it's absent. It's a warning because the upto SVM
scheme text allows omitting it.
**How to fix it.** Set `extra.paymentFlow` (`"upfront"` or `"escrow"`) on every such offer.

## P9
**What failed.** The 402 carries the bazaar discovery extension, and its `info` (usually the `info.input` example: the
query parameters, body or tool arguments) does not validate against the `schema` it ships with. The result lists each
problem with its path, for example `at /input/queryParams/limit: "3" is not of type integer`. An external `$ref` or
`$id`, or a `$schema` other than Draft 2020-12, fails too.
**Why it matters.** The bazaar extension says facilitators must validate `info` against `schema` before cataloging. An
example that fails its own schema can keep the endpoint out of a discovery catalog, and agents that build calls from
the schema and the example get two different answers.
**How to fix it.** Make the example match the schema (send `3`, not `"3"`, for an integer), or change the schema to
what the endpoint really accepts (query string values are strings, so `type: string` is also a valid choice). Keep
`$ref` same-document (`#/...`).

## P10
**What failed.** With `--well-known`, the host's `/.well-known/x402` manifest does not match the live 402: the paid URL
is not in `resources`, an entry is not HTTPS on this host or a subdomain, or the declared terms (scheme, network,
asset, payTo, or an atomic `amount`) match none of the live offers. It is a warning: the live 402 is what clients pay.
**Why it matters.** Crawlers and agents read the manifest to find what you sell. A stale or incomplete one hides paid
routes or advertises a price or recipient you no longer use, and an off-host entry is ignored by careful consumers.
**How to fix it.** Generate the manifest from the same route configuration as the payment middleware, list every paid
URL on your own host, and keep `payTo`, `asset`, `network` and `amount` in step with the 402.

## F12
**What failed.** The offline check asked the facilitator to verify a well-formed payment on a network no facilitator
supports (`x402conf:unsupported`), and one whose asset is an address with no contract code. It answered
`isValid: true` for at least one, answered without an `invalidReason`, or raised.
**Why it matters.** A facilitator that trusts the network and asset in the requirements verifies payments it can
never settle, or "payments" in a token that does not exist. The resource server serves on that verdict, or settles
against an address with no code and gets a meaningless success.
**How to fix it.** Before anything else in `/verify`, check that the payment's (scheme, network) is one you advertise
and that the asset is a known token contract on that network (an allow-list, or a code check against the chain), and
answer `isValid: false` with a specific reason (`unsupported_network`, `invalid_asset`) when it is not.

## F13
**What failed.** The offline check asked the facilitator to verify a payment that carried the quoted amount to the
quoted recipient but settled a different mint. It answered `isValid: true`, or settled it.
**Why it matters.** The asset is part of what a payment is. A verifier that binds only the amount and the recipient
accepts a payment in a token the route never priced, so the resource server serves on a payment it did not sell.
**How to fix it.** In `/verify`, compare the payment's on-chain asset to `PaymentRequirements.asset` and answer
`isValid: false` when they differ. Do not take the asset from the requirements on trust; read it from the signed
authorization or the on-chain transfer and require an exact match.

## F15
**What failed.** `/verify` was given a non-object body, an empty object, or a body with no authorization. It answered HTTP 5xx, or the library raised and nothing turned that into `invalid_payload`.
**Why it matters.** A malformed payload is a client error. A 5xx says the facilitator failed, so a caller retries or treats the route as down, and the failure is not the structured reject V2 §9 names.
**How to fix it.** On those three bodies, return HTTP 400 or HTTP 200 with `isValid: false` and `invalidReason: invalid_payload`. Catch the decode error. Do not let it become an unhandled exception.

## F16
**What failed.** The facilitator is registered for one testnet and was given a requirement for a different network in the same family. It answered `isValid: true`.
**Why it matters.** A family prefix is not a registration. Accepting every network in the family settles a payment against a network the facilitator did not advertise.
**How to fix it.** Compare the requirement's CAIP-2 `network` to the exact ids you registered. Answer `isValid: false` with `invalid_network` or `unsupported_scheme`. Do not treat `eip155:*` as registered.

## F14
**What failed.** The offline check asked the facilitator to verify a payment whose authorized network differed from
the requirement's network, at the same amount, recipient and asset. It answered `isValid: true`, or settled it.
**Why it matters.** A verifier that binds only the amount and the recipient lets a payment authorized for one chain
settle a route priced on another. The sharpest form is a cross-chain signature replay: an EIP-3009 authorization
whose EIP-712 domain omits `chainId` is cryptographically valid on every chain that shares the token address. This
check covers the facilitator-side network binding; F14a tests the mis-bound signature itself.
**How to fix it.** In `/verify`, reject a payment whose authorized network is not the requirement's `network`
(`invalid_payment_requirements`), even when amount, recipient and asset match. Separately, make sure the EIP-712
domain carries the correct `chainId` so the signature itself cannot be replayed across chains.

## F14a
**What failed.** The offline check had a throwaway key, generated for the run and never funded, sign an EIP-3009
`TransferWithAuthorization` over an EIP-712 domain with `chainId` omitted, then replayed that signature against a
requirement on a second network at the same token address, amount and recipient. The facilitator answered
`isValid: true` on `/verify`, or settled it. (If the control, signed over a domain bound to the first network's
`chainId`, did not verify and settle there, the result says so and the replay is not graded as safe.)
**Why it matters.** EIP-712 binds a signature to a chain only through the domain's `chainId`. Without it the domain
separator, the digest and so the signature are the same on every chain where the token has the same address, which
is common for CREATE2 deployments. Anyone who sees the payment on one chain can settle it again on another and move
the payer's funds there.
**How to fix it.** In `/verify` and again in `/settle`, rebuild the EIP-712 domain the signature must cover from the
requirement: its `chainId` from the requirement's `network` and its `verifyingContract` from `asset`. Reject a
payload whose domain omits `chainId` or names another chain (`invalid_exact_evm_payload_signature`). Never verify
against a domain taken from the payload as given.

## R0
**What failed.** An unpaid request to your paid route didn't get a 402 with a decodable `PAYMENT-REQUIRED` header.
If the header decoded but offered no `exact` payment on Solana devnet or Base Sepolia, the result is **unsupported**
(exit code 3), not failed: nothing was graded.
**How to fix it.** Make sure the probe reaches the paid route and the middleware sets the header. For an unsupported
result, offer `solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1` or `eip155:84532` on a test build of the route. Fix this
first: the other results depend on it.

## R1
**What failed.** A request with a payment the double settled successfully wasn't served, or it was served but your
server never called the double's `/verify` or `/settle`.
**How to fix it.** Your server must use `X402_FACILITATOR_URL` as its facilitator so the probe's double answers. If it
serves without calling the double, it is talking to another facilitator, and the probe stops there instead of
reporting results that would mean nothing.

## RX
**What failed.** The probe couldn't run to completion: the facilitator double's port was taken, something else was
already answering on your server's port, your `--start` server exited or never answered within 60 s, or the probe
crashed. The error is in `resource-server.json` and the job log.
**How to fix it.** Free the port or pick another with `port`, and check your server's start command and logs.

## R2
**What failed.** The same payment presented twice was served twice (F3).
**How to fix it.** Reject a payment whose transaction you've already served, or rely on the facilitator's
`duplicate_settlement` answer and never serve on it.

## R3
**What failed.** Your route served content while `/settle` never answered (F6). The double holds the request open
and never answers; your server passes if it serves nothing until the probe's 60 s deadline, whatever its own
facilitator timeout. (Before 1.3.0 the double answered success after 30 s, which wrongly failed servers that waited
longer than that for a real answer.)
**How to fix it.** Serve only after a well-formed `success: true`. On a timeout, answer 402 or 5xx and let the client
retry.

## R4
**What failed.** Your route served content when `/settle` answered an HTML 502 (F6).
**How to fix it.** Treat any non-2xx or non-JSON answer as not settled.

## R5
**What failed.** Your route served content when `/settle` answered 503 with a body that says `success: true` (F9).
**How to fix it.** Check the status code before the body. A 5xx is never a settlement.

## R6
**What failed.** Your route served content when `/settle` answered 200 with a non-JSON body (F9).
**How to fix it.** Parse the body strictly and treat a parse error as not settled.

## R7
**What failed.** Your route served content when the `/settle` body was truncated (F9).
**How to fix it.** Same as R6: a body that doesn't parse completely is not a settlement.

## R8
**What failed.** Your route served content on `settlement_pending`, before the payment was final (F5).
**How to fix it.** `settlement_pending` is non-terminal. Don't serve yet. Keep the transaction, and either retry
`/settle` with the same body until it's final or answer without content and let the client retry.

## R9
**What failed.** Your route served content when `/settle` answered `invalid_transaction_state` (F8).
**How to fix it.** Treat every `success: false` answer as not paid, whatever its error code.

## R10
**What failed.** The served response to a settled payment carried no `PAYMENT-RESPONSE` header, or it didn't decode to
a settlement response with `success: true`.
**Why it matters.** The V2 HTTP transport returns the settlement result in `PAYMENT-RESPONSE`; clients and agents read
it for the transaction and payer.
**How to fix it.** Send the settle result base64-encoded in `PAYMENT-RESPONSE` with the content. The x402 middleware
does this for you; a hand-written server has to set it.

## R11
**What failed.** The R11 control: a correct payment for each route wasn't served, settled exactly once and answered
with `PAYMENT-RESPONSE`. Nothing else in R11 can be graded until it passes.
**How to fix it.** Check the binding URLs are paid routes on this server at different prices and that the server uses
`X402_FACILITATOR_URL` as its facilitator.

## R11a
**What failed.** A payment made for the cheap route was accepted on the expensive one.
**How to fix it.** Verify and settle against the requirements your server builds for the route being requested, never
against `paymentPayload.accepted`; match `accepted` against them field by field and answer 402 on any difference. The
stock `@x402/express` and `@x402/core` middleware do this.

## R11b
**What failed.** A payment with a changed `payTo`, asset or network reached `/settle` or was served.
**How to fix it.** Same as R11a: compare the client's `accepted` with your own requirements, recipient, asset and
network included, before calling the facilitator.

## R11c
**What failed.** On a route priced by HTTP method, a payment for the cheaper method was accepted with the dearer one.
**How to fix it.** Price with the method of the request being served, and include the method in the route you match
`accepted` against. Don't reuse a requirements cache keyed on path alone.

## R11d
**What failed.** On a route priced by a query parameter, a payment for the cheaper query was accepted with the dearer
one.
**How to fix it.** Compute the price from the request being served, after parsing its query, and compare it with the
client's `accepted.amount`. Don't price from a value the client sends in the payment.

## R11e
**What failed.** An encoded separator (`%2F`), a dot segment or double encoding in a parameter reached a paid handler
without payment.
**How to fix it.** Let the payment middleware and the framework router see the same path: register the paid routes with
the framework's own routing, or match on the raw path the router uses, and reject paths that decode to a different
route.

## R11f
**What failed.** After paying for the cheap route with `PaymentPayload.resource.url` set to the expensive route, a
sign-in-with-x header alone opened the expensive route.
**Why it matters.** `resource` is optional and set by the client (V2 §5.2.2). A SIWX store keyed on it grants access to
whatever URL the client wrote, not what was paid for.
**How to fix it.** Record SIWX access under the path your server priced and settled (the request path in the settle
hook's transport context), never `paymentPayload.resource.url`. Until a fixed `@x402/extensions` release, wrap
`createSIWxResourceServerExtension` and replace its `onAfterSettle` hook (see `ts/example/binding-server.ts`).


## W1
**What failed.** Your server accepted a sign-in-with-x message signed for another site: the message's `domain` and
`uri` named that site, and the request's `Host` or `X-Forwarded-Host` header named it too.
**Why it matters.** A signature a wallet made to sign in somewhere else can be replayed against your server by anyone
who controls a request header. The rule exists so a message is only good for the origin it was signed for.
**How to fix it.** Validate `domain` and the `uri` origin against your configured public origin, the browser-visible
URL, never against values taken from the request. With the SDK, pass `origin` to
`createSIWxResourceServerExtension` as a constant from your configuration (see `ts/example/siwx-server.ts`).

## W2
**What failed.** The same signed sign-in-with-x message, nonce and all, signed in a second time.
**Why it matters.** Anyone who sees the header once, in a log, a proxy or a shared terminal, can sign in as that
wallet for as long as the message is inside its time window.
**How to fix it.** Record each nonce when you grant access and refuse a nonce you have seen. The SDK does this when
your storage implements both `hasUsedNonce` and `recordNonce`; the shipped `InMemorySIWxStorage` implements neither,
so add them, or use a shared store when you run more than one instance (see `ts/example/siwx-server.ts`).

## W3
**What failed.** A sign-in-with-x message outside its time window was accepted: `issuedAt` more than five minutes old,
`issuedAt` in the future, or `expirationTime` in the past.
**Why it matters.** The time window is what limits how long a leaked or captured message stays usable. Without it a
message signs in indefinitely, and a future `issuedAt` extends that further.
**How to fix it.** Run the full message validation before you check the signature or the payment record: the SDK's
`validateSIWxMessage` checks `issuedAt` age and future dates, `expirationTime` and `notBefore`. Don't rewrite or drop
those fields before validating.

## R12
**What failed.** Parallel requests that carried the same payment-identifier id, each with a fresh payment, were settled
more than once, or a served answer did not name the one settlement.
**Why it matters.** A client that retries in parallel, or fans one request out, pays once per request it sent. The id
is the client's promise that these are one payment; a server that reads its record before settling and writes it only
after misses every request that arrives in between, and charges each of them.
**How to fix it.** Make the read and the write of the idempotency record one step: reserve the key (route and payment
id, bound to the payer) before anything is awaited, then let a request that finds a reservation wait for it and serve
the result with the original `PAYMENT-RESPONSE`. Drop the reservation if the request ends without a settlement, so the
next one can pay (see `ts/example/replica-server.ts`).

## R13
**What failed.** The same payment-identifier id sent to two replicas of the service, one after the other and then to
both at once, was settled more than once, or a served answer did not name the one settlement.
**Why it matters.** Behind a load balancer a retry can reach any replica. A record held in each process's memory knows
only what that replica settled, so a retry that reaches the other one is charged again.
**How to fix it.** Keep the idempotency record in a store every replica shares, with an atomic reserve as in R12, so
any replica can serve a key another one settled.

## R14
**What failed.** The probe killed your server after `/settle` succeeded and before the client got the response, started
it again and presented the same payment. Your server called `/settle` again for a payment that had already settled,
answered 402 to it (the client is asked to pay a second time for what it bought), or refused it without naming the
transaction, payment id, signature or nonce. The probe does this at two points: while `/settle` is still answering (the
server never heard that it settled) and as the first byte of the response goes out. The result's `crash_points` say
which one failed.
**Why it matters.** In the default authorization flow funds move when `/settle` succeeds (V2 §6.1), so from then on the
client has paid and your server owes it the response. A crash, a deploy or an out-of-memory kill in that window loses
the response, and the client's retry is all that's left. A server that keeps its record of the payment in memory, or
writes it only after `/settle` returns, has forgotten the payment when it comes back: it settles again (the facilitator
answers `duplicate_settlement`) and turns the client away, and the money is gone with nothing to show for it.
**How to fix it.** Persist an idempotency record before `/settle`, or atomically with it, keyed by route and by the
payment-identifier `id` (advertise the `payment-identifier` extension) or, without one, by the payment itself (the
Solana transaction signature or the EIP-3009 nonce). Write `settling` before you call `/settle`, `settled` with the
transaction and the response before you send it, and use a store that survives a restart (a database row, or a file
written, fsynced and renamed). When the same payment comes back, never settle it again: replay the stored response
(the extension's "Same `id`, same payload: Return cached response"), or, if the record is still `settling`, refuse
with a 409 that names the payment so it can be reconciled on chain. `ts/example/crash-server.ts` shows one way to do
it.

## R22
**What failed.** After a successful settle the client did not receive the handler's own 2xx status, or a header the
handler set (such as `Location` on a 201) was dropped. The result's `cases` say which route answered which status.
**Why it matters.** The client treats the paid response as the handler's response. A 201 or 202 that arrives as 200,
or a 201 whose `Location` was dropped, is a different result from the one the handler produced.
**How to fix it.** Settle, then send the handler's status and headers unchanged and add the settlement header beside
them. Do not replace a 201 or 202 with 200. A handler that answers 3xx should not be settled at all (see R15).

## R15
**What failed.** The probe paid a route whose handler answers 5xx, one that redirects (3xx) and one that throws, and
your server called `/settle` for at least one of them, or sent a `PAYMENT-RESPONSE` with it. The result's `cases`
say which.
**Why it matters.** In the default authorization flow funds move when `/settle` succeeds (V2 §6.1), and that should
happen only once the resource has been produced. A server that settles first, or treats any status below 400 as
success, charges the client for an error page, a redirect it still has to follow, or a crash.
**How to fix it.** Run the handler first and buffer its response. Call `/settle` only when it answered 2xx; for a 3xx,
4xx or 5xx, or when it throws, cancel the settlement and send the handler's response with no `PAYMENT-RESPONSE`.
`ts/example/delivery-server.ts` shows one way to do it.

## R16
**What failed.** The probe sent `HEAD` to your paid `GET` route with a valid-looking payment, and your server
answered it 2xx, called `/settle` for it, or sent a `PAYMENT-RESPONSE`.
**Why it matters.** A `HEAD` response carries no content (RFC 9110 §9.3.2). A server that settles one charges the
client for headers only, and a client or crawler that probes with `HEAD` pays for nothing.
**How to fix it.** Match `HEAD` against the `GET` route so the paywall applies, and when a `HEAD` carries a payment
answer 402 asking the client to retry as `GET`, without calling `/verify` or `/settle`.
`ts/example/head-server.ts` shows one way to do it.

## R16a
**What failed.** The probe sent an unpaid `HEAD` to your paid `GET` route. Your server neither answered it 402 with a
`PAYMENT-REQUIRED` offer nor refused it with 405; usually it answered 200, which means the protected handler ran with
no payment. (A 405 with `Allow: GET` passes: the router refuses `HEAD` before any handler runs.)
**Why it matters.** Many routers serve `HEAD` from the `GET` handler (RFC 9110 §9.3.2: the same response without the
content). A paywall that matches routes by the exact method then misses `HEAD`, and anyone can run the handler, read
its status and headers and trigger its side effects for free.
**How to fix it.** Match `HEAD` against the `GET` route in the payment layer, so an unpaid `HEAD` gets the same 402
and `PAYMENT-REQUIRED` header as `GET` and never reaches the handler, or refuse `HEAD` on paid routes with 405.
`ts/example/head-unpaid-server.ts` shows both.

## D1
**What failed.** Your facilitator's discovery API did not answer in the V2 section 8 shapes: `/discovery/resources`
lacked `x402Version`, `items` or numeric `pagination` (`limit`, `offset`, `total`), `/discovery/search` lacked
`resources`, an item lacked `resource`, `type`, `x402Version`, a complete `accepts` entry or an ISO 8601
`lastUpdated`, or the endpoint returned more items than `limit` or items off the requested `network`.
**Why it matters.** Clients and marketplaces build their catalogues from these answers. A missing field or an ignored
filter shows a buyer offers on a network they did not ask for, or prices they cannot pay, and breaks the SDK's typed
client.
**How to fix it.** Return the list as `{ x402Version: 2, items, pagination: { limit, offset, total } }` and search as
`{ x402Version: 2, resources, partialResults?, pagination? }`, with every item carrying the V2 8.3 fields and each
`accepts` entry a complete `PaymentRequirements`. Apply `limit` (1 to 100) and the `type`, `network`, `scheme` and
`payTo` filters before you page (see `ts/example/discovery-server.ts`).

## G1
**What failed.** Your agent's A2A answer to an unpaid request did not ask for the same payment as the HTTP route it
mirrors: the task was not `input-required` with `x402.payment.status: "payment-required"`, `x402.payment.required` was
missing or not a V2 `PaymentRequired`, or its `accepts` differed from the route's `PAYMENT-REQUIRED` offers.
**Why it matters.** An agent paying over A2A signs whatever the task asks for. When that differs from the HTTP price,
the same skill costs two different amounts, and a client that checks one surface is charged on the other.
**How to fix it.** Build both answers from one source: the same resource server and route configuration, so the A2A
task carries the `PaymentRequired` that `createPaymentRequiredResponse` makes for the HTTP route. Put it in the status
message's metadata, not in the text (see `ts/example/discovery-server.ts`).

## R17
**What failed.** The probe paid your route through a shared cache on loopback, then asked for the same URL with no
payment through the same cache, and got the paid content back, or the paid response carried no `Cache-Control:
private` or `no-store` and no `Vary` on the payment header, so a shared cache is allowed to store it.
**Why it matters.** A CDN, a reverse proxy or a corporate cache between your server and its clients stores any 200 it
is not told to keep out of. The first buyer's content is then served to every later caller for free, and the paywall
is gone for as long as the entry is fresh.
**How to fix it.** Send `Cache-Control: private, no-store` on every paid response (and `Vary: PAYMENT-SIGNATURE` if
you want a private cache to key on the payment). Set it in the payment layer, not in each handler, so no route can
forget it (see `ts/example/cache-server.ts`).

## R18
**What failed.** While a settlement was pending, lost or late, your server served the content before the payment was
final, or refused the request without naming the transaction, the payment id, the nonce or the signature, so the
client could not tell what it had paid for.
**Why it matters.** `settlement_pending`, a settle that times out and a settle that succeeded after you gave up all
leave you unsure whether the funds moved. Serving on a guess gives the content away when the transaction later
fails; refusing with nothing to go on leaves a buyer who did pay with no way to reconcile or retry.
**How to fix it.** On `settlement_pending`, answer 402 with the transaction and ask the client to resend the same
payment; keep retrying the same `/settle` body until it is final (F7). On a timeout, answer 402 naming the payment
(the transaction, nonce or signature you were given). When `/settle` reports success, serve once and record what you
served against the payment, so a resend is replayed from the record and a `duplicate_settlement` with no record is
refused with the payment named (see `ts/example/pending-server.ts`).

## R19
**What failed.** On a route whose offer declares `extra.paymentFlow` `upfront` or `escrow`, your server served the
content although the settle failed, answered a failed check without a reason, ran the resource before a check had
passed, or took a payment signed for a flow the route never offered.
**Why it matters.** In these flows funds move before the resource runs, so the settle is the check that gates
execution. A resource that runs first does its work, and its side effects, for a payment that may never settle. A
server that accepts a payment the client signed for another flow charges under terms the client did not agree to.
**How to fix it.** Let the payment layer run the check for the declared flow before the handler, serve only on a
passed check, and refuse a payment whose `accepted.extra.paymentFlow` is not the flow the route offered, with no
`/settle` call. The probe sees content that came back without a passing check and payments that reached `/settle`;
a resource that ran behind a refusal is visible only from inside your server, so expose an execution count to the
testing API's `executed` option and the probe grades that too (see `ts/example/flow-server.ts`).

## R20
**What failed.** The route did not answer 402 with an `exact` offer the probe could pay, so R20 graded nothing.
**Why it matters.** R20a and R20b need one paid attempt to time out and be retried.
**How to fix it.** Point `--resource` at a paid route on Solana devnet or Base Sepolia behind `X402_FACILITATOR_URL`.

## R20a
**What failed.** The client timed out before `/settle` answered and retried with a fresh payment under the same
payment-identifier id, and the retry was settled again (paid twice), or it was refused without the earlier result.
**Why it matters.** A client that gives up while settlement is in flight can't know whether it paid. If the retry is
charged again the buyer pays twice for one request; if it is only refused, the buyer paid and got nothing.
**How to fix it.** Declare the `payment-identifier` extension and keep a durable idempotency record keyed by the request
(route and payment id, bound to the payer), written after settlement with the result and its settlement. In
`onProtectedRequest`, serve a retry whose key is in the record from it, with the original `PAYMENT-RESPONSE`, and never
settle again. Key it by the request, not by the payment: a fresh payment changes the payment (see
`ts/example/retry-server.ts`).

## R20b
**What failed.** A retry that resent the same signed payment did not get the original result (the duplicate settle was
refused and the request answered 402), or a client's retry after a timeout re-signed a fresh payment with no
idempotency key.
**Why it matters.** The facilitator refuses the duplicate, so the buyer is not charged again, but without a record the
paid result is lost. A client that re-signs with no key leaves a server nothing to deduplicate on and pays twice.
**How to fix it.** Server: serve a resent payment from the idempotency record above. Client: generate one payment id per
logical request and append it in `onBeforePaymentCreation` (`appendPaymentIdentifierToExtensions`), or resend the
same `PAYMENT-SIGNATURE` on retry.

## R20c
**What failed.** The client timed out before `/settle` answered and retried with a newly signed payment under the same
payment-identifier id. The retry was settled, so the request was paid twice, or the server answered it with neither the
original result nor a clear refusal (a 409, or another 4xx whose error names the id).
**Why it matters.** The payment-identifier id names one purchase. A re-signed payment under an id the server has already
settled is the same purchase, so settling it charges the buyer twice. A refusal that doesn't say why leaves the client
unable to tell a conflict from any other error.
**How to fix it.** Keep a record keyed by the payment-identifier id, written after settlement. When a request arrives
with an id in the record and a different payment, return the recorded result with its original `PAYMENT-RESPONSE`, or
refuse it with 409 and an error that names the id. Either way, do it before the payment middleware runs, so the retry
never reaches `/settle`. R20a stays strict: a 409 refusal passes R20c and still fails R20a, because the client loses the
result it paid for. To pass both, return the recorded result to a same-id retry from the same payer (R20a above).

## U1
**What failed.** Your `upto` route asked the facilitator to settle more than the maximum the client signed: the
metered charge went to `/settle` as it was, above `permit2Authorization.permitted.amount` (EVM) or `maxAmount` (Solana).
**Why it matters.** The client authorised a ceiling, and the scheme says the settled amount must not exceed it. A
facilitator that follows the spec refuses the settle (`invalid_upto_evm_payload_settlement_exceeds_amount` on EVM),
so the work is done and nothing is paid; one that doesn't charges the client more than it agreed to.
**How to fix it.** Cap the charge at the authorised maximum before you settle: pass `min(metered, max)` as the
settlement override's `amount` (`setSettlementOverrides`, or the `amount` of `processSettlement`'s overrides), and
stop or truncate work that would cost more than the ceiling (see `ts/example/upto-server.ts`).

## U2
**What failed.** The paid response of your `upto` route didn't report what it charged: `PAYMENT-RESPONSE` had no
`amount`, or an amount other than the one the settle charged (often the authorised maximum), or another transaction.
**Why it matters.** With `upto` the client signs a ceiling and learns the price only afterwards. The `amount` in the
settlement response is how it learns what it paid; without it, or with the ceiling in its place, the client's books
are wrong and it cannot tell a fair charge from an unfair one.
**How to fix it.** Return the facilitator's settlement response unchanged in `PAYMENT-RESPONSE`: it carries the
`amount` the settle charged, `0` included. If you build the header yourself, take `amount` and `transaction` from the
settle response, never from the offer.

## U3
**What failed.** Your `upto` offer declared a payment flow the scheme doesn't allow on its network: `upfront`, or a
flow other than `authorization` for Permit2 on EVM or `escrow` for the Solana payment channel.
**Why it matters.** `upto` charges what the request used, which is known only after the handler runs, so the settle
cannot come first. A client or facilitator that follows the declared flow either refuses the payment or settles the
wrong amount at the wrong time.
**How to fix it.** Leave `extra.paymentFlow` out and let the scheme's default apply, or declare the binding's own
flow: `authorization` on EVM, `escrow` on Solana. P7 still warns when a Solana `upto` offer leaves it out, because V2
section 6.1 asks for it.

## B1
**What failed.** On your `batch-settlement` route a paid response had no commitment identifier, or reported a charge
above the per-request amount, or a valid deposit or voucher was refused, or a voucher you had already been paid with
was served again.
**Why it matters.** With `batch-settlement` the money moves later, so the commitment is the only record of what the
request paid. The scheme requires a non-empty identifier for it, and a voucher is cumulative: one that doesn't advance
the channel's charged total by the request's amount pays for nothing new, so serving it gives the content away.
**How to fix it.** Keep the channel state the binding asks for (`chargedCumulativeAmount` per channel) and accept a
voucher only when its `maxClaimableAmount` is that total plus the request's amount; answer anything else with a
corrective 402 that carries the channel state. Return `extra.commitmentId` (or the channel snapshot) and
`extra.chargedAmount` in `PAYMENT-RESPONSE` (see `ts/example/batch-server.ts`).

## B2
**What failed.** A redemption run claimed a channel more than once, or at a voucher older than its latest, or a run
with nothing new claimed vouchers again.
**Why it matters.** Vouchers are cumulative, so the latest one supersedes every earlier one. Claiming the old ones as
well sends claims that cannot advance the onchain total and fail or waste a transaction, and a batch that fails on a
stale row can take the good rows down with it.
**How to fix it.** For each channel, claim only the latest voucher above what you have already claimed, record the
claimed amount when the claim succeeds, and skip channels with nothing new.

## B3
**What failed.** Part of a redemption run failed and your server reported the failed channels as claimed, or reported
the run without an item per channel, or the next run didn't claim the failed channels again (or claimed the others
twice).
**Why it matters.** A voucher that is never claimed is revenue lost once the payer withdraws. Recording a failed batch
as claimed hides that loss, and retrying the whole run claims the good channels twice.
**How to fix it.** Track the outcome per batch and per channel: mark a channel claimed only when the claim that named
it succeeded, report each channel with its own outcome, and leave failed ones due for the next run, well inside the
withdraw delay.
## R21
**What failed.** A Permit2 payment was granted although your server's own settle failed because a third party had
already submitted the signed transfer (the facilitator answered `permit2_invalid_nonce`), or a Permit2 payment that
was already spent unlocked the resource a second time, or the content went out before the settle answered.
**Why it matters.** In the exact scheme's Permit2 method the signature names the `x402ExactPermit2Proxy` as spender,
not your facilitator, so anyone who sees the payment can settle it. The funds still reach `payTo`, but your server
did not make that settlement and cannot tell whose request it paid for. A server that reads a spent nonce as "already
paid" lets one payment, or someone else's, unlock the resource as often as it is presented.
**How to fix it.** Serve only when your own `/settle` answered success, and refuse anything else with the
facilitator's reason, `permit2_invalid_nonce` included. If you want a resent payment to get the result it paid for,
replay it from your own record of that grant (the same transaction in `PAYMENT-RESPONSE`), never from a failed settle.
Settle before you serve (see `ts/example/preempt-server.ts`).

## C4
**What failed.** After a settle, the client had not stored its own record, and a resume of the same job signed a second payment.
**Why it matters.** The job was already settled. A second signature is a second payment for the same job key.
**How to fix it.** Key the settled result by the job key and return that result on resume. Sign only when the key is absent.

## C3
**What failed.** The 402 offered V2 (the `PAYMENT-REQUIRED` header) and V1 (a V1 JSON body for the same offer), and the
client paid the V1 offer: with an `X-PAYMENT` header, or with a payment at `x402Version` 1. Or it never paid.
**Why it matters.** A client offered V2 should pay V2. A V2 payment names the offer it accepted (`accepted`, V2 §5.2.2);
a V1 payment carries only its scheme, network and payload (V1 §5.2.2), so it no longer says which requirements it pays
for. A client that reads the body first also pays whatever the body says, even when the header says something else.
**How to fix it.** Read the `PAYMENT-REQUIRED` header first and use the body only when there is no header, as the stock
`@x402/core` HTTP client does (`x402HTTPClient.getPaymentRequiredResponse`). Pay a V2 offer with `PAYMENT-SIGNATURE` at
`x402Version` 2, and keep a V1 scheme (`registerV1`) for servers that send no V2 offer at all.

If your client has no payment path by design (it hands a 402 back to its caller as an error), pass
`{ signsPayments: false }`: a client that then signs nothing is graded not applicable, not failed.

## C2
**What failed.** Given several offers, the client signed one outside its own policy: an offer on a network outside
its configured set, or one for more than its maximum amount, listed before an offer it could pay. Or it paid nothing,
although an offer within its policy was there.
**Why it matters.** The server decides what goes in `accepts` and in what order. A client that signs the first offer
pays on whatever network and for whatever amount is listed first, not what it was configured to pay. V2 leaves
spending controls to the implementation (§12.1), so the client has to enforce its own.
**How to fix it.** Filter `accepts` by your own configuration before you choose: keep offers on your configured
networks and at or below your maximum, choose among those, and pay nothing if none is left. With `@x402/core`'s
`x402Client`, register your scheme clients only for the networks you configured (registration is its network scope),
not a wildcard, and keep spend controls on with a per-payment cap (`setSpendControls({ allowedAssets: [{ network,
asset, maxAmountPerPayment }] })`, an atomic amount). `ts/example/client-offers-clients.ts` shows one way to do it.

If your client has no payment path by design (it hands a 402 back to its caller as an error), pass
`{ signsPayments: false }`: a client that then signs nothing is graded not applicable, not failed.


## C1
**What failed.** The client was answered 402 with payment requirements and handed that 402 to its caller as a
successful response: it neither paid and retried nor raised an error. This happens when the client's status check
accepts every status and its payment step only runs for statuses the check rejects.
**Why it matters.** The caller takes the payment-required answer for the resource it asked for. It gets no content and
no error, so nothing tells it the request was never paid for or served.
**How to fix it.** Run the payment step on every 402 with a `PAYMENT-REQUIRED` header before any status check, whatever
that check accepts. If the client can't or won't pay (no matching scheme, over budget), raise a payment-required error
instead of returning the 402. The stock `@x402/fetch` wrapper does this (see `ts/example/client-status-clients.ts`).

## R23
**What failed.** The probe paid your route and dropped its connection while your server's `/settle` call was in flight,
then resent the same signed payment. The payment had settled, and the resend did not get the settled result (it was
asked to pay again, refused, or answered an error), or it was settled a second time. The result's `settled_on_abort`,
`resend` and `successful_settles` say which.
**Why it matters.** Clients disconnect: a process is killed, a network drops, a user closes the tab. If settlement
finishes after the client has gone, the client has paid, and sending the same payment again is its only way back to
what it bought. A server that records the result only once the response has been delivered, or keeps no record, has
nothing to answer with: the facilitator refuses the duplicate and the purchase is lost.
**How to fix it.** Record the settled result when `/settle` succeeds (in `onAfterSettle`), not when the response is
written, keyed by route and by the payment-identifier `id` or, without one, by the payment itself, and serve a resent
payment from that record with the original `PAYMENT-RESPONSE`. A server that cancels the purchase when the client goes
away must do so before it calls `/settle`; once `/settle` has been called, the record is what makes the abort
recoverable. `ts/example/retry-server.ts` shows the record.

## R24
**What failed.** The probe sent your paid route payment headers that were not base64, base64 that was not JSON, and
JSON that was not an object. At least one got a 5xx, no answer at all (the connection was dropped), or a 4xx with no
structured error. The result's `cases` list each header with the status it got.
**Why it matters.** A malformed header is the client's mistake, so it should get a client error it can read: the HTTP
transport maps an invalid payment to 400 and a payment that is required or failed to 402. A 5xx tells the client the
server broke, invites blind retries and hides the real problem, and a header that throws inside your stack can take
the request, or the process, down with it.
**How to fix it.** Let the payment middleware decode `PAYMENT-SIGNATURE`: it answers anything it cannot decode with
402 and a `PAYMENT-REQUIRED` that names the error. If your own code reads the header first (for logging or routing),
wrap the decode and the field access in a guard and pass a malformed header on unchanged, or answer it with 400 and a
JSON body carrying `error`.

## X1
**What failed.** Called without a payment, your paid MCP tool did not answer the way the MCP transport requires: it
returned a JSON-RPC error instead of a tool result, `isError` was not `true`, `structuredContent` was missing or not a
V2 `PaymentRequired` with a resource and at least one complete offer, or `content[0].text` was not the same object
JSON-encoded.
**Why it matters.** An MCP client looks for the offer in `structuredContent` and falls back to `content[0].text`.
When neither carries it, the client cannot pay and the agent sees an opaque failure; a JSON-RPC error is treated as a
protocol fault, not as a price.
**How to fix it.** Answer an unpaid call of a paid tool with a normal tool result: `isError: true`, the
`PaymentRequired` object (`x402Version: 2`, `resource`, `accepts`) in `structuredContent`, and
`JSON.stringify(structuredContent)` as the text of `content[0]`. Build the object with the resource server's
`createPaymentRequiredResponse` so its offers match what you verify against (see `ts/example/mcp-server.ts`).

## X2
**What failed.** Your paid MCP tool returned the tool's result for a payment that was not settled: the settle never
answered, answered a broken body, was still pending, failed, or was a duplicate of a payment already settled. Or a
settled call came back without `_meta["x402/payment-response"]` naming the transaction.
**Why it matters.** The tool's output is what the caller pays for. Returning it when the settle failed, or before
it ran, gives it away for nothing and lets one payment be spent again; an agent that never sees the payment response
cannot reconcile what it was charged.
**How to fix it.** Verify, run the tool, then settle, and return the tool's content only when the settle answered a
well-formed success. On any other outcome, a timeout included, return the payment error alone as a tool result with
`isError: true`, and drop the content you computed. Put the settle response in `_meta["x402/payment-response"]` on
the result you do return (see `ts/example/mcp-server.ts`).
