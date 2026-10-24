"""Identifiers quoted from the x402 V2 specification (specs/x402-specification-v2.md), the Solana `exact` scheme
(specs/schemes/exact/scheme_exact_svm.md) and https://solana.com/docs/payments/agentic-payments/x402.
Read on 2026-10-20 at x402-foundation/x402 commit 0e6e8c55d86b4f14234fb6e49a4052074fb93e57."""

from __future__ import annotations

import re
from typing import Final

X402_VERSION: Final = 2
SOLANA_MAINNET: Final = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
SOLANA_DEVNET: Final = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"
SOLANA_DEVNET_USDC: Final = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"
# V1 network names. V2 kinds must use CAIP-2 instead.
SOLANA_V1_NAMES: Final = frozenset({"solana", "solana-devnet", "solana-mainnet", "solana-testnet"})
# V1 EVM network names (V1 used names, not CAIP-2).
EVM_V1_NAMES: Final = frozenset({"base", "base-sepolia", "avalanche", "avalanche-fuji", "polygon", "polygon-amoy",
                                 "ethereum", "sepolia", "iotex", "sei", "sei-testnet"})
# \Z, not $: in Python $ also matches before a trailing newline, which the TypeScript port (and JSON) do not allow.
CAIP2: Final = re.compile(r"^[-a-z0-9]{3,8}:[-_a-zA-Z0-9]{1,32}\Z")
SETTLEMENT_PENDING: Final = "settlement_pending"      # V2 section 9, non-terminal
DUPLICATE_SETTLEMENT: Final = "duplicate_settlement"  # SVM exact, Duplicate Settlement Mitigation
INVALID_TRANSACTION_STATE: Final = "invalid_transaction_state"  # V2 section 9, the transaction failed on chain
_B58: Final = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        i = _B58.find(ch)
        if i < 0:
            raise ValueError("not base58")
        n = n * 58 + i
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\0" * (len(s) - len(s.lstrip("1"))) + raw


def is_solana_pubkey(s: object) -> bool:
    if not isinstance(s, str) or not 32 <= len(s) <= 44:
        return False
    try:
        return len(b58decode(s)) == 32
    except ValueError:
        return False


# ---------------- the check catalog: profile, spec basis, controls and faulty builds ----------------
# Every check the suite runs has an entry. "profile" says what a failure means: normative (the spec says MUST or
# REQUIRED), security-profile (the spec is silent or permissive, and a public, reproduced failure shows money or
# content lost) or resilience (interoperability and recovery under real limits). "controls" are tests that show a
# legitimate implementation passes; "faulty" are the deliberately broken builds the check is proven to catch:
#   py:<module.Class.test>  a Python test       fault:<name>  a facilitator double in mock.FAULTS
#   guard:<name>  a resource-server guard in harness.GUARD_FAULTS       ts:<title>  a test in ts/test/*.test.ts
# tests.test_offline.Offline.test_credibility_matrix_complete fails the build if any entry lacks either, or if a
# referenced test or faulty build doesn't exist or doesn't make its check fail.
PROFILES: Final = ("normative", "security-profile", "resilience")
EVIDENCE_FORMAT: Final = "x402-conformance-evidence/2"
_LIVE = "py:tests.test_live.Live."
_OFF = "py:tests.test_offline.Offline."
_TS_OK = "ts:the example server passes R0-R10"
_TS_STOCK = "ts:a stock @x402/express server with default settings passes every check"
_TS_BIND = "ts:R11 control: the stock @x402/express server passes R11"
_TS_RETRY = "ts:R20a control: the stock @x402/express server with an idempotency record"
CATALOG: Final[dict[str, dict[str, object]]] = {
    "S0": {"profile": "normative", "basis": "V2 7.3: GET /supported answers with a SupportedResponse",
           "controls": [_LIVE + "test_s_all_pass_on_conformant_body"], "faulty": [_LIVE + "test_s0_unreachable_is_a_check"]},
    "S1": {"profile": "normative", "basis": "V2 7.3.1 SupportedResponse: kinds, extensions, signers; V1 7.3: kinds",
           "controls": [_LIVE + "test_s_all_pass_on_conformant_body", _LIVE + "test_s1_v1_only_response_graded_as_v1"],
           "faulty": [_LIVE + "test_s1_shape", _LIVE + "test_s1_mixed_versions_need_v2_shape"]},
    "S2": {"profile": "normative", "basis": "V2 11.1: networks are CAIP-2",
           "controls": [_LIVE + "test_s_all_pass_on_conformant_body"], "faulty": [_LIVE + "test_s2_non_caip2"]},
    "S3": {"profile": "normative", "basis": "V2 11.1 and SVM exact: Solana networks use the published CAIP-2 IDs",
           "controls": [_LIVE + "test_s_all_pass_on_conformant_body"], "faulty": [_LIVE + "test_s3_v1_name_in_v2"]},
    "S4": {"profile": "normative", "basis": "SVM exact: extra.feePayer is the sponsor's public key",
           "controls": [_LIVE + "test_s_all_pass_on_conformant_body", _LIVE + "test_s4_exact_network_signer_key"],
           "faulty": [_LIVE + "test_s4_bad_fee_payer", _LIVE + "test_s4_fee_payer_not_signer"]},
    "S5": {"profile": "normative",
           "basis": "V2 7.3: /supported lists the payment kinds the facilitator supports; V2 7.1: /verify answers "
                    "isValid, with invalidReason when it is false",
           "controls": [_OFF + "test_s5_reference_answers_every_advertised_kind"],
           "faulty": ["fault:advertise_unhandled", "fault:reasonless_invalid"]},
    "P1": {"profile": "normative", "basis": "V2 HTTP transport: payment required is signalled with HTTP 402",
           "controls": [_LIVE + "test_p_all_pass_on_spec_example"], "faulty": [_LIVE + "test_p1_served_without_payment"]},
    "P2": {"profile": "normative", "basis": "V2 HTTP transport: PAYMENT-REQUIRED carries base64 JSON; V1 5.1 body",
           "controls": [_LIVE + "test_p_all_pass_on_spec_example", _LIVE + "test_p_v1_body_graded_as_v1"],
           "faulty": [_LIVE + "test_p2_missing_header"]},
    "P3": {"profile": "normative", "basis": "V2 5.1.2: x402Version, resource and accepts are required",
           "controls": [_LIVE + "test_p_all_pass_on_spec_example"], "faulty": [_LIVE + "test_p3_p4_p5_field_problems"]},
    "P4": {"profile": "normative", "basis": "V2 5.1.2: required accepts fields; amount in atomic token units",
           "controls": [_LIVE + "test_p_all_pass_on_spec_example"], "faulty": [_LIVE + "test_p3_p4_p5_field_problems"]},
    "P5": {"profile": "normative", "basis": "EVM exact: extra.name and extra.version; SVM exact: extra.feePayer",
           "controls": [_LIVE + "test_p_all_pass_on_spec_example"],
           "faulty": [_LIVE + "test_p3_p4_p5_field_problems", _LIVE + "test_p_svm_needs_fee_payer"]},
    "P6": {"profile": "resilience", "upstream": "x402-foundation/x402#3803",
           "basis": "The spec sets no header budget; Node fetch fails above 16 KB of headers and aiohttp near 8 KB",
           "controls": [_LIVE + "test_p_all_pass_on_spec_example"], "faulty": [_LIVE + "test_p6_header_budget"]},
    "P7": {"profile": "normative", "basis": "V2 6.1: extra.paymentFlow MUST be present when the resolved flow is not "
           "authorization (a warning: the upto SVM scheme spec allows omitting it)",
           "controls": [_LIVE + "test_p_all_pass_on_spec_example"], "faulty": [_LIVE + "test_p7_payment_flow_declared"]},
    "F1": {"profile": "normative", "basis": "V2 9 invalid_payload; V2 5.1.2 atomic units; SVM exact: fail closed",
           "controls": [_OFF + "test_reference_passes_all"], "faulty": ["fault:open_on_malformed", "fault:lenient_amounts"]},
    "F2": {"profile": "normative", "basis": "SVM exact 1.1 and V2 9: an amount below the requirement is rejected",
           "controls": [_OFF + "test_reference_passes_all"], "faulty": ["fault:accept_dust"]},
    "F3": {"profile": "normative", "basis": "SVM exact, Duplicate Settlement Mitigation: duplicate_settlement",
           "controls": [_OFF + "test_reference_passes_all"], "faulty": ["fault:no_dup_cache"]},
    "F4": {"profile": "security-profile", "basis": "V2 10.1 replay prevention; one memo or nonce, one purchase",
           "controls": [_OFF + "test_reference_passes_all"], "faulty": ["fault:no_memo_check"]},
    "F5": {"profile": "normative", "basis": "V2 9: settlement_pending is non-terminal and MUST carry transaction and "
           "network", "controls": [_OFF + "test_reference_passes_all"],
           "faulty": ["fault:success_before_final", "fault:pending_without_tx"]},
    "F6": {"profile": "normative", "basis": "Solana guide: a retry cannot settle or fulfil the same purchase twice; "
           "SVM exact: fail closed", "controls": [_OFF + "test_f6_guard_fails_closed_and_credits_once"],
           "faulty": ["guard:guard_credit_on_error"]},
    "F7": {"profile": "normative", "basis": "V2 9 settlement_pending: retry reaches the final outcome",
           "controls": [_OFF + "test_reference_pending_retry_reaches_final_and_credits_once"],
           "faulty": ["fault:burn_on_pending"]},
    "F8": {"profile": "normative", "basis": "V2 9 invalid_transaction_state is terminal",
           "controls": [_OFF + "test_reference_failure_after_pending_is_terminal"], "faulty": ["fault:stuck_pending"]},
    "F9": {"profile": "resilience", "basis": "SVM exact 2.1.2: a transient failure fails closed and stays retryable",
           "controls": [_OFF + "test_guard_never_credits_503_non_json_or_truncated_and_retries"],
           "faulty": ["guard:guard_trust_any_status", "guard:guard_give_up_after_error"]},
    "F10": {"profile": "security-profile", "basis": "V2 5.1.2 and 5.2.2: a payment is verified against the "
            "requirements it was quoted under", "controls": [_OFF + "test_f10_reference_binding_passes"],
            "faulty": ["fault:cross_request_replay"]},
    "F11": {"profile": "normative", "basis": "V2 7.1: /verify MUST NOT commit payment state",
            "controls": [_OFF + "test_reference_passes_all"], "faulty": ["fault:verify_commits"]},
    "F12": {"profile": "security-profile",
            "basis": "V2 7.1 and 7.3: /verify checks a payment against the kinds /supported advertises; an asset is a "
                     "token contract on the network",
            "controls": [_OFF + "test_f12_reference_rejects_unsupported_network_and_asset"],
            "faulty": ["fault:trust_kind"]},
    "F13": {"profile": "security-profile",
            "basis": "V2 5.1.2: a payment settles the asset the requirement names; the amount and recipient "
                     "alone do not bind the asset, so a different mint at the same price is a distinct payment",
            "controls": [_OFF + "test_f13_reference_rejects_asset_substitution"],
            "faulty": ["fault:trust_asset"]},
    "F14": {"profile": "security-profile",
            "basis": "V2 5.1.2 and 11.1: the verifier binds the payment's authorized network to the requirement; a "
                     "payment authorized for one network is not valid against a requirement on another, even when "
                     "amount, asset and payTo match (facilitator-layer network substitution)",
            "controls": [_OFF + "test_f14_reference_rejects_network_substitution"],
            "faulty": ["fault:trust_network"]},
    "R0": {"profile": "normative", "basis": "V2 HTTP transport: an unpaid request gets 402 with PAYMENT-REQUIRED",
           "controls": [_TS_OK, _TS_STOCK], "faulty": ["ts:a server that serves without payment is caught"]},
    "R1": {"profile": "normative", "basis": "V2 7.2: the resource server settles through its facilitator",
           "controls": [_TS_OK, _TS_STOCK], "faulty": ["ts:a server that is not using the double fails R1"]},
    **{f"R{i}": {"profile": "normative" if i in (2, 8, 9) else "resilience",
                 "basis": "F3, F5, F6, F8 and F9 applied to a running resource server",
                 "controls": [_TS_OK, _TS_STOCK],
                 "faulty": ["ts:a server that serves after /verify and ignores /settle is caught",
                            "ts:a server that serves whatever /settle answers is caught"]} for i in range(2, 10)},
    "R10": {"profile": "normative", "basis": "V2 HTTP transport: settlement results go in PAYMENT-RESPONSE",
            "controls": [_TS_OK, _TS_STOCK], "faulty": ["ts:a server that serves without PAYMENT-RESPONSE is caught"]},
    "R11": {"profile": "normative", "basis": "control: each route is served and settled once with its own payment",
            "controls": [_TS_BIND], "faulty": ["ts:R11 control: a server that never serves a paid route is caught"]},
    "R11a": {"profile": "normative", "basis": "V2 5.2.2: accepted is matched against the route's own requirements",
             "controls": [_TS_BIND], "faulty": ["ts:R11a R11b: a server that settles against the client's"]},
    "R11b": {"profile": "normative", "basis": "V2 5.1.2 and 9: recipient, asset and network must match",
             "controls": [_TS_BIND], "faulty": ["ts:R11a R11b: a server that settles against the client's"]},
    "R11c": {"profile": "security-profile", "basis": "a route priced by method is priced for the method used",
             "controls": [_TS_BIND], "faulty": ["ts:R11c R11d: a server that prices from the client's"]},
    "R11d": {"profile": "security-profile", "basis": "a route priced by query is priced for the query sent",
             "controls": [_TS_BIND], "faulty": ["ts:R11c R11d: a server that prices from the client's"]},
    "R11e": {"profile": "security-profile", "basis": "payment middleware and framework must agree on the path",
             "controls": [_TS_BIND], "faulty": ["ts:R11e: a server whose route matching sees the decoded path"]},
    "R11f": {"profile": "security-profile", "upstream": "x402-foundation/x402#3838",
             "basis": "sign-in-with-x: access is for the requested resource the server priced and settled",
             "controls": ["ts:R11f control: a SIWX server that records the settled route passes"],
             "faulty": ["ts:R11f: a SIWX server that records the client's resource.url is caught"]},
    "R12": {"profile": "security-profile",
            "basis": "payment-identifier: the id is an idempotency key that deduplicates requests, so parallel "
                     "requests with one id are charged once",
            "controls": ["ts:R12 control: a record that reserves the key before it awaits"],
            "faulty": ["ts:R12 catches a non-atomic check-then-set"]},
    "R13": {"profile": "resilience",
            "basis": "payment-identifier: the id deduplicates requests for the service, not per process, so its "
                     "replicas charge one id once",
            "controls": ["ts:R13 control: two replicas sharing one record"],
            "faulty": ["ts:R13 catches a per-process in-memory cache"]},
    "R14": {"profile": "resilience",
            "basis": "payment-identifier: same id, same payload returns the cached response; V2 6.1: in the "
                     "authorization flow funds move only after the resource completes; V2 9: a transaction is "
                     "surfaced so the caller can reconcile",
            "controls": ["ts:R14 control: a server with a durable idempotency record passes"],
            "faulty": ["ts:R14 catches a server whose idempotency record is in memory only",
                       "ts:R14 catches a server that writes its record only after /settle returns",
                       "ts:R14 catches a server that refuses after a restart without surfacing the payment"]},
    "R15": {"profile": "normative",
            "basis": "V2 6.1: in the authorization flow funds move only after the resource completes successfully; a "
                     "failed, redirected or thrown request is not settled",
            "controls": ["ts:R15 control: a server that settles only after a 2xx charges nothing"],
            "faulty": ["ts:R15 catches a server that settles before the handler runs (settle_first)",
                       "ts:R15 catches a server that settles anything below 400"]},
    "R16": {"profile": "security-profile",
            "basis": "RFC 9110 9.3.2: a HEAD response carries no content, so a HEAD carrying a payment has nothing to "
                     "deliver and is not settled",
            "controls": ["ts:R16 control: a server that refuses a paid HEAD with a 402 and settles nothing passes"],
            "faulty": ["ts:R16 catches a server that settles a paid HEAD as if it were a GET (head_settles)"]},
    "R16a": {"profile": "security-profile",
            "basis": "the paywall covers every method that reaches the protected handler: RFC 9110 9.3.2 HEAD is GET "
                     "without the content, so an unpaid HEAD is answered 402",
            "controls": ["ts:R16a control: a paywall that covers HEAD answers it 402"],
            "faulty": ["ts:R16a catches a paywall that matches only GET"]},
    "R17": {"profile": "security-profile",
           "basis": "RFC 9111: a shared cache may store a 200 that is not private or no-store and does not vary on "
           "the request header that decided it, so a paid response must say so or the next caller gets it "
           "for free",
           "controls": ["ts:R17 control: a server that marks paid responses private, no-store leaks nothing"],
           "faulty": ["ts:R17 catches a server whose paid response is public and cacheable",
                      "ts:R17 catches a server that says nothing about caching"]},
    "R18": {"profile": "resilience",
           "basis": "V2 9: settlement_pending carries the transaction so the caller can reconcile; a pending, late "
           "or unanswered settlement ends served once after it is final, or refused with the payment "
           "surfaced",
           "controls": ["ts:R18 control: a server that refuses while pending, names the payment, and serves once when final"],
           "faulty": ["ts:R18 catches a server that serves on settlement_pending",
                      "ts:R18 catches a server that refuses a pending or lost settlement without naming the payment"]},
    "R19": {"profile": "normative",
           "basis": "V2 6.1: at least one check MUST run before the resource executes, and a server MUST reject an "
           "unsupported flow; on an upfront or escrow offer the check that gates execution is the settle",
           "controls": ["ts:R19 control: an upfront route that settles before the handler runs it once"],
           "faulty": ["ts:R19 catches a server that runs the handler before any check",
                      "ts:R19 catches a server that takes a payment signed for a flow it never offered"]},
    "R20": {"profile": "security-profile", "basis": "control: the route answers 402 with an exact offer the probe can pay",
            "controls": [_TS_RETRY], "faulty": ["ts:R20 control: a URL that is not a paid route fails the control"]},
    "R20a": {"profile": "security-profile",
             "basis": "payment-identifier: a retry with the same id and a fresh payment is not charged again",
             "controls": [_TS_RETRY], "faulty": ["ts:R20a settle_both: a server with no idempotency record",
                                                 "ts:R20a key_by_payment: a record keyed by the payment"]},
    "R20b": {"profile": "security-profile",
             "basis": "a retry resending the same signed payment is settled once and gets the original result",
             "controls": [_TS_RETRY, "ts:R20b client control: the stock @x402/fetch client"],
             "faulty": ["ts:R20b settle_both: with no record", "ts:R20b client resign_on_timeout"]},
    "C3": {"profile": "security-profile",
           "basis": "V2 HTTP transport: PAYMENT-REQUIRED is canonical; V2 5.2.2 accepted is Required, and a V1 payload "
                    "(V1 5.2.2) has none",
           "controls": ["ts:C3 control: the stock @x402/fetch client pays with V2 when the 402 also carries a V1 body"],
           "faulty": ["ts:C3 v1_fallback: a client that pays the V1 offer when V2 is present is caught"]},
    "C2": {"profile": "security-profile",
           "basis": "given several offers a client pays one within its own networks and maximum amount, not the first; "
                    "V2 12.1: spending controls are implementation-specific",
           "controls": ["ts:C2 control: the stock x402Client pays the offer within its networks and maximum"],
           "faulty": ["ts:C2 first_offer: a client that signs the first offer outside its policy is caught",
                      "ts:C2 ignore_max: a client that signs an offer above its maximum is caught"]},
    "C1": {"profile": "security-profile",
           "basis": "V2 4 and HTTP transport: a 402 is Payment Required or Payment Failed, not Success, so a client "
                    "pays and retries or raises an error",
           "controls": ["ts:C1 control: the stock @x402/fetch client pays the 402 and gets the content",
                        "ts:C1 control: a stock @x402/fetch client whose policy declines the price rejects",
                        "ts:C1 control: a client whose status check passes every status but pays a 402 before the check"],
           "faulty": ["ts:C1 accept_any_status: a client whose status check passes 402 through unpaid is caught",
                      "ts:C1 gate: a URL that is not a paid route fails the check",
                      "ts:C1 gate: a client that rejects before it receives a 402 does not pass"]},
    "R23": {"profile": "security-profile",
            "basis": "a client that disconnects while /settle is in flight is not charged, or a resend of the same "
                     "payment gets the settled result and is not charged again",
            "controls": ["ts:R23 control: the stock @x402/express server with an idempotency record"],
            "faulty": ["ts:R23 record_on_delivery: a server that records the result only once the response",
                       "ts:R23 settle_both: a server with no idempotency record"]},
    "R24": {"profile": "resilience",
            "basis": "V2 HTTP transport, Error Handling: Invalid Payment (a malformed payment payload) is 400, "
                     "Payment Required and Payment Failed are 402, and Server Error (500) is for the server's own failures",
            "controls": ["ts:R24 control: the stock @x402/express server answers every malformed payment header"],
            "faulty": ["ts:R24 decode_unchecked: a server that throws on a malformed payment header",
                       "ts:R24 drop_on_bad_header: a server that drops the connection",
                       "ts:R24 gate: a URL that is not a paid route fails and grades nothing"]},
    "R22": {"profile": "normative",
            "basis": "after a successful settle the client receives the handler's own 2xx status code and headers, "
                     "such as Location; a 201 stays a 201 and a 202 stays a 202, never a rewritten 200; "
                     "a paid 3xx is not settled (R15)",
            "controls": ["ts:R22 control: a server that returns the handler status"],
            "faulty": ["ts:R22 catches a server that rewrites the paid response to 200",
                       "ts:R22 gate: a 3xx expectation is refused and nothing is paid"]},
}
