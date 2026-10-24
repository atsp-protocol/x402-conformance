# Threat model

Scope: the money-safety properties of an x402 V2 payment, as seen by a resource server that trusts a facilitator
on Solana. Everything here is experimental.

| # | threat | effect | check | Lean |
|---|---|---|---|---|
| T1 | The same payment payload is sent to `/settle` several times before the first send confirms | One payment unlocks many resources | F3 | `step_idem`, `run_nodup`, `concurrent_nodup`, `racy_not_nodup` |
| T2 | A used memo or nonce is replayed inside a new transaction | Double credit | F4 | `consume_once`, `run_nodup` |
| T3 | Dust or an underpayment is accepted | Resource delivered for less than the price | F2 | `credit_sound` |
| T4 | Success is reported before finality, or `settlement_pending` is treated as success | Credit for a payment that never lands | F5 | `credit_sound`, `pending_never_credits` |
| T5 | The facilitator times out, or returns a 5xx, an HTML error page or a truncated body | The resource server fails open, or gives up on a payment that did land | F6, F9, F1 | `credit_sound` (only `success` credits), `timeout_never_credits`, `failure_never_credits`, `reconcile_credits_once` |
| T9 | A `settlement_pending` payment is marked as seen before it is final, so its retry gets `duplicate_settlement` | A paid purchase is never fulfilled | F7 | `pending_never_credits`, `reconcile_credits_once` |
| T10 | A transaction that failed on chain keeps being reported as `settlement_pending` | The resource server waits forever, or eventually guesses | F8 | `resolved_final`, `failed_never_pending`, `failed_never_credits` |
| T6 | `/supported` advertises V1 names or an invalid fee payer | Clients sign against the wrong network or sponsor | S2 to S4 | n/a |
| T7 | The suite itself causes harm | Payments, signing or load against third parties | Live and resource modes are GET-only (tested); devnet only, with throwaway keypairs from a directory outside the repository; no keys of yours held | n/a |
| T8 | Results are misreported | False claims about a facilitator | Raw bodies and SHA256SUMS committed per run; `test_committed_evidence_reproduces` | n/a |
| T11 | A payment verified under one set of requirements is presented under different requirements (amount escalation, recipient or resource substitution) | The payment authorises a request it was never made for | F10 | n/a |
| T12 | `/verify` commits payment state | A payment is burned without being settled, or counted twice | F11 | n/a |
| T13 | `/verify` takes the network and asset in the requirements on trust | A payment the facilitator can never settle, or one in a token that does not exist, is verified and served | F12 | n/a |
| T14 | `/supported` advertises a kind `/verify` has no handler for, or `/verify` refuses with no reason | The kind looks supported but fails every payment, and the refusal cannot be acted on | S5 | n/a |

## Out of scope
The facilitator's own key custody, fee-payer drain attacks (SVM exact §2.1, already specified and tested by
facilitators), facilitator checks for EVM schemes (P5 reads EVM `exact` offers, and the resource-server and client checks run on Base
Sepolia as well as Solana devnet), and the `upto` and `batch-settlement` schemes. They may come later and will be
listed in the roadmap if they do.

## Disclosure
A failing check against a named facilitator goes to that facilitator privately first (see `SECURITY.md`). It is
published only after a fix, or after 90 days.
