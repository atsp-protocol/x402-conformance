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
