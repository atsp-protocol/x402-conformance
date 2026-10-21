# Check specification

Each check below quotes the spec text it tests. Sources were read on 2026-10-20 at x402-foundation/x402 commit
`0e6e8c55d86b4f14234fb6e49a4052074fb93e57`: `specs/x402-specification-v2.md` (V2), `specs/x402-specification-v1.md`
(V1), `specs/transports-v2/http.md` (V2 HTTP transport), `specs/schemes/exact/scheme_exact_svm.md` (SVM exact) and
`specs/schemes/exact/scheme_exact_evm.md` (EVM exact). The Solana guide is
https://solana.com/docs/payments/agentic-payments/x402.

[FIXES.md](FIXES.md) explains, for each check, what a failure means and how to fix it.

These checks map behaviour to spec text. Passing them is evidence about specific properties. It is not
certification of conformance to x402.

| id | property | spec text | test |
|---|---|---|---|
| S0 | `GET /supported` answers HTTP 200 with a JSON object | V2 §7.3 "Returns the list of payment schemes, networks, and extensions supported by the facilitator" | `tests.test_live.Live.test_s0_unreachable_is_a_check`, `test_s0_401_hints_at_credentials` |
| S1 | `GET /supported` returns `kinds[]`, `extensions[]` and `signers{}` | V2 §7.3.1 SupportedResponse fields: `kinds` array (required), `extensions` array (required), `signers` object (required), "Map of CAIP-2 patterns ... to public signer addresses". A V1-only response is graded against V1 §7.3 (`kinds` only) | `tests.test_live.Live.test_s1_shape`, `test_s1_v1_only_response_graded_as_v1`, `test_s1_mixed_versions_need_v2_shape` |
| S2 | Every `x402Version: 2` kind names its network in CAIP-2 | V2 §11.1 "Networks in x402 v2 use CAIP-2 ... format: `namespace:reference`" | `tests.test_live.Live.test_s2_non_caip2` |
| S3 | Solana V2 kinds use the published IDs | Solana guide: Mainnet `solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp`, Devnet `solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1`; "V1 integrations used ... network names such as `solana-devnet`. Do not use those V1 fields in a new integration." | `tests.test_live.Live.test_s3_v1_name_in_v2` |
| S4 | Solana `exact` kinds advertise a valid `extra.feePayer` (error); it is listed as a signer (warning, inferred) | SVM exact: "`extra.feePayer`: The sponsor's public key"; V2 §7.3.1 `signers` | `tests.test_live.Live.test_s4_bad_fee_payer`, `test_s4_fee_payer_not_signer`, `test_s4_not_signer_is_a_warning_and_missing_fee_payer_an_error` |
| F1 | Malformed input fails closed | V2 §9 `invalid_payload`; SVM exact §2.1.2 "A transient failure ... MUST fail closed (reject / retryable), never open" | `tests.test_offline.Offline.test_f1_open_on_malformed_caught` |
| F2 | Dust and underpayment are rejected | SVM exact §1.1 "A transfer of at least `PaymentRequirements.amount`"; §1.4 "it MUST NOT be less" | `tests.test_offline.Offline.test_f2_accept_dust_caught` |
| F3 | The same payload settled twice succeeds at most once | SVM exact, Duplicate Settlement Mitigation: "if the key is already present in the cache, reject the settlement with a `\"duplicate_settlement\"` error" | `tests.test_offline.Offline.test_f3_no_dup_cache_caught` |
| F4 | Replaying a used memo or nonce in a new transaction is rejected | SVM exact §3.1 "The Memo instruction ensures transaction uniqueness"; Solana guide "The authorization is unexpired and has not been replayed" | `tests.test_offline.Offline.test_f4_no_memo_check_caught` |
| F5 | Nothing counts as settled before confirmation, and `settlement_pending` carries a transaction | V2 §9 `settlement_pending` is "non-terminal" and "MUST carry a non-empty `transaction`"; SVM invariant I3 "Settlement success returned only after confirming actual on-chain effects" | `tests.test_offline.Offline.test_f5_success_before_final_caught` |
| F6 | A facilitator timeout or malformed response never becomes a credit | Solana guide: "A retry cannot settle or fulfill the same purchase twice"; "Settlement reaches the confirmation level required before fulfillment" | `tests.test_offline.Offline.test_f6_guard_fails_closed_and_credits_once` |
| F7 | A `settlement_pending` settle retried with the same body reaches its final result, the same transaction on success, and is credited exactly once | V2 §9 `settlement_pending`: "Facilitators MAY return this **non-terminal** code — the transaction may still confirm on chain" and the caller can "reconcile on chain before deciding whether to retry"; Solana guide "A retry cannot settle or fulfill the same purchase twice" | `tests.test_offline.Offline.test_f7_burn_on_pending_caught`, `test_reference_pending_retry_reaches_final_and_credits_once` |
| F8 | A failure confirmed on chain after `settlement_pending` is terminal and is never reported as pending again | V2 §9 `invalid_transaction_state`: "Blockchain transaction failed or was rejected"; `settlement_pending` is for when "confirmation could not be established" | `tests.test_offline.Offline.test_f8_stuck_pending_caught`, `test_reference_failure_after_pending_is_terminal` |
| F9 | A 503, a non-JSON page or a truncated `/settle` body never becomes a credit, and the payment stays retryable until a well-formed answer credits it once | SVM exact §2.1.2 "A transient failure ... MUST fail closed (reject / retryable), never open"; Solana guide "A retry cannot settle or fulfill the same purchase twice" | `tests.test_offline.Offline.test_f9_guard_trusting_a_503_caught`, `test_f9_guard_that_never_retries_caught`, `test_guard_never_credits_503_non_json_or_truncated_and_retries` |

| F10 | A payload settled against one PaymentRequirements set is rejected when the same verifier is asked to accept it under different requirements — amount escalation, recipient substitution, or resource substitution (cross-request replay) | The exact scheme binds amount, asset and `payTo` on chain and the memo binds nonce uniqueness; no scheme field binds the protected resource, so the verifier records the requirements hash each transaction was verified under and refuses the same transaction against a different hash. Fail closed on missing or malformed requirements | `tests.test_offline.Offline.test_f10_cross_request_replay_caught`, `test_reference_rejects_amount_escalation`, `test_reference_rejects_recipient_substitution`, `test_reference_rejects_resource_substitution`, `test_verify_fails_closed_on_malformed_requirements` |
| P1 | An unpaid request to a paid URL answers HTTP 402 | V2 HTTP transport: "The server indicates payment is required using the HTTP 402 \"Payment Required\" status code" | `tests.test_live.Live.test_p1_served_without_payment` |
| P2 | The `PaymentRequired` object is present and decodes | V2 HTTP transport: "`PAYMENT-REQUIRED` header containing base64-encoded JSON"; V1 §5.1: the 402 body is the `PaymentRequired` JSON | `test_p2_missing_header`, `test_p_v1_body_graded_as_v1` |
| P3 | `x402Version`, `resource` and a non-empty `accepts` | V2 §5.1.2: `x402Version` "must be 2", `resource` Required, `accepts` Required | `test_p3_p4_p5_field_problems` |
| P4 | Each `accepts` entry has its required fields and types | V2 §5.1.2: `scheme`, `network` (CAIP-2), `amount` ("atomic token units"), `asset`, `payTo`, `maxTimeoutSeconds` all Required; V1 §5.1 the same with `maxAmountRequired`, `resource`, `description` | `test_p3_p4_p5_field_problems`, `test_p_all_pass_on_spec_example` |
| P5 | Scheme-specific `extra` | EVM exact: "`extra.name` (required)", "`extra.version` (required)" for EIP-3009; SVM exact: "`extra.feePayer`: The sponsor's public key" | `test_p3_p4_p5_field_problems`, `test_p_svm_needs_fee_payer` |
| R0-R10 | Your resource server serves only on a final, well-formed, first-time settlement, and returns `PAYMENT-RESPONSE` | F3, F5, F6, F8 and F9 above; V2 HTTP transport: "Servers communicate payment settlement results using the `PAYMENT-RESPONSE` header" | `ts/test/probe.test.ts` (including a stock `@x402/express` server on Solana devnet and Base Sepolia) |

Four distinct properties are often conflated; this check separates them:

- **Payment settlement validity** — the transaction is real, final and on the required network (F3, F5, F8).
- **Payment-requirement validity** — the settled payment matches the CURRENT requirements: amount, asset, recipient, network, scheme (F2 and F10).
- **Authorisation of the current request/resource** — the settled payment is bound to THIS resource, not merely to a price and recipient (F10). The exact scheme provides no field that cryptographically binds a resource URL; the binding is enforced at the verifier boundary via the requirements hash recorded per transaction.
- **Replay prevention and idempotency** — the same settlement cannot credit twice, while a legitimate retry of the SAME request reaches its outcome exactly once (F3, F4, F7, F9).

Limitation: a facilitator that never sees the requirements (settle-by-transaction-hash alone) cannot enforce the resource binding by itself; the enforcement point is the verifier that holds both the payload and the requirements it is being quoted against.

## Lean models
| theorem | statement | file |
|---|---|---|
| `credit_sound` | Anything credited was a finalized success for at least the required amount (F2, F5) | `lean/X402Conformance/Settlement.lean` |
| `step_idem` | Settling the same outcome again changes nothing (F3) | same |
| `step_nodup`, `run_nodup` | No transaction is ever credited twice, over any sequence of outcomes (F3, F4) | same |
| `consume_once`, `only_open_consumes` | A nonce is consumed at most once (F4) | `lean/X402Conformance/Nonce.lean` |
| `pending_never_credits` | A `settlement_pending` answer never credits (F5, F7) | `lean/X402Conformance/Pending.lean` |
| `timeout_never_credits`, `failure_never_credits` | A timeout, broken transport or terminal failure never credits (F6, F8, F9) | same |
| `reconcile_credits_once` | Any run of pending answers and timeouts, then confirmation and retries, ends credited exactly once (F7, F9) | same |
| `resolved_final`, `failed_never_pending`, `failed_never_credits` | A failure confirmed on chain is terminal and never credited (F8) | same |
| `concurrent_nodup` | Any interleaving of concurrent settles over one shared credited set credits each transaction at most once (F3) | same |
| `racy_not_nodup` | A check-then-insert on a stale read double-credits, so the rule must be atomic (F3) | same |

All of these use only standard axioms: `propext`, plus `Quot.sound` for `racy_not_nodup` (`lean/Axioms.lean`, checked in CI). They are models of the rule the suite
checks. They are not proofs about any particular facilitator's code.
