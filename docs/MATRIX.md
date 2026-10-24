# Facilitator matrix

Devnet results for x402 V2 facilitators on Solana: F1 to F6 over real `/verify` and `/settle`, run by
`x402conf devnet`. I run it against a third-party facilitator only with that operator's written **permission**,
and only on devnet. Each third-party report will sit in `evidence/matrix/<operator>.json` with its permission record linked below.

Disclosure: a failing check in someone else's facilitator goes to that operator privately first. I publish it only
after a fix or 90 days after the report, whichever is first (SECURITY.md). Until then the row says "under disclosure".

| facilitator | operator permission | devnet run | F1 | F2 | F3 | F4 | F5 | F6 | disclosure status |
|---|---|---|---|---|---|---|---|---|---|
| self-hosted reference (@x402/core + @x402/svm 2.28.0) | mine, not needed | [2026-10-20](../evidence/devnet) | pass | pass | pass | **fail** | pass | pass | n/a: my own instance of open-source code |
| facilitator.payai.network | not yet requested | none | | | | | | | n/a |
| facilitator.x402.rs | not yet requested | none | | | | | | | n/a |
| x402.dexter.cash | not yet requested | none | | | | | | | n/a |
| x402.org/facilitator | not yet requested | none | | | | | | | n/a |
| facilitator.daydreams.systems | not yet requested | none | | | | | | | n/a |
| facilitator.goplausible.xyz | not yet requested | none | | | | | | | n/a |
| facilitator.ultravioletadao.xyz | not yet requested | none | | | | | | | n/a |

In the live run of 2026-10-20 ([evidence/2026-10-20-v1.3.0](../evidence/2026-10-20-v1.3.0)), seven named facilitators advertise a V2 `exact` kind on Solana devnet in `GET /supported`: the seven above. One more is withheld in that run. XC-M2 is done when at least
three facilitators have a report here, each with its permission recorded. No third-party report exists yet.

The F4 failure on the reference is explained in [evidence/devnet](../evidence/devnet): it deduplicates by
transaction, not by memo, so two different transactions with the same memo both settle.

Want your facilitator in the matrix? Open an issue and say so. The issue is the permission record.
