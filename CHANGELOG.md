# Changelog
## Unreleased
- External modes for R16a and R24 in the tier-1 queue (proposed task XC-110).
  - `x402conf resource --malformed-header` adds R24 (five unpaid GETs with a malformed `PAYMENT-SIGNATURE`, graded
    like `x402conf-svm live`), and `--unpaid-head` adds R16a (one unpaid `HEAD`), both on the GET that P1-P7 already
    sent. A `HEAD` is not a `GET`: off loopback it is sent only with `--operator-permission <ref>` (the devnet runner's
    convention) and R16a is skipped without it. `x402conf-svm live` follows the same rule.
  - The queue's `run` job sends them against the row's testnet endpoint, at most eight requests 5 s apart; the HEAD only
    when the row ticked the new optional form box (`consent.unpaid_head`), with the row's consent issue as the
    permission. Tier 1 is now 11 checks (P1-P7, P9, P10, R16a, R24); an external check the run did not reach counts
    as needing the self-hosted run.
- Two tiers in the matrix (proposed task XC-98).
  - **External-verified** (tier 1): the run queue runs the checks that work from outside a project's stack (P1 to
    P7, P9, P10: unpaid GETs, paced, zero spend) against its public testnet endpoint, with the pinned suite release
    (`matrix/queue/suite.json`), on each new release. The queue no longer checks out or runs the project's code, and
    the form no longer asks for a start command.
  - **Full suite (self-hosted)** (tier 2): the project runs the whole suite in its own CI with the Action's new
    `attest` and `not-applicable` inputs. The Action writes one entry per catalogue check (with reasons for checks
    that don't apply), signs it with GitHub artifact attestations and uploads it. The queue verifies it and never
    reruns it: `tools/attestation.py` with `gh attestation verify` (the row's repository, the attested commit, tag and
    run, the pinned suite, every applicable check). An older suite is listed as "rerun on current suite".
  - Rows show the tier, passed/applicable, the denominator (exercised / NA / needs self-hosted), the suite tag and the
    date. Badges read "External-verified · x402-conformance <tag> · Optitransfer" or "Full suite (self-hosted) ·
    x402-conformance <tag> · Optitransfer" with the count and date. The README snippet and attribution are unchanged.
  - The notify hook asks for the tier-1 rerun and, when enabled, runs the full suite and submits its attestation; the
    weekly check asks for tier-1 reruns of new releases and verifies new attestations. The free six months cover
    tier-1 reruns and tier-2 verification and listing. A hosted-staging full run is an exception path by arrangement.
- Free run program (proposed task XC-97). I run the suite for a project, free: one initial run, then queued reruns
  on new releases only, for six months from consent (`program_start`, `program_end` in the row).
  - In return the project is listed with its results, displays the badge in its README with "Conformance tested by
    Optitransfer/x402-conformance", and installs the notify hook (`docs/templates/x402-conformance-notify.yml`, on
    release published).
  - The `run-queue` workflow and `tools/run_queue.py` keep one queue entry per slug on the `run-queue` branch and run
    within `matrix/queue/caps.json`: at least 5 s between probes, testnet ids, the loopback double, zero spend.
  - The project's code runs in a read-only job with no secrets. Full results are sealed to the maintainer's key and
    go to the project privately first. A maintainer's publish comment then opens the row PR.
  - A renewal heads-up issue opens at five months. After the end date the row stays listed with its last result,
    marked stale, and the badge greys out. Self-runs with the Action stay free and unlimited.
  - The form adds the badge consent ("Display the badge in our README with attribution to
    Optitransfer/x402-conformance"), the hook checkbox, the start command and the paid route.
  - The weekly check flags a row whose public README no longer links it.
  - The Action gains `evidence-upload`.
  - The attribution line is now "Optitransfer/x402-conformance" throughout.
- Opt-in matrix (proposed task XC-96): only projects that accept are listed. `docs/MATRIX.md` is compact: a coverage
  summary of accepted projects (by type, chain, language and environment), the accepted projects with evidence, a
  labelled example row, and the suite's reference baseline; the full searchable table is generated on Pages
  (`docs/site/matrix/`, one anchor per row). The named facilitator and self-hosted lists that had not accepted are no
  longer in the matrix. Badges ("Tested with x402-conformance · Optitransfer", the version tested, grey "stale" when
  stale) are made only for listed projects, with copy-paste Markdown and HTML per row. Freshness: a vendor workflow
  template (`docs/templates/x402-conformance.yml`), and a weekly job (`tools/matrix_freshness.py`,
  `.github/workflows/matrix-freshness.yml`) that records each project's latest release and default-branch commit,
  pulls the evidence from its own runs and opens a pull request; a release-alignment column (current, behind, stale).
- Add your project to the matrix (proposed task XC-96): the "Add or update my row" issue form
  (`.github/ISSUE_TEMPLATE/matrix-row.yml`) asks for public details only and three required consents (listing, CC BY
  4.0 for public results, testnet-only probes). The `matrix-row` workflow checks it with `tools/matrix_rows.py` against
  `matrix/schema/row.schema.json` and the public-safe rules (no emails, no secrets, https links, a public handle),
  labels it, comments what to fix, and opens a pull request adding or updating `matrix/rows/<slug>.json` for review.
  Pasted evidence goes through the same refusals as `tools/row_from_evidence.py`. Nothing merges automatically. The
  "Listed projects" table in `docs/MATRIX.md` is generated from the rows and checked in CI.
- Run it yourself (proposed task XC-94): the Action's `evidence: true` and `row:` inputs write one matrix row's
  evidence bundle (the run.json as written, a README and `SHA256SUMS`) and upload it as an artifact. A mainnet network
  is refused before any request, and so is a run graded on mainnet or with a facilitator off loopback. New
  "Add or update my row" issue form, and `docs/RUN-IT-YOURSELF.md` (CLI, Action, MCP, how to get listed).
- Matrix rows (proposed task XC-93): every row in `docs/MATRIX.md` has an environment (testnet, devnet, live-not-run
  or out-of-reach), checks passed out of checks run, a failed count only, the version tested and the run date linking
  its evidence, plus "rerun / get listed" and "missing check?" links. No score or ranking.
- Attribution (proposed task XC-95): a "Tested with x402-conformance" SVG badge per row on the Pages site
  (`docs/site/badge/`, terms in `docs/BADGE.md`, built and checked by `tools/compat_matrix.py`). The public results
  and evidence are CC BY 4.0 (`DATA-LICENSE`); the code stays Apache-2.0. `CITATION.cff`, and a credit line in
  `NOTICE`. Every results document has `provenance` (suite, version, publisher, repo), and the Action's job summary
  ends with "Tested with x402-conformance vX.Y.Z".
- `x402conf-svm mcp --url <mcp-endpoint> --tool <name> [--arguments '<json>'] [--no-initialize]`: one unpaid
  `tools/call` of a paid MCP tool on a live server, paced like `live`, graded X1 on the tool result and P3, P4, P5 and
  P7 on the `PaymentRequired` in it (`checkMcpSeller`). `--no-initialize` grades a server that needs no session in one
  request. MCP is JSON-RPC over `POST`, so it is for servers whose operator agreed. Proposed task XC-89.
- P9 and P10 (proposed task XC-85). P9: the bazaar discovery `info` in a 402, including its example query, body or
  tool arguments, validates against the `schema` the endpoint ships next to it (a Draft 2020-12 subset with no
  dependency; keywords it does not grade are listed, never guessed). P10, with `x402conf resource --well-known`: the
  host's `/.well-known/x402` manifest lists the paid URL, lists only HTTPS URLs on its own host or a subdomain, and
  declares terms a live offer matches; one GET per origin, a 404 is not graded.
- R16a passes an unpaid `HEAD` that is refused with 405 and no `PAYMENT-RESPONSE`, as well as a 402 with an offer: both
  keep `HEAD` away from the handler. A 2xx still fails. Proposed task XC-86.
- C2 and C3 grade a client the caller declares does not sign (`{ signsPayments: false }`) and that signs nothing as not
  applicable instead of failed. Reports, `explain`, SARIF, JUnit (skipped) and the badge show it as N/A and never count
  it as a failure. Without the declaration a client that never pays still fails. Proposed task XC-87.
- Live targets are paced by default: at least 5 s between requests to a non-loopback host (`--min-interval`), an
  optional cap (`--max-requests`; a request over it is not sent and the target is reported skipped), one log line per
  request on stderr and the log in the JSON under `pacing`. This applies to `x402conf live` and `resource` and to
  `x402conf-svm resource` and the new `x402conf-svm live --url`, which grades P1-P7, R16a and R24 on one paid URL in
  7 unpaid requests. Proposed task XC-88.
- Seventeen open-source facilitators are listed in `docs/MATRIX.md` as self-hosted columns, each at a pinned commit, run
  on 127.0.0.1 as my own instance against public testnets; S0 to S4 run against them today. The verify-only F checks on
  Base Sepolia for these columns are the proposed task XC-51.
- U1 to U3 for the `upto` scheme and B1 to B3 for the `batch-settlement` scheme (XC-35), on Solana devnet and Base
  Sepolia, exported as `probeUpto` and `probeBatch` with a scheme double, `startSchemeDouble`. U1: a settle never
  exceeds the authorised maximum; U2: `PAYMENT-RESPONSE` reports the settled amount; U3: an `upto` offer never declares
  `upfront` (P7's flow rule, graded). B1: a commitment is served once with its identifier and charge; B2: one
  redemption run claims each channel once, at its latest voucher; B3: a partly failed run is reported and retried per
  channel. The `upto` control is `ts/example/upto-server.ts` on the stock scheme servers, the `batch-settlement` control
  `ts/example/batch-server.ts`; the `no_cap`, `report_max`, `upfront_flow`, `accept_replay`, `claim_every_voucher` and
  `drop_failed` builds are each caught.
- W1 to W3, the sign-in-with-x server rules (XC-37), exported as `probeSiwx`. After a throwaway wallet pays the route
  through the double and signs back in (the control), W1 refuses a message signed for another site even when `Host` or
  `X-Forwarded-Host` names it, W2 refuses the same signed message twice, and W3 refuses a stale, future or expired
  message. The control is the shipped extension with a configured origin and a nonce-tracking storage
  (`ts/example/siwx-server.ts`); the shipped `InMemorySIWxStorage` tracks no nonces, so on its own it fails W2. The
  `origin_from_host`, `no_nonce_store` and `no_time_window` builds are each caught.
- D1 and G1, discovery and A2A (XC-36), exported as `checkDiscovery` and `checkA2aMirrorsHttp`. D1 reads a
  facilitator's `/discovery/resources` and `/discovery/search` (GET only) and checks the V2 section 8 shapes, every
  item's fields, `limit` and the `network` filter; a facilitator that serves neither is unsupported. G1 sends an
  unpaid A2A `message/send` and checks the `input-required` task asks for the same `accepts` as the HTTP route's 402.
  The controls and the `v1_items`, `ignore_filters`, `stale_price` and `not_input_required` builds are in
  `ts/example/discovery-server.ts`.
- R21, settlement preemption for caller-unbound settlement (XC-34), exported as `probePreempt`. On a Base Sepolia
  route whose exact offer uses Permit2, a payment a third party settled first (the server's own settle answers
  `permit2_invalid_nonce`) must not be served, and a spent payment must not be served twice. The facilitator double
  gains a `settle_preempted` mode and answers `permit2_invalid_nonce` for a spent Permit2 payment. The control is
  `ts/example/preempt-server.ts`; the `nonce_used_is_paid` and `serve_before_settle` builds are each caught.
- X1 and X2, the MCP transport checks for paid MCP tools (XC-33), exported from `x402-conformance-svm` as
  `checkMcpPaymentRequired` and `probeMcpTransport`. X1 reads one unpaid `tools/call` and checks the payment-required
  tool result: `isError: true`, the `PaymentRequired` object in `structuredContent` and the same JSON in
  `content[0].text`. X2 runs the R0-R10 faults on a paid tool call: the tool's result comes back only on a final,
  first-time settle, with `_meta["x402/payment-response"]`. The control is `ts/example/mcp-server.ts`; the
  `text_only`, `rpc_error`, `serve_on_failure` and `result_first` builds are each caught.
## 1.6.0 (2026-10-24)
- The contract: XC-48, Release 1.6.0, carries the tasks that were still open when 1.5.0 was planned and the two added
  since: R17 to R19 (XC-18), the implementation matrix (XC-19), the framework quickstarts (XC-26), docs examples run by
  CI (XC-27), the compatibility matrix (XC-28), the mutation matrix with the false-positive register (XC-29), and F13
  and F14 (XC-49, XC-50). XC-22 (the R20 corpus case) and XC-24 (the n-replica Lean models) are on XC-48's list and
  landed before the 1.5.0 tag. XC-49 and XC-50 come from
  `docs/proposals/contract-addendum-asset-network-substitution.json`, signed into `proofline.json` with this release;
  every task above is claimed in `vv/claims.json`.
- F13 and F14, two facilitator checks in the offline suite (`x402conf offline`, the Action's `offline` input). F13: a
  payment that carries the quoted amount to the quoted recipient but in a different asset is rejected (asset
  substitution; the faulty `trust_asset` facilitator takes the asset from the requirement on trust). F14: a payment
  authorized for another network is rejected even when amount, recipient and asset match (facilitator-layer network
  substitution; the faulty `trust_network` facilitator). Each has a passing control, the faulty build it catches, a fix
  section in `docs/FIXES.md` and its rows in `docs/COVERAGE.md` and the mutation matrix. F14 checks the facilitator's
  network binding only: a cross-chain replay of an EIP-3009 signature whose EIP-712 domain omits `chainId` needs a live
  devnet test and is not covered offline. The contract tasks are XC-49 and XC-50.
- Every example the docs mark with `<!-- runnable: <kind> -->` is run or checked by CI through
  `tools/doc_examples.py --run`, so a broken example fails the build. The contract task is XC-27.
- The mutation matrix: `tools/mutation_matrix.py` resolves every faulty build in the catalogue the way the credibility
  test does and writes `docs/site/mutation-matrix.json` (each check, its profile, each faulty build with `caught` and how),
  byte-identical for one tree; CI checks it, and the false-positive register exists. The contract task is XC-29.
- R17, R18 and R19 (`probeCacheLeak`, `probePending`, `probeFlows`): a shared cache in front of the paid route must not
  serve the paid content to an unpaid request; a pending, late or unanswered settlement never serves before the payment
  is final and serves once after it; the upfront and escrow flows are checked, each with a passing control and faulty
  builds. The flaky port race in the CLI tests (#67) is fixed by `ts/test/ports.ts`. The contract task is XC-18.
- The implementation matrix: `evidence/impl-matrix/` holds five rows (Express with `@x402/express` 2.28.0 and 2.27.0,
  Hono 2.28.0, FastAPI and Flask with the Python SDK 2.25.0), each a probe run of R0 to R10 against the stock example
  server behind the double, with `run.json`, a README naming the versions and `SHA256SUMS`; `.github/workflows/impl-matrix.yml`
  rebuilds them, one job per row; `examples/python/flask_server.py` is new. The contract task is XC-19.
- The compatibility matrix: `tools/compat_matrix.py` reads every row of `evidence/impl-matrix/` and writes
  `docs/compat-matrix.json` and the implementation-matrix table in `docs/MATRIX.md` (stack, version, network, tool, every
  check's status, the run's path and hashes), byte-identical for one tree; `--check` fails CI when either is stale, and
  `.github/workflows/compat-matrix.yml` rebuilds it on a schedule. The contract task is XC-28.
- Framework quickstarts: `examples/` holds one minimal paid route per framework (Express, Hono and Next on `@x402/*`
  2.28.0, FastAPI and Flask on the Python SDK 2.25.0, Go gin on the Go SDK), and `sh tools/quickstart.sh <framework>`
  takes a clean checkout to a first R0 to R10 result behind the facilitator double, writing
  `examples/<framework>/quickstart-result.json`; the `quickstarts` CI job runs all six. The contract task is XC-26.
- Dependencies: every open Dependabot alert on the default branch is cleared (38 on 2026-10-24, all in the example apps
  and the probe's lockfiles). `examples/go` moves `golang.org/x/crypto` to 0.52.0 (which needs `go 1.25.0`, so the go
  directive and CI's Go setup follow), `go-ethereum` to 1.17.0, `gnark-crypto` 0.18.1, `klauspost/compress` 1.18.7,
  `quic-go` 0.59.1, `gorilla/websocket` 1.5.3, `mongo-driver` 1.17.7, `x/net` 0.55.0, `edwards25519` 1.1.1 and the
  OpenTelemetry modules to 1.41.0 while the Go SDK pin is unchanged. The Node lockfiles (`ts/`, the devnet runner, the
  Express, Hono and Next quickstarts) carry `zod` 4.6.6 through an override, which reverses the 1.5.0 decision to leave
  the SDK's `zod` 3 pin alone; the Next quickstart also moves `uuid` to 11.1.1, `decode-uri-component` to 0.5.1, `ws` to
  8.22.0 and 7.5.13 under their parents and `bn.js` to 4.12.5 under `@walletconnect/utils`. The SDK pins (`@x402/*`
  2.28.0, Python 2.25.0, the Go SDK) do not change.

## 1.5.0 (2026-10-23)
- The contract: XC-39 to XC-46 (R16a, R22, R23, R24, C1, C2, C3, F12) are signed and claimed (#55), XC-23 is claimed
  (#48), XC-30 is claimed, and XC-47 for S5 is proposed, unsigned (#49). XC-31 (this release) is amended to depend on the
  tasks that are built, and XC-48, Release 1.6.0, carries the eight tasks that were open when 1.5.0 was planned (XC-18,
  XC-19, XC-22, XC-24, XC-26 to XC-29); two of them, the R20 corpus case and the n-replica Lean models, landed before
  the tag. [RELEASES.md](RELEASES.md) at the repository root maps every release to what it added, with the narrative in
  [docs/RELEASES.md](docs/RELEASES.md), and [docs/COVERAGE.md](docs/COVERAGE.md) lists every check with its profile,
  where it runs and its controls and faulty builds, and the networks, schemes, stacks, facilitators and Lean models the
  evidence covers.
- Lean: `lean/X402Conformance/Replicas.lean` models n replicas; its five theorems include `shared_cas_at_most_one_grant`
  (a shared atomic check-and-set admits at most one grant) and `partitioned_caches_admit_double_grant`, with standard
  axioms only. The contract task is XC-24.
- The R20 corpus case, `corpus/cases/2026-10-23-R20-express.json`, from a `--share` run of `x402conf-svm probe --retry`
  against a stock `@x402/express` 2.28.0 server with no idempotency record (R20a and R20b fail); `ts/example/retry-server.ts`
  now runs standalone. The contract task is XC-22.
- MCP: `x402_explain_check` finds the fix section of a check whose id has a lowercase suffix (R11a to R11f, R16a, R20a,
  R20b); the heading lookup used to upper-case the id.
- `x402-conformance-mcp` depends on zod 4.6.6: Dependabot flagged 4.1.12 for memory exhaustion while validating oversized
  constrained collections, and the MCP server validates every tool input with zod. The `x402-conformance-svm` and devnet
  lockfiles resolve zod 3.25.76 through `@x402/core`'s `^3.24.2` range, which no 4.x satisfies; that pin moves when
  upstream's does.
- `tools/interdeps.py` no longer writes a per-component file count into the map, so a pull request that adds a file no
  longer stales the committed map of every other open pull request (#52).
- The MCP server is published to the MCP Registry as `io.github.atsp-protocol/x402-conformance` on each GitHub release
  (`.github/workflows/mcp-registry.yml`, GitHub OIDC). The workflow checks that `server.json` matches the release tag
  and skips a version the registry already lists.
- The v1.5 contract addendum (XC-22 to XC-37) was signed into `proofline.json` after 1.4.0.
- Dev dependencies: vitest 4.1.12.
- S5, every advertised kind gets a verdict: the offline checks read the facilitator's `/supported` and send `/verify`
  once for each kind it lists. Each answer must be `isValid: true`, or `isValid: false` with an `invalidReason`; an
  exception (a 5xx or a dropped answer over HTTP) or a refusal with no reason fails. The reference double passes, with
  one kind or with a second network it answers `invalid_asset` for. The `advertise_unhandled` build (a listed kind its
  `/verify` has no handler for) and the `reasonless_invalid` build each fail (`tests/test_offline.py`). A facilitator
  double with no `supported()` is not graded on S5. A fix section is in [docs/FIXES.md](docs/FIXES.md#s5). The contract task, XC-47, is proposed.
- R22, the paid response keeps the handler's 2xx status and headers (`probeStatus`): after a successful settle the
  client receives the handler's own status and headers. A 201 stays a 201 with its Location and a 202 stays a 202 with
  its Content-Location. Only 2xx statuses are graded, since a paid 3xx is never settled (R15). The control is
  `ts/example/status-server.ts`; a build that rewrites the paid response to 200 fails, on Solana devnet and Base
  Sepolia (`ts/test/handler-status.test.ts`). The contract task is XC-40.
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
  (`ts/test/client-version.test.ts`). A fix section is in [docs/FIXES.md](docs/FIXES.md#c3). The contract task is XC-45.
- C2, a client pays an offer within its own policy (`checkClientOfferPolicy`): given several offers a client must
  choose one on its configured networks and within its maximum amount, not the first, and never sign for a network
  outside its set. A recording proxy puts two decoys before the route's offer in the 402 (the same offer on a network
  outside the client's set, and one on its network above its maximum), answers a payment for a decoy with 402 so
  nothing settles, and reads which offer the client signed. The stock `x402Client` with `@x402/fetch`, registered only
  for its network and capped with spend controls, passes; a client that signs the first offer and one that ignores its
  maximum are caught, on Solana devnet and Base Sepolia (`ts/test/client-offers.test.ts`). A fix section is in
  [docs/FIXES.md](docs/FIXES.md#c2). The contract task is XC-44.
- C1, a client never hands a 402 to its caller as a success. `checkClientHandles402` runs a client once through a
  recording proxy in front of a paid route behind the facilitator double. It passes when the client pays and gets a
  2xx, or rejects with an error, and fails when the client resolves with the 402. The stock `@x402/fetch` client, the
  same client with a policy that declines the price, and a client that pays a 402 before its status check pass; a
  client whose status check accepts every status and whose payment step only runs for rejected statuses is caught
  (`ts/test/client-status.test.ts`, Solana devnet and Base Sepolia). A fix section is in
  [docs/FIXES.md](docs/FIXES.md#c1). The contract task is XC-43.
- R23, a client abort during settle (`probeAbort`): the probe pays a route, drops its connection while the server's
  `/settle` is in flight and then resends the same signed payment. It passes when nothing was settled, or when the
  payment was settled once and the resend gets the settled result with no second charge. The stock `@x402/express`
  server with an idempotency record written when `/settle` succeeds passes; a server that writes its record only once
  the response is delivered, and one with no record, fail (`ts/test/abort.test.ts`, on Solana devnet and Base
  Sepolia). A fix section is in [docs/FIXES.md](docs/FIXES.md#r23). The contract task is XC-41.
- R24, a malformed payment header (`probeMalformedHeader`): the probe sends a paid route five `PAYMENT-SIGNATURE`
  values that are not base64, not JSON or not an object, and passes when every one gets 402 or 400 with a structured
  error, never a 5xx, a dropped connection or the content. The stock `@x402/express` server passes; a build that decodes
  the header itself and throws, and one that drops the connection, fail (`ts/test/malformed-header.test.ts`, on Solana
  devnet and Base Sepolia). A fix section is in [docs/FIXES.md](docs/FIXES.md#r24). The contract task is XC-42.
- `tools/interdeps.py` generates `docs/INTERDEPENDENCY.md` from `proofline.json`, the unmerged addenda,
  `vv/claims.json`, the check catalogue and the tree, with a mermaid graph of the tasks. `--check` fails when the
  committed map is stale; `--drift` fails when a doc names a check id, CLI flag or Action input the code doesn't have,
  when the code has one no doc names, or when the package versions disagree; `--versions X.Y.Z` fails unless every
  package is at X.Y.Z. CI runs `--check` and `--drift`, and `tests/test_interdeps.py` shows each kind of drift is
  caught. The `ts/README.md` now documents the R11 binding flags, which no doc named. The contract task is XC-23.
- `tools/interdeps.py` also maps every tracked file to one of 36 components (code, tests, docs, the contract, CI,
  distribution) with the edges between them, drawn in `docs/INTERDEPENDENCY.md`; `--check` fails when a file is in no
  component. `--gate --base REF` fails a change that leaves a doc, contract or test component directly downstream
  neither touched nor acknowledged with `Interdeps-Ack: <component> - <reason>`, and lists the rest for review. CI
  runs the gate on pull requests. The contract task is XC-23.
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
  (`ts/test/head-unpaid.test.ts`). The contract task is XC-39.
- F12, `/verify` rejects an unsupported network or an asset that is not a token contract: the offline harness verifies
  a well-formed payment on a network the facilitator doesn't advertise and one in an address with no contract code,
  and each must be answered `isValid: false` with a reason. The `trust_kind` double fails it. The contract task is XC-46.
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
