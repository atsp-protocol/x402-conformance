# Changelog

## 1.3.0 (2026-10-20)
Fixes from an end-to-end review of 1.2.1, plus the EVM probe and 402 validation.

**Fixed**
- R3 no longer fails correct servers. The facilitator double used to answer success after 30 s, so a stock
  `@x402/express` server (whose facilitator client waits up to 90 s) was reported as serving on a timeout. The double
  now never answers, and a server passes if it serves nothing by the probe's 60 s deadline. A stock `@x402/express`
  server is tested in CI and passes.
- The Action fails closed. A requested check that crashes or leaves no results file now fails the job instead of
  passing, and so does a run that requested nothing. The probe refuses to run when something else already answers on
  your server's port or the double's port is taken, stops when a `--start` server exits, and always writes `--out`.
  The probe also stops at R1 if your server serves without calling the double, instead of grading another
  facilitator.
- S1 is version-aware: a facilitator that advertises only `x402Version: 1` kinds is graded against V1 §7.3 instead of
  failing for missing V2 fields.
- S4 splits by evidence: a missing or invalid `extra.feePayer` is an error; a fee payer not listed in `signers` is now
  a warning, because the spec doesn't require it. Warnings show in the summary and SARIF and never fail a run.
- S0 is a real check: an unreachable `/supported`, a non-200 or a non-JSON body is reported as S0 with the reason, and
  a 401 or 403 says how to pass credentials.
- The Action no longer replaces your Node: it runs the probe on a pinned, checksum-verified Node 24 kept out of your
  PATH, and no longer runs `setup-python` or `setup-node`.

**Added**
- The probe grades **Base Sepolia** (`eip155:84532`, `exact` with EIP-3009) as well as Solana devnet, picked from
  your 402 automatically or with `--network`. A server that offers neither is reported as **unsupported** (exit code
  3), not failed.
- R10: the served response must carry a `PAYMENT-RESPONSE` header that decodes to `success: true`.
- `x402conf resource URL...` (and the Action's `resources` input): P1-P5 validate any paid URL's 402 answer on any
  network, V1 or V2, with one unpaid GET.
- Facilitators that need credentials: set `X402C_FACILITATOR_AUTHORIZATION` and `X402C_FACILITATOR_AUTH_HOST`. The
  credential is read only from the environment, sent only to that host and never printed.
- `--version` on `x402conf` and `x402conf-svm`; `--help` lists every subcommand and exits 0.
- `--fail-on-error` on `live`, `resource` and `report`. Without it they exit 0 after writing results, as before.
- `ts/example/express-server.ts`, a stock `@x402/express` server, and EVM support in `ts/example/server.ts`.
- README: a 60-second quickstart, who it is for, a badge ("tested with", not certification) and the current results.
  Issue forms for adding a facilitator to the results and for false positives; Discussions are open.
- The npm package ships its licence.

**Changed**
- Documented exit codes now match the code. `x402conf`: 0 ok, 1 failed (with `--fail-on-error`, or `offline`/`devnet`),
  2 usage error. `x402conf-svm`: 0 pass, 1 fail, 2 usage or run error, 3 unsupported.
- Spec links point to the canonical x402-foundation/x402 repository.
- `tools/vv.py` on a pull request (or with `--pre-merge`) reports the "pushed to main" criterion as pending instead of
  failing; every other criterion still fails, and the run on main stays strict. The receipt records the mode.

## 1.2.1 (2026-10-20)
- Published to PyPI as `x402-conformance` and to npm as `x402-conformance-svm`; the README and project page now
  install from them.
- README for public use: an install table, CLI
  exit codes, Action outputs, how to verify the signed Proofline contract yourself, and security and contributing
  sections. Proofline links point to its new home, github.com/Optitransfer/proofline.

## 1.2.0 (2026-10-20)
- `x402conf report` turns `live.json`, `resource-server.json` and `offline.json` into SARIF 2.1.0 (for GitHub code
  scanning) and JUnit XML. Each failed check links to its fix. The Action writes both files and exposes them as the
  `sarif` and `junit` outputs, and its job summary links to the fix guide.
- docs/FIXES.md: for every check (S0-S4, F1-F9, R0-R9 and FX), what failed, why it matters and how to fix it.
- README: uploading failures to code scanning, and one-command runs with `pipx run` or `uvx`.
- Packaging, ready to publish: the Python wheel now ships the devnet runner's Node helpers, so `x402conf devnet` works
  from a PyPI install, and has project URLs. The TypeScript runner (`ts/`) is no longer marked private and lists the
  files, repository and keywords npm needs, so `npx x402conf-svm` works once it's published.

## 1.1.0 (2026-10-20)
- M1 devnet evidence: F1 to F6 ran over real `/verify` and `/settle` on Solana devnet against my self-hosted
  reference facilitator (`@x402/core` and `@x402/svm` 2.28.0), then against its fault-injected builds. F1, F2, F3, F5
  and F6 pass, and every fault-injected build is caught by the check it targets. F4 fails: the reference deduplicates
  by transaction but not by memo, so two different transactions with the same memo both settled. Results, transaction
  links and hashes are in `evidence/devnet`.
- The devnet runner retries public RPC rate limits (HTTP 429 and 5xx) with backoff, both in the Node helpers (which
  also covers the `@x402/svm` client and facilitator) and in the runner's own RPC calls.
- README: a complete workflow file you can copy, a table of the Action's inputs and outputs, an example job summary,
  and the devnet results. ROADMAP, MATRIX and ARCHITECTURE now reflect the devnet run.

## 1.0.0 (2026-10-20)
- GitHub Action `x402 Conformance` (`action.yml`): live S1-S4, resource-server checks R0-R9 and the offline F1-F9
  suite, with a job summary and a `result` output.
- TypeScript runner (`ts/`) for resource servers on `@x402/core` and `@x402/svm`: a facilitator double with fault
  modes and a probe of the paid route.
- Devnet runner (`x402conf devnet`): F1-F6 over real `/verify` and `/settle` against a self-hosted reference
  facilitator on Solana devnet, with fault-injected builds. Devnet evidence follows once the fee payer is funded.
- Lean: `Pending.lean` models timeouts, `settlement_pending` reconciliation and concurrent settles.
- The Proofline contract is signed by the owner key.
- docs/MATRIX.md and docs/MANAGED.md.

## Earlier, unreleased
- Fixed the reference facilitator double: it marked a payment as seen before the payment was final, so retrying a
  settle that was still `settlement_pending` came back as `duplicate_settlement` instead of the final result. That
  contradicts V2 §9, where `settlement_pending` is non-terminal. A payment is now recorded only once its outcome is
  final, and a confirmed on-chain failure answers `invalid_transaction_state` and stays terminal.
- New offline checks. F7: a pending settle retried with the same body reaches its final result and is credited exactly
  once. F8: a failure confirmed after pending is terminal and never stuck pending. F9: a 503, a non-JSON page or a
  truncated body is never credited, and the payment stays retryable. Each has a faulty double that must fail it
  (`burn_on_pending`, `stuck_pending`, and the guards `guard_trust_any_status` and `guard_give_up_after_error`).

## 0.1.0 (2026-10-20)
- First prototype. Live checks S1 to S4 read only `GET /supported`. Safety checks F1 to F6 run against in-process facilitator doubles, using devnet fixtures.
- Lean models: `credit_sound`, `step_idem`, `step_nodup` and `run_nodup` for the credit rule, plus `consume_once` and `only_open_consumes` for nonces. Every one of them depends only on `propext`.
- First evidence run (2026-10-20). Dexter, PayAI and the x402.org facilitator pass S1 to S4.
- A Proofline contract (`proofline.json`) with V&V tooling (`tools/vv.py`) and a traceability matrix (`docs/VV.md`). The contract was not yet signed in this release; I signed it for 1.0.0.
