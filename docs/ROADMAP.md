# Roadmap

v1.2.1 is the current release: S1 to S4 run live with GET only, F1 to F9 run against fault-injected doubles and in
your own CI through the Action, the TypeScript runner covers resource servers, the Lean models cover timeouts,
`settlement_pending` and concurrent settles, and F1 to F6 have run on Solana devnet against a self-hosted reference
facilitator ([evidence/devnet](../evidence/devnet)). There are no public users yet.

The milestones below are my proposal for taking the suite from a working tool to a standard people rely on. Every milestone is a
Proofline task in `proofline.json` (XC-M1 to XC-M6), with acceptance criteria that CI verifies.

| id | deliverable | acceptance (summary) | status |
|---|---|---|---|
| M1 | **Devnet runner.** F1 to F6 run over real x402 V2 `/verify` and `/settle` against a facilitator on Solana devnet that I host myself, using throwaway devnet keypairs | `x402conf devnet` exits 0 against the self-hosted reference facilitator; each F check also fails against a fault-injected build; the devnet evidence is committed with hashes | devnet run done (1.1.0), [evidence/devnet](../evidence/devnet): F1, F2, F3, F5 and F6 pass, every fault-injected build is caught, and F4 fails on the reference facilitator (memo not tracked across transactions), so the exit-0 criterion is not met yet |
| M2 | **Facilitator matrix.** Results pages for at least 3 facilitators that offer Solana devnet, run only with each operator's permission | `evidence/matrix/` holds at least 3 facilitator reports; any failures go through the 90-day disclosure in [SECURITY.md](../SECURITY.md) first | open: waiting on operator permission |
| M3 | **Lean models extended.** Timeouts, `settlement_pending` reconciliation, and concurrent settles over a shared cache | New theorems build in CI with only standard axioms; each theorem is linked to its F check in [SPEC.md](SPEC.md) | done (1.0.0) |
| M4 | **Drop-in CI action.** A GitHub Action plus a TypeScript runner for resource servers built on `@x402/svm` | The action runs F1 to F6 in another repo's CI, and an example repo is green | done (1.0.0) |
| M5 | **Maintenance for 6 months.** Issues, spec updates and fixes | Monthly: open issues are triaged within 7 days and CI stays green on the current spec | ongoing since 1.0.0 |
| M6 | **Adoption.** Real projects relying on it | At least 3 external repos run the suite in CI; at least 5 facilitators have published results | open: needs real users |

Review is open and public, through issues and pull requests in this repo.
