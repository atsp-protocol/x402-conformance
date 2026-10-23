# Releases

Every release of x402-conformance, with what it added and where it is published. [CHANGELOG.md](../CHANGELOG.md) has
the full entry for each change, [RELEASES.md](../RELEASES.md) at the repository root is the same history as one table,
and [COVERAGE.md](COVERAGE.md) is what the suite covers today; this page is the narrative per release. Each GitHub release carries
`RELEASE-SUMS-<tag>.json`, the SHA-256 of every published artefact, and `RELEASE-SUMS-<tag>.dsse.json`, that manifest
signed with my owner key (`guard/owner.pub`). Release tags from v1.4.0 on are signed with my SSH release key, and the
`v1` tag always points at the latest 1.x release.

| release | published | tag commit | PyPI `x402-conformance` | npm `x402-conformance-svm` | npm `x402-conformance-mcp` | GHCR image |
|---|---|---|---|---|---|---|
| [1.5.0](#150) | 2026-10-23 | the `v1.5.0` tag | 1.5.0 | 1.5.0 | 1.5.0 | `1.5.0`, `1`, `latest` |
| [1.4.0](#140) | 2026-10-23 | `aee0f84a` | 1.4.0 | 1.4.0 | 1.4.0 | `1.4.0` |
| [1.3.1](#131) | 2026-10-21 | `a2da1a19` | 1.3.1 (superseded) | 1.3.1 (deprecated) | | |
| [1.3.0](#130) | 2026-10-21 | `74b7d7cd` | 1.3.0 (superseded) | 1.3.0 (deprecated) | | |
| [1.2.1](#121) | 2026-10-20 | `98731e3e` | 1.2.1 | 1.2.1 | | |
| [1.2.0](#120) | 2026-10-20 | `375333e2` | | | | |
| [1.1.0](#110) | 2026-10-20 | `eb315ee2` | | | | |
| [1.0.1](#101) | 2026-10-20 | `4e1186d0` | | | | |
| [1.0.0](#100) | 2026-10-20 | `884c73e4` | | | | |
| [0.1.0](#010) | 2026-10-20 | `78c3cf72` | | | | |

Releases before 1.2.1 were GitHub releases only; 1.2.1 was the first on PyPI and npm, 1.4.0 the first with the MCP
package and the container image. The GitHub Action is listed on the Marketplace as
[x402 Conformance](https://github.com/marketplace/actions/x402-conformance); `uses: atsp-protocol/x402-conformance@v1`
runs the latest 1.x release.

## 1.5.0

Published 2026-10-23. Thirteen checks added since 1.4.0, the signed contract tasks for eight of them (XC-39 to XC-46),
and the docs-versus-code gate.

- Facilitator: **S5**, every kind `/supported` advertises gets a verdict from `/verify`, with the `advertise_unhandled`
  and `reasonless_invalid` faulty doubles. **F12**, `/verify` rejects an unsupported network or an asset that is not a
  token contract.
- Resource server, payment versus delivery: **R15** no settlement when the paid handler fails (`probeDelivery`),
  **R16** a paid `HEAD` is never settled (`probeHead`), **R16a** an unpaid `HEAD` gets the same 402 as `GET`
  (`probeUnpaidHead`), **R22** the paid response keeps the handler's 2xx status and headers (`probeStatus`), **R23** a
  client abort during settle is recoverable (`probeAbort`), **R24** a malformed payment header is a 4xx, never a 5xx
  (`probeMalformedHeader`).
- Resource server, concurrency: **R12** the same payment identifier in eight parallel requests settles once
  (`probeParallel`); **R13** the same identifier across two replicas settles once (`probeReplicas`).
- Clients: **C1** a client never hands a 402 to its caller as a success (`checkClientHandles402`), **C2** a client pays
  an offer within its own policy (`checkClientOfferPolicy`), **C3** a client offered V2 never falls back to V1
  (`checkClientKeepsV2`).
- Every new check has a control that passes and a faulty build it catches, on Solana devnet and Base Sepolia, and a
  fix section in [FIXES.md](FIXES.md).
- `tools/interdeps.py` generates [INTERDEPENDENCY.md](INTERDEPENDENCY.md): every contract task, check, component and
  edge; `--check` fails CI on a stale map, `--drift` on a doc that disagrees with the code, `--versions` on a version
  string that disagrees, and `--gate` fails a pull request that changes a component without updating or acknowledging
  its downstream docs, contracts and tests.
- Lean: `Replicas.lean` models n replicas and proves that a shared atomic check-and-set admits at most one grant while
  partitioned caches admit a double grant (XC-24).
- The R20 corpus case from a stock `@x402/express` server with no idempotency record, and `retry-server.ts` runs
  standalone (XC-22).
- Contract: XC-39 to XC-46 signed and claimed, XC-23 and XC-30 claimed, XC-31 amended so 1.5.0 ships the checks that are
  built, and XC-48 added for the 1.6.0 list; XC-22 and XC-24 from that list landed before the tag. XC-47 (S5) is
  proposed, unsigned.
- `RELEASES.md` (the release map) and `docs/COVERAGE.md`.
- Dev dependencies: vitest 4.1.12.

## 1.4.0

Published 2026-10-23 (the changelog entry is dated 2026-10-22, when the release commit landed). The binding release:
a trustworthy oracle, R11, R14, R20, the adoption track, the MCP package, the Docker image and the pytest plugin.

- **R11a to R11f**, payment-to-request binding on a real resource server (`probeBinding`): route, recipient, asset,
  network, method, query and encoded-path substitution, and SIWX access recorded for the route that was priced
  (upstream x402#3838). Probe flags `--cheap`, `--expensive`, `--by-method`, `--by-query`, `--param`, `--siwx-cheap`,
  `--siwx-expensive`; matching `binding-*` Action inputs.
- **R14**, a crash between a successful `/settle` and the response (`--crash`, Action `crash`), and **R20**, a client
  retry never pays twice (`--retry`, Action `retry`, `checkClientRetry`).
- **F5 extended** (`settlement_pending` carries the network), **F11** (`/verify` is read-only), **P6** (header size),
  **P7** (`extra.paymentFlow`), and F10 and F11 in the README and the Action.
- The oracle fails closed: strict atomic-unit amounts, `invalid_payload` and `invalid_payment_requirements` instead of
  exceptions, a `lenient_amounts` double caught by F1.
- Credibility gate: `spec.CATALOG` names each check's profile, spec basis, control and faulty build, and a test runs
  every fault. Results format `x402-conformance-evidence/2` with `profile`, `basis` and a `fix` link; one report format
  `x402-conformance.report/1` across the CLIs and test helpers, with a `via` field and no telemetry.
- Adoption: `npx -y x402-conformance-svm demo` and `x402conf demo` with `--fault`; the Action's sticky `pr-comment`;
  `badge.json` and the `badge` output; the shareable corpus (`--share`, `corpus/`); `docs/USING.md`;
  `x402-conformance-svm/testing` (`runConformance`, vitest and jest matchers, `assertX402Conformance`, `saveReport`);
  `x402conf-svm resource --url` for P1 to P7 in Node; a stock `@x402/hono` example.
- New packages: `x402-conformance-mcp` (seven MCP tools over stdio, plus Vercel AI SDK and LangChain tools), the
  `ghcr.io/atsp-protocol/x402-conformance` image with a GitLab CI template, and the pytest plugin (`x402` fixture,
  `--x402-report-dir`, `--x402-share`) with the FastAPI example.
- Contract: the v1.5 addendum XC-22 to XC-37 signed; the interdependency map proposed (XC-23).

## 1.3.1

Published 2026-10-21. XC-08, cross-request payment replay: the reference verifier records the requirements hash each
transaction was verified under and refuses the same transaction against a different set (amount escalation, recipient
and resource substitution), failing closed on malformed requirements. Check **F10** with the `cross_request_replay`
fault and nine tests; SPEC.md separates settlement validity, requirement validity, authorisation and replay prevention.
Superseded by 1.4.0 on PyPI and deprecated on npm.

## 1.3.0

Published 2026-10-21. Fixes from an end-to-end review of 1.2.1, plus the EVM probe and 402 validation.

- Fixed: R3 no longer fails correct servers (the double never answers; 60 s deadline); the Action fails closed; S1 is
  version-aware; S4 splits errors from warnings; S0 is a real check; the Action runs on a pinned Node 24.
- Added: **Base Sepolia** (`eip155:84532`) next to Solana devnet, with `unsupported` as exit code 3; **R10**, the served
  response carries `PAYMENT-RESPONSE`; `x402conf resource URL...` and the Action's `resources` input (**P1 to P5** on any
  paid URL); facilitator credentials from the environment; `--version`; `--fail-on-error`; a stock `@x402/express`
  example; the README quickstart, badge and results; issue forms.
- Changed: documented exit codes match the code; spec links point to x402-foundation/x402; `tools/vv.py` reports the
  pushed criterion as pending on a pull request.
Superseded by 1.4.0 on PyPI and deprecated on npm.

## 1.2.1

Published 2026-10-20. The first release on PyPI (`x402-conformance`) and npm (`x402-conformance-svm`); the README for
public use (install table, exit codes, Action outputs, verifying the signed contract, security and contributing), and
Proofline links to github.com/Optitransfer/proofline.

## 1.2.0

Published 2026-10-20. `x402conf report` writes SARIF 2.1.0 and JUnit XML from the result files, with a fix link per
failed check; the Action's `sarif` and `junit` outputs; [FIXES.md](FIXES.md) for every check (S0 to S4, F1 to F9, R0 to
R9 and FX); `pipx run` and `uvx` one-command runs; packaging ready to publish.

## 1.1.0

Published 2026-10-20. M1 devnet evidence: F1 to F6 over real `/verify` and `/settle` on Solana devnet against my
self-hosted reference facilitator and its fault-injected builds (F4 fails on the reference, which deduplicates by
transaction but not by memo); the devnet runner retries RPC rate limits; the README gains a complete workflow file, the
inputs and outputs table, an example job summary and the devnet results.

## 1.0.1

Published 2026-10-20. Docs only: the Marketplace badge, a free-run offer, linked doc references, `docs/ADOPTION.md` and
an updated roadmap. The checks and the Action are unchanged; `@v1` stayed at 1.0.0.

## 1.0.0

Published 2026-10-20. The GitHub Action `x402 Conformance` (live **S1 to S4**, resource-server **R0 to R9**, offline
**F1 to F9**, a job summary and a `result` output); the TypeScript runner (`ts/`) with the facilitator double's fault
modes and the paid-route probe; the devnet runner `x402conf devnet`; `Pending.lean` for timeouts, `settlement_pending`
reconciliation and concurrent settles; the Proofline contract signed by the owner key; `docs/MATRIX.md` and
`docs/MANAGED.md`. F7 to F9 (pending retried once, a confirmed failure is terminal, a 503 or truncated body is never
credited) and the fixed reference double landed first in this release.

## 0.1.0

Published 2026-10-20. The first prototype: live checks S1 to S4 over `GET /supported`; safety checks F1 to F6 against
in-process facilitator doubles with devnet fixtures; Lean models `credit_sound`, `step_idem`, `step_nodup`,
`run_nodup`, `consume_once` and `only_open_consumes`, each depending only on `propext`; the first evidence run (Dexter,
PayAI and the x402.org facilitator pass S1 to S4); the Proofline contract and `tools/vv.py`, unsigned until 1.0.0.
