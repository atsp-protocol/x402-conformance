// Profile and spec basis for every check (S, P, F and R), the same labels as spec.CATALOG in the Python package
// (tests/test_offline.py checks they match). Evidence v2 puts them on every result.
export const EVIDENCE_FORMAT = "x402-conformance-evidence/2";
export const DOCS = "https://github.com/atsp-protocol/x402-conformance/blob/main/docs/FIXES.md#";
export const CATALOG: Record<string, { profile: string; basis: string }> = {
 "S0": {
  "profile": "normative",
  "basis": "V2 7.3: GET /supported answers with a SupportedResponse"
 },
 "S1": {
  "profile": "normative",
  "basis": "V2 7.3.1 SupportedResponse: kinds, extensions, signers; V1 7.3: kinds"
 },
 "S2": {
  "profile": "normative",
  "basis": "V2 11.1: networks are CAIP-2"
 },
 "S3": {
  "profile": "normative",
  "basis": "V2 11.1 and SVM exact: Solana networks use the published CAIP-2 IDs"
 },
 "S4": {
  "profile": "normative",
  "basis": "SVM exact: extra.feePayer is the sponsor's public key"
 },
 "S5": {
  "profile": "normative",
  "basis": "V2 7.3: /supported lists the payment kinds the facilitator supports; V2 7.1: /verify answers isValid, with invalidReason when it is false"
 },
 "P1": {
  "profile": "normative",
  "basis": "V2 HTTP transport: payment required is signalled with HTTP 402"
 },
 "P2": {
  "profile": "normative",
  "basis": "V2 HTTP transport: PAYMENT-REQUIRED carries base64 JSON; V1 5.1 body"
 },
 "P3": {
  "profile": "normative",
  "basis": "V2 5.1.2: x402Version, resource and accepts are required"
 },
 "P4": {
  "profile": "normative",
  "basis": "V2 5.1.2: required accepts fields; amount in atomic token units"
 },
 "P5": {
  "profile": "normative",
  "basis": "EVM exact: extra.name and extra.version; SVM exact: extra.feePayer"
 },
 "P6": {
  "profile": "resilience",
  "basis": "The spec sets no header budget; Node fetch fails above 16 KB of headers and aiohttp near 8 KB"
 },
 "P7": {
  "profile": "normative",
  "basis": "V2 6.1: extra.paymentFlow MUST be present when the resolved flow is not authorization (a warning: the upto SVM scheme spec allows omitting it)"
 },
 "P9": {
  "profile": "normative",
  "basis": "bazaar extension, Schema Validation: schema is JSON Schema Draft 2020-12 with same-document $ref only, and facilitators MUST validate info against schema before cataloging"
 },
 "P10": {
  "profile": "resilience",
  "basis": "draft-hawkins-x402-dns-discovery 3.2: resources are HTTPS on the manifest's own host, and a manifest that diverges from the live endpoint is a misconfiguration (a warning; the runtime 402 is authoritative)"
 },
 "F1": {
  "profile": "normative",
  "basis": "V2 9 invalid_payload; V2 5.1.2 atomic units; SVM exact: fail closed"
 },
 "F2": {
  "profile": "normative",
  "basis": "SVM exact 1.1 and V2 9: an amount below the requirement is rejected"
 },
 "F3": {
  "profile": "normative",
  "basis": "SVM exact, Duplicate Settlement Mitigation: duplicate_settlement"
 },
 "F4": {
  "profile": "security-profile",
  "basis": "V2 10.1 replay prevention; one memo or nonce, one purchase"
 },
 "F5": {
  "profile": "normative",
  "basis": "V2 9: settlement_pending is non-terminal and MUST carry transaction and network"
 },
 "F6": {
  "profile": "normative",
  "basis": "Solana guide: a retry cannot settle or fulfil the same purchase twice; SVM exact: fail closed"
 },
 "F7": {
  "profile": "normative",
  "basis": "V2 9 settlement_pending: retry reaches the final outcome"
 },
 "F8": {
  "profile": "normative",
  "basis": "V2 9 invalid_transaction_state is terminal"
 },
 "F9": {
  "profile": "resilience",
  "basis": "SVM exact 2.1.2: a transient failure fails closed and stays retryable"
 },
 "F10": {
  "profile": "security-profile",
  "basis": "V2 5.1.2 and 5.2.2: a payment is verified against the requirements it was quoted under"
 },
 "F11": {
  "profile": "normative",
  "basis": "V2 7.1: /verify MUST NOT commit payment state"
 },
 "F12": {
  "profile": "security-profile",
  "basis": "V2 7.1 and 7.3: /verify checks a payment against the kinds /supported advertises; an asset is a token contract on the network"
 },
 "F13": {
  "profile": "security-profile",
  "basis": "V2 5.1.2: a payment settles the asset the requirement names; the amount and recipient alone do not bind the asset, so a different mint at the same price is a distinct payment"
 },
 "F14": {
  "profile": "security-profile",
  "basis": "V2 5.1.2 and 11.1: the verifier binds the payment's authorized network to the requirement; a payment authorized for one network is not valid against a requirement on another, even when amount, asset and payTo match (facilitator-layer network substitution)"
 },
 "F14a": {
  "profile": "security-profile",
  "basis": "EIP-712 and EVM exact (EIP-3009): a signature is bound to a chain only by the domain's chainId; an authorization signed over a domain without chainId is valid on every chain with the same token address, so the verifier requires the domain's chainId to be the requirement's network and rejects a chainless domain replayed on another network"
 },
 "F15": {
  "profile": "resilience",
  "basis": "V2 9: a non-object, empty-object or authorization-less payload is invalid_payload (HTTP 400, or isValid false), never an HTTP 5xx and never an uncaught exception"
 },
 "F16": {
  "profile": "security-profile",
  "basis": "V2 7.3 and 11.1: a facilitator registered for one testnet does not accept a requirement for a different network in the same family; a family wildcard is not a registration"
 },
 "R0": {
  "profile": "normative",
  "basis": "V2 HTTP transport: an unpaid request gets 402 with PAYMENT-REQUIRED"
 },
 "R1": {
  "profile": "normative",
  "basis": "V2 7.2: the resource server settles through its facilitator"
 },
 "R2": {
  "profile": "normative",
  "basis": "F3, F5, F6, F8 and F9 applied to a running resource server"
 },
 "R3": {
  "profile": "resilience",
  "basis": "F3, F5, F6, F8 and F9 applied to a running resource server"
 },
 "R4": {
  "profile": "resilience",
  "basis": "F3, F5, F6, F8 and F9 applied to a running resource server"
 },
 "R5": {
  "profile": "resilience",
  "basis": "F3, F5, F6, F8 and F9 applied to a running resource server"
 },
 "R6": {
  "profile": "resilience",
  "basis": "F3, F5, F6, F8 and F9 applied to a running resource server"
 },
 "R7": {
  "profile": "resilience",
  "basis": "F3, F5, F6, F8 and F9 applied to a running resource server"
 },
 "R8": {
  "profile": "normative",
  "basis": "F3, F5, F6, F8 and F9 applied to a running resource server"
 },
 "R9": {
  "profile": "normative",
  "basis": "F3, F5, F6, F8 and F9 applied to a running resource server"
 },
 "R10": {
  "profile": "normative",
  "basis": "V2 HTTP transport: settlement results go in PAYMENT-RESPONSE"
 },
 "R11": {
  "profile": "normative",
  "basis": "control: each route is served and settled once with its own payment"
 },
 "R11a": {
  "profile": "normative",
  "basis": "V2 5.2.2: accepted is matched against the route's own requirements"
 },
 "R11b": {
  "profile": "normative",
  "basis": "V2 5.1.2 and 9: recipient, asset and network must match"
 },
 "R11c": {
  "profile": "security-profile",
  "basis": "a route priced by method is priced for the method used"
 },
 "R11d": {
  "profile": "security-profile",
  "basis": "a route priced by query is priced for the query sent"
 },
 "R11e": {
  "profile": "security-profile",
  "basis": "payment middleware and framework must agree on the path"
 },
 "R11f": {
  "profile": "security-profile",
  "basis": "sign-in-with-x: access is for the requested resource the server priced and settled"
 },
 "W1": {
  "profile": "normative",
  "basis": "sign-in-with-x: domain MUST match the server's configured public origin host and the uri origin MUST match that origin, derived from the server's configuration, not from request headers such as Host"
 },
 "W2": {
  "profile": "security-profile",
  "basis": "sign-in-with-x: the nonce MUST be unique and the server SHOULD track used nonces, so one signed message signs in once"
 },
 "W3": {
  "profile": "normative",
  "basis": "sign-in-with-x: issuedAt MUST be recent (under five minutes) and MUST NOT be in the future, and a present expirationTime MUST be in the future"
 },
 "R12": {
  "profile": "security-profile",
  "basis": "payment-identifier: the id is an idempotency key that deduplicates requests, so parallel requests with one id are charged once"
 },
 "R13": {
  "profile": "resilience",
  "basis": "payment-identifier: the id deduplicates requests for the service, not per process, so its replicas charge one id once"
 },
 "R14": {
  "profile": "resilience",
  "basis": "payment-identifier: same id, same payload returns the cached response; V2 6.1: in the authorization flow funds move only after the resource completes; V2 9: a transaction is surfaced so the caller can reconcile"
 },
 "R15": {
  "profile": "normative",
  "basis": "V2 6.1: in the authorization flow funds move only after the resource completes successfully; a failed, redirected or thrown request is not settled"
 },
 "R16": {
  "profile": "security-profile",
  "basis": "RFC 9110 9.3.2: a HEAD response carries no content, so a HEAD carrying a payment has nothing to deliver and is not settled"
 },
 "R16a": {
  "profile": "security-profile",
  "basis": "the paywall covers every method that reaches the protected handler: RFC 9110 9.3.2 HEAD is GET without the content, so an unpaid HEAD is answered 402"
 },
 "D1": {
  "profile": "normative",
  "basis": "V2 8 and the bazaar extension: GET /discovery/resources returns x402Version, items and pagination (limit, offset, total), GET /discovery/search returns resources; every item has resource, type, x402Version, accepts and lastUpdated (8.3), and limit and the network filter are honoured"
 },
 "G1": {
  "profile": "security-profile",
  "basis": "A2A transport: payment required is a task in input-required with x402.payment.status payment-required and the PaymentRequired in x402.payment.required; an agent that mirrors an HTTP route asks for the same requirements as its 402"
 },
 "R17": {
  "profile": "security-profile",
  "basis": "RFC 9111: a shared cache may store a 200 that is not private or no-store and does not vary on the request header that decided it, so a paid response must say so or the next caller gets it for free"
 },
 "R18": {
  "profile": "resilience",
  "basis": "V2 9: settlement_pending carries the transaction so the caller can reconcile; a pending, late or unanswered settlement ends served once after it is final, or refused with the payment surfaced"
 },
 "R19": {
  "profile": "normative",
  "basis": "V2 6.1: at least one check MUST run before the resource executes, and a server MUST reject an unsupported flow; on an upfront or escrow offer the check that gates execution is the settle"
 },
 "R20": {
  "profile": "security-profile",
  "basis": "control: the route answers 402 with an exact offer the probe can pay"
 },
 "R20a": {
  "profile": "security-profile",
  "basis": "payment-identifier: a retry with the same id and a fresh payment is not charged again"
 },
 "R20b": {
  "profile": "security-profile",
  "basis": "a retry resending the same signed payment is settled once and gets the original result"
 },
 "R21": {
  "profile": "security-profile",
  "basis": "EVM exact Permit2: the signed transfer names the x402ExactPermit2Proxy as spender, so anyone holding it can submit it first; a server grants only on a settlement it made, and a spent nonce never unlocks the resource again"
 },
 "C3": {
  "profile": "security-profile",
  "basis": "V2 HTTP transport: PAYMENT-REQUIRED is canonical; V2 5.2.2 accepted is Required, and a V1 payload (V1 5.2.2) has none"
 },
 "C2": {
  "profile": "security-profile",
  "basis": "given several offers a client pays one within its own networks and maximum amount, not the first; V2 12.1: spending controls are implementation-specific"
 },
 "C1": {
  "profile": "security-profile",
  "basis": "V2 4 and HTTP transport: a 402 is Payment Required or Payment Failed, not Success, so a client pays and retries or raises an error"
 },
 "C4": {
  "profile": "security-profile",
  "basis": "a client that resumes after a crash between settle and its own record reuses the settled result and does not sign a second payment for the same job key"
 },
 "R23": {
  "profile": "security-profile",
  "basis": "a client that disconnects while /settle is in flight is not charged, or a resend of the same payment gets the settled result and is not charged again"
 },
 "R24": {
  "profile": "resilience",
  "basis": "V2 HTTP transport, Error Handling: Invalid Payment (a malformed payment payload) is 400, Payment Required and Payment Failed are 402, and Server Error (500) is for the server's own failures"
 },
 "R22": {
  "profile": "normative",
  "basis": "after a successful settle the client receives the handler's own 2xx status code and headers, such as Location; a 201 stays a 201 and a 202 stays a 202, never a rewritten 200; a paid 3xx is not settled (R15)"
 },
 "U1": {
  "profile": "normative",
  "basis": "upto, Core Property 4: the settled amount MUST be less than or equal to the authorized maximum; the settle-time requirements.amount is the actual charge (Core Property 5)"
 },
 "U2": {
  "profile": "normative",
  "basis": "upto SettlementResponse: amount, the actual amount charged in atomic units (may be 0), is required on EVM and on Solana"
 },
 "U3": {
  "profile": "normative",
  "basis": "upto, Payment Flow: upto cannot use upfront, because the amount is known only after the handler runs; Permit2 on EVM supports authorization, the Solana channel escrow (V2 6.1 extra.paymentFlow, as P7)"
 },
 "B1": {
  "profile": "normative",
  "basis": "batch-settlement: the settlement result MUST include a non-empty commitment identifier on success, the charge is at most the per-request amount, and the same authorization MUST NOT execute the handler twice"
 },
 "B2": {
  "profile": "security-profile",
  "basis": "batch-settlement redemption: the server claims each channel's latest cumulative voucher, which supersedes the older ones, and a claim cannot advance accounting twice"
 },
 "B3": {
  "profile": "resilience",
  "basis": "batch-settlement redemption in batches: a channel is not silently dropped from a batch, and a voucher whose claim failed stays claimable, so a partly failed run is reported and retried per item"
 },
 "X1": {
  "profile": "normative",
  "basis": "MCP transport: a paid tool called without a payment MUST answer a tool result with isError true, the PaymentRequired object in structuredContent and the same object JSON-encoded in content[0].text"
 },
 "X2": {
  "profile": "resilience",
  "basis": "MCP transport: the server verifies, runs the tool and settles, and when the settle fails it returns only the payment error, never the tool's content; the R0-R10 faults on a paid tool call"
 }
};

/** The check id ("R11a") from a result's check text. */
export const checkId = (check: string): string => check.split(" ")[0].replace(/:$/, "");

/** A result labelled with its profile, spec basis and where to read the fix. */
export function label<T extends { check: string }>(r: T): T & { profile: string; basis: string; fix: string } {
  const id = checkId(r.check);
  const e = CATALOG[id] ?? { profile: "normative", basis: "" };
  return { ...r, profile: e.profile, basis: e.basis, fix: DOCS + id.toLowerCase() };
}
