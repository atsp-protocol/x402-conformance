# Release map

One row per release: what it added, which contract tasks it closed and where it was published. The narrative for each
release is in [docs/RELEASES.md](docs/RELEASES.md), every change in [CHANGELOG.md](CHANGELOG.md), and what the suite
covers today, check by check, in [docs/COVERAGE.md](docs/COVERAGE.md). Each GitHub release carries a signed
`RELEASE-SUMS` manifest with the SHA-256 of every artefact.

## Releases

| release | date | checks added | other functionality added | contract tasks | published to |
|---|---|---|---|---|---|
| [1.6.0](docs/RELEASES.md#160) | 2026-10-24 | R17, R18, R19, F13, F14 | framework quickstarts for six stacks (`tools/quickstart.sh`); docs examples run by CI (`tools/doc_examples.py`); the implementation matrix (`evidence/impl-matrix/`) and the generated compatibility matrix (`tools/compat_matrix.py`); the published mutation matrix and the false-positive register; every Dependabot alert cleared | XC-48 done, closing XC-18, XC-19, XC-26 to XC-29 and XC-49, XC-50 (signed with this release); XC-22 and XC-24 shipped in 1.5.0 | PyPI, npm (svm and mcp), GHCR, MCP Registry, GitHub release, Marketplace `v1` |
| [1.5.0](docs/RELEASES.md#150) | 2026-10-23 | S5, F12, R12, R13, R15, R16, R16a, R22, R23, R24, C1, C2, C3 | the interdependency map and the docs-versus-code gate (`tools/interdeps.py`); the n-replica Lean models; the R20 corpus case; this release map, docs/RELEASES.md and docs/COVERAGE.md | XC-39 to XC-46 signed and done; XC-23, XC-30 done; XC-31 amended; XC-48 (1.6.0) added | PyPI, npm (svm and mcp), GHCR, MCP Registry, GitHub release, Marketplace `v1` |
| [1.4.0](docs/RELEASES.md#140) | 2026-10-23 | F11, P6, P7, R11 (R11a to R11f), R14, R20 (R20a, R20b); F5 extended | fail-closed oracle; credibility gate; evidence v2 and one report format; `demo` one-liners; `pr-comment` and `badge`; the corpus and `--share`; `docs/USING.md`; test helpers and matchers; MCP server package; Docker image and GitLab template; pytest plugin; Hono example | v1.5 addendum XC-22 to XC-37 signed; XC-09 to XC-16, XC-17, XC-20, XC-21, XC-25 done | PyPI, npm (svm and mcp), GHCR, MCP Registry, GitHub release |
| [1.3.1](docs/RELEASES.md#131) | 2026-10-21 | F10 | the verifier records the requirements hash per transaction | XC-08 | PyPI (superseded), npm (deprecated), GitHub release |
| [1.3.0](docs/RELEASES.md#130) | 2026-10-21 | R10, P1 to P5; S0 made real, S1 version-aware, S4 split into error and warning | Base Sepolia; `x402conf resource`; facilitator credentials from the environment; `--version`, `--fail-on-error`; Action fails closed on a pinned Node | | PyPI (superseded), npm (deprecated), GitHub release |
| [1.2.1](docs/RELEASES.md#121) | 2026-10-20 | | first release on PyPI and npm; public README | | PyPI, npm, GitHub release |
| [1.2.0](docs/RELEASES.md#120) | 2026-10-20 | | `x402conf report` (SARIF, JUnit); `docs/FIXES.md` for every check | | GitHub release |
| [1.1.0](docs/RELEASES.md#110) | 2026-10-20 | | devnet evidence for F1 to F6 (M1); RPC retries | XC-M1 run | GitHub release |
| [1.0.1](docs/RELEASES.md#101) | 2026-10-20 | | docs only: Marketplace badge, adoption page, roadmap | | GitHub release |
| [1.0.0](docs/RELEASES.md#100) | 2026-10-20 | F7, F8, F9, R0 to R9 | the GitHub Action; the TypeScript runner and facilitator double; `x402conf devnet`; `Pending.lean`; the signed contract | XC-00 to XC-07, XC-M3, XC-M4 | GitHub release |
| [0.1.0](docs/RELEASES.md#010) | 2026-10-20 | S1 to S4, F1 to F6 | the first prototype; six Lean theorems; the first evidence run; the unsigned contract and `tools/vv.py` | | GitHub release |

## Planned

| release | contract task | carries |
|---|---|---|
| next (on `main`, not released) | XC-33 to XC-37, XC-85 to XC-89, XC-93 to XC-98, XC-110 | the MCP transport (X1, X2) and `x402conf-svm mcp`; settlement preemption (R21); the `upto` and `batch-settlement` schemes (U1 to U3, B1 to B3); A2A and discovery (D1, G1); SIWX normative checks (W1 to W3); P9 and P10; R16a graded on a 405; C2 and C3 not applicable to a client that doesn't sign; paced live targets; the opt-in two-tier matrix and the free run program. See the Unreleased section of [CHANGELOG.md](CHANGELOG.md) |
| later | XC-32 | dropping the experimental label (the release gate in [docs/ROADMAP.md](docs/ROADMAP.md)) |

## Checks by release

| check | what it catches | since |
|---|---|---|
| S1 to S4 | a malformed `GET /supported` (shape, CAIP-2 IDs, Solana names, fee payers) | 0.1.0 (S0 and warnings since 1.3.0) |
| S5 | a kind `/supported` advertises that `/verify` cannot answer | 1.5.0 |
| P1 to P5 | a malformed 402 answer on any paid URL | 1.3.0 |
| P6, P7 | an oversized `PAYMENT-REQUIRED` header; a missing `extra.paymentFlow` | 1.4.0 |
| F1 to F6 | a facilitator that credits a malformed, under-, double-, replayed, early or broken payment | 0.1.0 (devnet since 1.1.0) |
| F7 to F9 | pending payments never finalised, failures stuck pending, broken transports credited | 1.0.0 |
| F10 | cross-request payment replay at the facilitator | 1.3.1 |
| F11 | `/verify` committing payment state | 1.4.0 |
| F12 | `/verify` accepting an unsupported network or a non-contract asset | 1.5.0 |
| F13, F14 | a payment in a different asset, or authorized for another network, accepted at the quoted amount and recipient | 1.6.0 |
| R0 to R9 | a resource server serving on a bad `/settle` answer, a timeout, `settlement_pending`, a failure or a duplicate | 1.0.0 |
| R10 | a missing `PAYMENT-RESPONSE` | 1.3.0 |
| R11, R11a to R11f | a payment for one route, price, recipient, method, query or SIWX session unlocking another | 1.4.0 |
| R12, R13 | one payment identifier granting more than once, in parallel or across replicas | 1.5.0 |
| R14 | a crash between `/settle` and the response settling again | 1.4.0 |
| R15, R16, R16a | settling a failed handler; settling a paid `HEAD`; an unpaid `HEAD` not answered 402 | 1.5.0 |
| R17, R18, R19 | a shared cache serving paid content unpaid; serving before a pending settlement is final; an `upfront` or `escrow` route executing before the check | 1.6.0 |
| R20, R20a, R20b | a client retry paying twice | 1.4.0 |
| R22, R23, R24 | a rewritten 2xx status; a charged abort; a 5xx on a malformed payment header | 1.5.0 |
| C1, C2, C3 | a client treating 402 as success, overpaying or paying outside its policy, falling back to V1 | 1.5.0 |
