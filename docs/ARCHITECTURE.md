# Architecture

<!-- docs-aligned:status -->
Status: experimental. The latest release is 1.6.0; this page describes `main`. Expect changes.
<!-- /docs-aligned:status -->

```mermaid
flowchart LR
  subgraph suite[x402-conformance]
    CLI[x402conf CLI] --> LIVE[Live checks S0-S4<br/>GET /supported only]
    CLI --> RES[402 checks P1-P7, P9, P10<br/>unpaid GETs; R16a, R24 with flags]
    PROBE[x402conf-svm probe<br/>R0-R11, R14, R20] --> DBL[Facilitator double<br/>loopback, fault modes]
    LIB[x402-conformance-svm library<br/>R12, R13, R15-R19, R16a, R21-R24, C1-C3,<br/>W1-W3, U1-U3, B1-B3, D1, G1, X1, X2] --> DBL
    DBL -->|X402_FACILITATOR_URL| RS[(Your resource server<br/>Solana devnet or Base Sepolia)]
    CLI --> OFF[Safety checks F1-F14, S5]
    OFF --> DOUBLES[Facilitator doubles<br/>Reference + Faulty]
    CLI --> DEVNET[Devnet runner F1-F6<br/>self-hosted or permitted facilitator]
    GUARD[ResourceServerGuard<br/>credit rule] --- OFF
    LEAN[lean/ proofs<br/>Settlement, Nonce, Pending, Replicas] -. models .- GUARD
    VV[tools/vv.py<br/>Proofline V&V] --> RCPT[receipts]
  end
  LIVE -->|GET| PUB[(Public facilitators)]
  RES -->|GET| PAID[(Paid URLs, any network)]
  DEVNET -->|/verify /settle| OWN[(Facilitator under test<br/>on Solana devnet)]
  LIVE --> EVID[evidence/DATE<br/>raw bodies + SHA256SUMS]
```

## Components
| path | role |
|---|---|
| `src/x402conf/spec.py` | Identifiers quoted from the x402 V2 spec and the Solana `exact` scheme (CAIP-2 IDs, error codes), and `CATALOG`: the profile, spec basis, controls and faulty builds of every check |
| `src/x402conf/harness.py` | The checks. `run_live` makes exactly one GET per target (S0-S4); `run_resource` makes one unpaid GET per paid URL (P1-P7, and P9 when the 402 carries the bazaar extension). `check_safety` runs F1 to F6 and F10 to F14 against anything that has `verify` and `settle`, F7 to F9 against a double whose simulated chain it can advance between retries, and S5 when the facilitator also has `supported()` |
| `src/x402conf/mock.py` | The `Reference` double, which behaves as the spec asks, and `Faulty` doubles, each reproducing one known failure. `Chain` is the simulated ledger F7 to F9 advance |
| `src/x402conf/fixtures/devnet.json` | Devnet requirements (`solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1`, devnet USDC) and the test vectors |
| `lean/` | Lean 4 models of the credit rule (`Settlement.lean`), the nonce state machine (`Nonce.lean`), timeouts, `settlement_pending` reconciliation and concurrent settles (`Pending.lean`), and n replicas with a shared atomic check-and-set versus partitioned caches (`Replicas.lean`), built by `lake build`. `tools/lean_axioms.py` runs `lean/Axioms.lean`, and CI fails on an unexpected axiom |
| `tools/vv.py` | Verifies every Proofline criterion in `proofline.json` and writes receipts |
| `src/x402conf/devnet/` | The devnet runner: F1 to F6 over real `/verify` and `/settle` on Solana devnet, with a self-hosted reference facilitator (`node/`) and its fault-injected builds |
| `ts/` | The `x402-conformance-svm` npm package: the facilitator double, the resource-server and client checks, the Node CLI and the test-framework entry points, with example servers and clients in `ts/example/` |
| `ts/src/double.ts` | The facilitator double: `GET /supported`, `POST /verify` and `POST /settle` on loopback with one switchable fault mode, on Solana devnet and Base Sepolia. It never touches a chain or a key |
| `ts/src/probe.ts` | R0-R10: the paid route under each fault mode of the double |
| `ts/src/cli.ts` | The `x402conf-svm` command: `probe` (R0-R11, R14 with `--crash`, R20 with `--retry`), `resource` (P1-P7), `live --url` (P1-P7, R16a and R24 on one paid URL, unpaid and paced), `mcp` (X1 and P3-P5, P7 on a paid MCP tool, unpaid) and `demo` |
| `ts/src/catalog.ts` | The profile and spec basis of every check, the same labels as `CATALOG` in `spec.py` |
| `ts/src/index.ts` | The library entry point. R12, R13, R15 to R19, R21 to R23, C1 to C3, W1 to W3, U1 to U3, B1 to B3, D1, G1 and X2 run only through its exports (`probeParallel`, `probeReplicas`, `probeDelivery`, `probeHead`, `probeCacheLeak`, `probePending`, `probeFlows`, `probePreempt`, `probeStatus`, `probeAbort`, `checkClientHandles402`, `checkClientOfferPolicy`, `checkClientKeepsV2`, `probeSiwx`, `probeUpto`, `probeBatch`, `checkDiscovery`, `checkA2aMirrorsHttp`, `probeMcpTransport`), not the Action; R16a, R24 and X1 also run from the CLIs (`probeUnpaidHead`, `probeMalformedHeader`, `checkMcpPaymentRequired`) |
| `ts/src/concurrency.ts` | R12 and R13: parallel requests (eight by default) with one payment-identifier id, and one id sent to two replicas |
| `ts/src/crash.ts` | R14: a crash between a successful `/settle` and the response |
| `ts/src/delivery.ts`, `ts/src/head.ts`, `ts/src/head-unpaid.ts`, `ts/src/status.ts` | R15 (no settlement when the handler fails), R16 (a paid `HEAD` is never settled), R16a (an unpaid `HEAD` gets the same 402 as `GET`) and R22 (the paid response keeps the handler's 2xx status and headers) |
| `ts/src/cache.ts`, `ts/src/pending.ts`, `ts/src/flow.ts` | R17 (a shared cache never serves paid content unpaid), R18 (a pending, late or unanswered settlement) and R19 (`upfront` and `escrow` flows) |
| `ts/src/preempt.ts` | R21: settlement preemption for caller-unbound settlement (Permit2 on Base Sepolia) |
| `ts/src/siwx.ts` | W1 to W3: the sign-in-with-x message rules on a paid route |
| `ts/src/schemes.ts` | U1 to U3 for the `upto` scheme and B1 to B3 for `batch-settlement`, with the scheme double (`startSchemeDouble`) |
| `ts/src/discovery.ts` | D1 (a facilitator's discovery API) and G1 (an A2A agent's paid skill against the HTTP route it mirrors) |
| `ts/src/mcp-transport.ts`, `ts/src/mcp-seller.ts` | X1 and X2 on paid MCP tools over Streamable HTTP, and `x402conf-svm mcp`: X1 and P3-P5, P7 on the offer in an unpaid tool result |
| `ts/src/pace.ts` | Pacing for live targets, the TypeScript twin of `src/x402conf/pacing.py` |
| `ts/src/provenance.ts` | The `provenance` block (suite, version, publisher, repository) every results document carries |
| `ts/src/abort.ts`, `ts/src/header.ts` | R23 (a client abort during settle is recoverable) and R24 (a malformed payment header gets a 4xx) |
| `ts/src/client-status.ts`, `ts/src/client-offers.ts`, `ts/src/client-version.ts` | C1, C2 and C3: a client's handling of a 402, its choice among several offers and its payment version, graded through a recording proxy in front of a paid route |
| `src/x402conf/cli.py` | The `x402conf` command: `live`, `resource` (with `--well-known` for P10, `--malformed-header` for R24 and `--unpaid-head` for R16a), `offline`, `report` (SARIF, JUnit and `--badge`), `demo`, `pr-comment` and `devnet` |
| `src/x402conf/discovery.py` | P9 and P10: the bazaar discovery `info` in a 402 against the schema it ships with, and the host's `/.well-known/x402` manifest against the live 402 |
| `src/x402conf/external.py` | R16a and R24 from outside the project's stack, the Python ports of `ts/src/head-unpaid.ts` and `ts/src/header.ts`, for `x402conf resource` and the tier-1 queue |
| `src/x402conf/pacing.py` | Pacing for live targets: at least 5 s between requests off loopback (`--min-interval`), an optional cap (`--max-requests`) and one log line per request |
| `src/x402conf/tiers.py` | The matrix's two tiers (External-verified and Full suite, self-hosted) and the attestation of a self-hosted full run |
| `src/x402conf/pytest_plugin.py` | The pytest plugin the package registers: the `x402` fixture, `--x402-report-dir` and `--x402-share` |
| `src/x402conf/types.py` | Typed shapes used by the harness |
| `tools/interdeps.py` | Generates `docs/INTERDEPENDENCY.md`. `--check` fails on a stale map, `--drift` on docs that disagree with the code, `--gate` on a pull request that leaves a downstream doc, contract or test component neither touched nor acknowledged, and `--docs` (the `docs-aligned` CI job) on any derived number, table or block in the docs that no longer matches the code and the contract; `--docs --fix` regenerates them |
| `tools/check_ids.py` | Writes `docs/check-ids.json` from the catalogue. `--check --since v1.6.0` fails when that registry is stale, when an id published at v1.6.0 is missing, or when that id's property changed without a deprecation entry in `CHANGELOG.md` |
| `tools/build_coverage.py` | Generates the check table in `docs/COVERAGE.md` from `CATALOG` |
| `tools/mutation_matrix.py` | Builds `docs/site/mutation-matrix.json`: which faulty build each check is proven to catch |
| `tools/compat_matrix.py`, `tools/row_from_evidence.py` | The compatibility matrix and the reference baseline in `docs/MATRIX.md`, generated from `evidence/impl-matrix/`; and one matrix row from a run's evidence bundle |
| `tools/matrix_rows.py`, `tools/matrix_freshness.py` | The listed-projects rows (`matrix/rows/`), checked against `matrix/schema/row.schema.json` and rendered into `docs/MATRIX.md` and the Pages table; and the weekly freshness check |
| `tools/run_queue.py`, `tools/attestation.py` | The free-run queue (tier 1, external checks only) and the verification of a tier-2 attestation |
| `tools/doc_examples.py` | Runs every docs example marked runnable against the bundled mock (A8) |
| `tools/quickstart.sh` | From a clean checkout to a first result for one framework quickstart (A4) |
| `tools/verify-sig.mjs` | Checks the owner signature on `proofline.json` against the key pinned in `guard/owner.pub` |
| `vv/claims.json` | The contract tasks claimed as done; `tools/vv.py` fails CI if any of them misses a mandatory criterion |
| `examples/python/` | A stock x402 Python SDK FastAPI server that the pytest plugin test runs |
| `action.yml` | The GitHub Action: live, 402, resource-server and offline checks, a job summary, SARIF and JUnit, a badge file and an opt-in sticky pull request comment (`pr-comment`). It fails closed when a requested run leaves no results, and runs the probe on a pinned Node that never goes on the caller's PATH |
| `ts/src/binding.ts` | R11: payment-to-request binding on a real resource server (two routes, method, query, encoded path, SIWX) |
| `ts/src/retry.ts` | R20: retry double-pay. The client times out before `/settle` answers and retries with a fresh payment under the same key (R20a) or the same signed payment (R20b); `checkClientRetry` grades a client's retry |
| `ts/src/resource.ts` | P1-P7 in Node, a port of `run_resource` that CI checks against the Python CLI |
| `ts/src/testing.ts`, `ts/src/report.ts` | `runConformance()`, the vitest and jest matchers, `assertX402Conformance()` and the shared `x402-conformance.report/1` format every entry point writes |
| `ts/src/mock-server.ts` | The bundled mock resource server behind `x402conf-svm demo` |
| `ts/src/corpus.ts` | Opt-in `--share`: an anonymised corpus case and a pre-filled issue link; nothing is sent |
| `ts/mcp/` | The MCP server and the Vercel AI SDK and LangChain tools, thin entry points into the same checks |
| `ts/docker/`, `ts/ci/gitlab/` | The Docker image (Python CLI, Node probe, MCP server) and the GitLab CI template |
| `corpus/` | The regression corpus: the case and report schemas, the case template, accepted cases in `corpus/cases/` and the shared anonymisation fixture in `corpus/fixtures/` |
| `evidence/` | Dated live results with raw bodies and hashes, and the devnet run in `evidence/devnet` |

## Boundaries
- Live and resource modes are GET-only, and this is enforced in code and tested (`test_live_mode_is_get_only`, `test_resource_mode_is_get_only`).
- A facilitator credential comes only from the environment, is sent only to the one host named with it, and is never printed (`test_auth_header_only_to_its_host_and_never_printed`).
- The suite holds no keys of yours. The devnet runner uses throwaway devnet keypairs from a directory outside the repository (`X402C_KEYS`); they are never committed, and the runner refuses a keys directory inside the repository.
- The devnet runner refuses any network but Solana devnet (checked by genesis hash) and any third-party facilitator without the operator's written permission.
- No mainnet payments, ever.
