# Changelog
## Unreleased
- R22, the paid response keeps the handler's 2xx status and headers (`probeStatus`): after a successful settle the
  client receives the handler's own status and headers. A 201 stays a 201 with its Location and a 202 stays a 202 with
  its Content-Location. Only 2xx statuses are graded, since a paid 3xx is never settled (R15). The control is
  `ts/example/status-server.ts`; a build that rewrites the paid response to 200 fails, on Solana devnet and Base
  Sepolia (`ts/test/handler-status.test.ts`).
- R12, parallel requests with one payment identifier (`probeParallel`): the probe sends eight requests at once with the
  same payment-identifier id and a fresh payment each, and fails a server that settles more than one of them or serves
  one that doesn't name the settlement. R13, two replicas (`probeReplicas`): the same id goes to one replica, then the
  other, then both at once, and the service must settle it once in all. The control is `ts/example/replica-server.ts`
  (an idempotency record that reserves the key before it awaits, shared by both replicas); the `check_then_set` build
  and a per-process record each fail, on Solana devnet and Base Sepolia (`ts/test/concurrency.test.ts`). The contract
  task is XC-17 (AC01, AC02).
- C3, a client offered V2 never falls back to V1 (`checkClientKeepsV2`). A recording proxy in front of a paid route
  adds a V1 body for the same offer to the route's 402, next to its V2 `PAYMENT-REQUIRED` header. The client must pay
  with `PAYMENT-SIGNATURE` at `x402Version` 2; a payment with `X-PAYMENT` or at `x402Version` 1 fails, and so does a
  client that never pays. Only a V2 payment is forwarded, so nothing settles for a V1 one. The stock `@x402/fetch`
  client passes and a client that reads the V1 body first is caught, on Solana devnet and Base Sepolia
  (`ts/test/client-version.test.ts`). A fix section is in [docs/FIXES.md](docs/FIXES.md#c3).
- C2, a client pays an offer within its own policy (`checkClientOfferPolicy`): given several offers a client must
  choose one on its configured networks and within its maximum amount, not the first, and never sign for a network
  outside its set. A recording proxy puts two decoys before the route's offer in the 402 (the same offer on a network
  outside the client's set, and one on its network above its maximum), answers a payment for a decoy with 402 so
  nothing settles, and reads which offer the client signed. The stock `x402Client` with `@x402/fetch`, registered only
  for its network and capped with spend controls, passes; a client that signs the first offer and one that ignores its
  maximum are caught, on Solana devnet and Base Sepolia (`ts/test/client-offers.test.ts`). A fix section is in
  [docs/FIXES.md](docs/FIXES.md#c2).
- C1, a client never hands a 402 to its caller as a success. `checkClientHandles402` runs a client once through a
  recording proxy in front of a paid route behind the facilitator double. It passes when the client pays and gets a
  2xx, or rejects with an error, and fails when the client resolves with the 402. The stock `@x402/fetch` client, the
  same client with a policy that declines the price, and a client that pays a 402 before its status check pass; a
  client whose status check accepts every status and whose payment step only runs for rejected statuses is caught
  (`ts/test/client-status.test.ts`, Solana devnet and Base Sepolia). A fix section is in
  [docs/FIXES.md](docs/FIXES.md#c1).
- R23, a client abort during settle (`probeAbort`): the probe pays a route, drops its connection while the server's
  `/settle` is in flight and then resends the same signed payment. It passes when nothing was settled, or when the
  payment was settled once and the resend gets the settled result with no second charge. The stock `@x402/express`
  server with an idempotency record written when `/settle` succeeds passes; a server that writes its record only once
  the response is delivered, and one with no record, fail (`ts/test/abort.test.ts`, on Solana devnet and Base
  Sepolia). A fix section is in [docs/FIXES.md](docs/FIXES.md#r23).
- R24, a malformed payment header (`probeMalformedHeader`): the probe sends a paid route five `PAYMENT-SIGNATURE`
  values that are not base64, not JSON or not an object, and passes when every one gets 402 or 400 with a structured
  error, never a 5xx, a dropped connection or the content. The stock `@x402/express` server passes; a build that decodes
  the header itself and throws, and one that drops the connection, fail (`ts/test/malformed-header.test.ts`, on Solana
  devnet and Base Sepolia). A fix section is in [docs/FIXES.md](docs/FIXES.md#r24).
- `tools/interdeps.py` generates `docs/INTERDEPENDENCY.md` from `proofline.json`, the unmerged addenda,
  `vv/claims.json`, the check catalogue and the tree, with a mermaid graph of the tasks. `--check` fails when the
  committed map is stale; `--drift` fails when a doc names a check id, CLI flag or Action input the code doesn't have,
  when the code has one no doc names, or when the package versions disagree; `--versions X.Y.Z` fails unless every
  package is at X.Y.Z. CI runs `--check` and `--drift`, and `tests/test_interdeps.py` shows each kind of drift is
  caught. The `ts/README.md` now documents the R11 binding flags, which no doc named. The contract task is XC-23.
- R15, no settlement when the paid handler fails (`probeDelivery`): the probe pays a route that answers 5xx, one that
  redirects and one that throws, and fails a server that calls `/settle` for any of them or sends a
  `PAYMENT-RESPONSE`. The control is `ts/example/delivery-server.ts`, which settles only after a 2xx; the
  `settle_first` and `settle_below_400` builds each fail, on Solana devnet and Base Sepolia
  (`ts/test/handler-failure.test.ts`). The contract task is XC-18 (AC01).
- R16, a paid `HEAD` is never settled (`probeHead`): the probe sends `HEAD` with a payment to a paid `GET` route and
  fails a server that answers 2xx, calls `/settle` or sends a `PAYMENT-RESPONSE`. The control is
  `ts/example/head-server.ts`; the `head_settles` build fails, on Solana devnet and Base Sepolia
  (`ts/test/head.test.ts`). The contract task is XC-18 (AC02).
- R16a, an unpaid `HEAD` gets the same 402 as `GET` (`probeUnpaidHead`): it fails a paid route whose unpaid `HEAD`
  is not answered 402 with a `PAYMENT-REQUIRED` offer. The control is `ts/example/head-unpaid-server.ts`; the
  `head_bypass` build (a paywall that matches only `GET`) fails, on Solana devnet and Base Sepolia
  (`ts/test/head-unpaid.test.ts`).
- F12, `/verify` rejects an unsupported network or an asset that is not a token contract: the offline harness verifies
  a well-formed payment on a network the facilitator doesn't advertise and one in an address with no contract code,
  and each must be answered `isValid: false` with a reason. The `trust_kind` double fails it.
## 1.4.0 (2026-10-22)
- R14, a crash between a successful `/settle` and the response (`x402conf-svm probe --crash`, Action `crash: "true"`).
  The probe kills the server while `/settle` is answering and again as the response starts, restarts it (the `--start`
  command, or `--crash-kill` and `--crash-restart` for a server it didn't start) and presents the same payment, with a
  payment-identifier id when the server advertises the extension. It fails a server that settles again, answers 402,
  or refuses without naming the transaction or payment, on Solana devnet and Base Sepolia. The control is
  `ts/example/crash-server.ts` (a durable idempotency record), and three faulty builds of it each fail. A fix section is
  in [docs/FIXES.md](docs/FIXES.md#r14); the contract task is XC-21.
- R20, retry double-pay (`x402conf-svm probe --resource <url> --retry`, Action input `retry`): the client times out
  before `/settle` answers and retries. A retry with a fresh payment under the same payment-identifier id must not be
  settled again (R20a), and a retry resending the same signed payment must get the original result (R20b); both are
  graded on Solana devnet and Base Sepolia against the facilitator double, which can now hold `/settle`
  (`settleDelayMs`) and counts successful settlements. `checkClientRetry` grades a client's own retry: it must resend
  the payment or keep the payment id. The stock `@x402/express` server with an idempotency record keyed by the request
  and the stock `@x402/fetch` client with a payment id pass; servers with no record or a record keyed by payment, and a
  client that re-signs on timeout, are caught (`ts/test/retry.test.ts`).
- [docs/INTERDEPENDENCY.md](docs/INTERDEPENDENCY.md): every contract task and its dependencies, every check with its
  spec basis, upstream refs, code, tests and docs, the entry points and the downstream drafts, with a mermaid graph.
  It is generated from the contract, the proposed addenda and the tree. The generator (`tools/interdeps.py`), its tests
  and the CI step that fails on a stale map or on docs-versus-code drift land with contract task XC-23, once signed.
- Proposed (unsigned) contract addendum for the rest of the roadmap, XC-22 to XC-37
  ([docs/proposals/contract-addendum-v1.5-full.json](docs/proposals/contract-addendum-v1.5-full.json)), including
  R20: a client that times out and retries must never pay twice for one request.
- Docs synced with the code on `main`: the README says which commands and Action inputs need 1.4.0 (published 1.3.1
  and `@v1` don't have them yet) and lists the `pr-comment` and `github-token` inputs; the MCP check tool is P1-P7;
  ARCHITECTURE lists the binding probe, test helpers, MCP server, Docker image, GitLab template and corpus; the project
  page lists F10, F11, P6, P7 and R11; CONTRIBUTING matches CI's local checks; SPEC.md records the 2026-10-22
  re-check of the upstream spec (no normative change).
- Roadmap for v1.4 and v1.5 ([docs/ROADMAP.md](docs/ROADMAP.md)): payment-to-request binding on a real resource
  server (R11), a fail-closed oracle, F11, P6, P7 and a stricter F5, then concurrency and idempotency (R12-R14) and payment versus
  delivery (R15-R19). Checks are classified as normative, security profile or resilience, and an adoption track (A1 to
  A8: one-line demo, 3-line Action with a PR summary, fix hints, framework quickstarts, badge, regression corpus,
  compatibility matrix rebuilt in CI, examples) is built into the code. The release gate for dropping the experimental
  label is written down. The new contract tasks are proposed, unsigned, in
  [docs/proposals/contract-addendum-v1.4-v1.5.json](docs/proposals/contract-addendum-v1.4-v1.5.json).
- README and the Action list F10 and F11 with the rest of the offline self-test.
- A first run with nothing to set up: `npx -y x402-conformance-svm demo` runs R0-R10 against a bundled mock resource
  server (`ts/src/mock-server.ts`, @x402/core only) behind the facilitator double, and `x402conf demo` runs S1-S4 and
  P1-P7 against a bundled mock facilitator and paid route, then the F1-F11 self-test. No wallet, no chain, a few
  seconds each. `--fault` shows a failing run, with a fix link under every failed check. A CI job installs both packed
  packages the way a new user would and fails if either one-liner takes 60 s or more.
- Action `pr-comment: "true"` (off by default) posts one sticky pull request comment with the result and a fix link
  per failed check, updated in place on every run (`x402conf pr-comment`). On a fork's read-only token it warns.
- Badge: the action writes `badge.json` (a shields.io endpoint: `pass n/n`, `n failing` or `unsupported`) and has a
  `badge` output; `x402conf report --badge FILE` writes it outside the action.
- The suite's oracle fails closed. The reference verifier parsed amounts with `int()`, so a malformed amount raised
  instead of being rejected, and forms `int()` accepts but V2 atomic units don't (`" 10000 "`, `"+10000"`, `"10_000"`,
  `"010000"`, non-ASCII digits) passed. Amounts are now parsed strictly (ASCII digits, no leading zeros, within
  uint256); a malformed payload amount is `invalid_payload`, and a malformed, zero or negative requirement amount is
  `invalid_payment_requirements`. F1 also refuses six non-canonical amounts, and a new `lenient_amounts` double is
  caught by F1.
- R11, payment-to-request binding on a real resource server (TypeScript, `probeBinding`): a control, R11a (a payment
  for the cheap route presented on the expensive one), R11b (`payTo`, asset or network altered) and R11e (encoded
  separators and dot segments in a parameterised paid route). The stock `@x402/express` 2.28.0 server passes on Solana
  devnet and Base Sepolia, and two faulty builds in `ts/example/binding-server.ts` are each caught by the sub-check
  they target.
- R11c (a payment for the cheaper HTTP method presented with the dearer one), R11d (the same for a query-priced route)
  and R11f (sign-in-with-x access recorded for the route that was priced and settled, not the client's
  `PaymentPayload.resource.url`). The stock `@x402/express` server passes R11c and R11d and the `trust_client` build
  fails both. For R11f, a SIWX server that records the settled path passes, and the stock `@x402/extensions` 2.28.0
  settle hook fails (the public upstream issue x402-foundation/x402#3838, fix proposed in #3840). R11f needs
  `@x402/extensions` and `viem` next to the probe and reports unsupported without them. A `refuse_paid` build fails
  the R11 control.
- `x402conf-svm probe` takes the binding routes (`--cheap`/`--expensive`, `--by-method`, `--by-query`, `--param`,
  `--siwx-cheap`/`--siwx-expensive`), with or without `--resource`; the Action has matching `binding-*` inputs and
  `x402conf report` reads the R11 results from `resource-server.json`.
- F5 also requires `settlement_pending` to carry the network (V2 §9). New F11: `/verify` is read-only (V2 §7.1), with
  a `verify_commits` double. New P6 (`PAYMENT-REQUIRED` header over 8 KB is a warning, over 16 KB an error) and P7
  (an `upto` Solana offer without `extra.paymentFlow`, a warning: V2 §6.1 and the upto SVM scheme text disagree).
- Faulty builds for every check that lacked one: `pending_without_tx` (F5), `verify_commits` (F11),
  `guard_credit_on_error` (F6), and probe servers `serve_unpaid` (R0) and `no_payment_response` (R10).
- Credibility gate: `spec.CATALOG` names, for every check, its profile, spec basis, a passing control and the faulty
  build it catches; a test resolves every reference and runs every fault to confirm its check fails.
- Results format `x402-conformance-evidence/2`: every result carries `profile` (`normative`, `security-profile`,
  `resilience`) and `basis`; probe results also carry a `fix` link. Documents carry the tool and runtime versions.
- The facilitator double reports the EVM payload's own `from` as the payer.
- Entry points share one report: `x402-conformance.report/1` (check IDs, status, severity, detail, summary, links)
  from the Node CLI and the new test helpers, with a `via` field naming the entry point. The same `via` goes into the
  User-Agent. No telemetry.
- `x402conf-svm resource --url`: P1-P7 in Node, ported from the Python CLI and checked against it (pass/fail and
  severity) on 37 answers in CI. Two differences the port found are fixed in Python: `maxTimeoutSeconds: 60.0` is the
  JSON number 60 and now passes P4 in both, and an amount or network with a trailing newline now fails P4 in both.
- `x402-conformance-svm/testing`: `runConformance()`, vitest and jest matchers (`toPassX402Conformance`,
  `toBeValidX402Challenge`), `assertX402Conformance()` for node:test, and `saveReport()`.
- `--share` (opt-in): writes an anonymised corpus case and prints a link to the new "Share a corpus case" issue form.
  Nothing is sent. The corpus, its schemas and the case template live in top-level `corpus/`; accepted cases go in
  `corpus/cases/` and CI re-runs every one.
- A stock `@x402/hono` example server, tested on Solana devnet and Base Sepolia alongside `@x402/express`.
- docs/USING.md: one page for using the suite from each stack.
- `x402-conformance-mcp`, a new package: the suite as seven MCP tools over stdio (`npx -y x402-conformance-mcp`), with
  MCP registry metadata, plus the four read-only tools for the Vercel AI SDK (`/ai-sdk`) and LangChain (`/langchain`).
- The Python CLI names its entry point too (`X402CONF_VIA`, default `cli-py`, in the User-Agent and the output), and
  `x402conf resource --share` writes the same anonymised case as the Node CLI. A shared fixture keeps the two equal.
- A Docker image (`ts/docker/Dockerfile`): both CLIs and the MCP server, with `x402-conformance ci` for any CI system
  that runs containers, and a GitLab CI template (`ts/ci/gitlab`). CI builds the image and runs it.
- A pytest plugin, registered when the package is installed: the `x402` fixture (`check_payment_required`, `probe`,
  `assert_passed`), `--x402-report-dir` and `--x402-share`. The stock x402 Python SDK (2.25.0) FastAPI middleware
  passes R0-R10 on Solana devnet, and CI runs it.

## 1.3.1
- XC-08: cross-request payment replay security — the reference verifier records the requirements hash each transaction
  was verified under and refuses the same transaction against a different requirements set (amount escalation, recipient
  substitution, resource substitution), and fails closed on missing or malformed requirements. Check F10 with a
  `cross_request_replay` fault, nine new tests; SPEC.md separates settlement validity, payment-requirement validity,
  authorisation of the current resource, and replay prevention.


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
