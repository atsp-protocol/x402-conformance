# Verification and validation: traceability matrix

Each requirement maps to a [Proofline](https://github.com/Optitransfer/proofline) task in `proofline.json`. Each acceptance criterion is bound to one verifiable artefact,
such as a test id, a CI job, a Lean theorem with its axioms check, or a file hash. `tools/vv.py verify` checks every criterion and writes
a receipt, which the `vv` CI job uploads. A task counts as done only when it is listed in `vv/claims.json` and all its mandatory
criteria pass. A claimed task that fails, or any tracked file that no task owns, fails CI.

Contract state: **signed by the owner key** (`guard/owner.pub`). The owner signs on his own machine (`proofline contract sign`), and CI
verifies `proofline.json.sig` against `guard/owner.pub`. Anyone can repeat that check from a clone with
`node tools/verify-sig.mjs` or `npx -y @optitransfer/proofline@next contract verify-sig`.

| task | requirement | criterion | artefact | evidence |
|---|---|---|---|---|
| XC-00 | R-OPEN, R-GOV | XC-00-AC01: LICENSE is the Apache License 2.0 | `LICENSE` must be present for `Apache License\s+Version 2\.0` | CI `vv` receipt |
| XC-00 | R-OPEN, R-GOV | XC-00-AC02: NOTICE names Ryan Gillespie / Optitransfer | `NOTICE` must be present for `Ryan Gillespie / Optitransfer` | CI `vv` receipt |
| XC-00 | R-OPEN, R-GOV | XC-00-AC03: README carries the experimental label | `README.md` must be present for `(?i)experimental` | CI `vv` receipt |
| XC-00 | R-OPEN, R-GOV | XC-00-AC04: SECURITY.md routes reports through GitHub private vulnerability reporting | `SECURITY.md` must be present for `security/advisories/new` | CI `vv` receipt |
| XC-00 | R-OPEN, R-GOV | XC-00-AC05: SECURITY.md contains no email address | `SECURITY.md` must be absent for `[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}` | CI `vv` receipt |
| XC-00 | R-OPEN, R-GOV | XC-00-AC06: CODEOWNERS names @mgillr for everything | `.github/CODEOWNERS` must be present for `^\* @mgillr$` | CI `vv` receipt |
| XC-00 | R-OPEN, R-GOV | XC-00-AC07: CONTRIBUTING, CODE_OF_CONDUCT and CHANGELOG present | `test -s CONTRIBUTING.md && test -s CODE_OF_CONDUCT.md && test -s CHANGELOG.md` | CI `vv` receipt |
| XC-00 | R-OPEN, R-GOV | XC-00-AC08: Issue and PR templates present | `test -s .github/ISSUE_TEMPLATE/bug.yml && test -s .github/ISSUE_TEMPLATE/check-proposal.yml && test -s .github/pull_request_template.md` | CI `vv` receipt |
| XC-00 | R-OPEN, R-GOV | XC-00-AC09: Owner key pin present (guard/owner.pub, Ed25519 public key) | `guard/owner.pub` must be present for `BEGIN PUBLIC KEY` | CI `vv` receipt |
| XC-00 | R-OPEN, R-GOV | XC-00-AC10: Every changed file is inside this task's scope | changed files ⊆ scope.allow | CI `vv` receipt |
| XC-00 | R-OPEN, R-GOV | XC-00-AC11: Committed and pushed to main | HEAD on origin/main | CI `vv` receipt |
| XC-01 | R-S1, R-S2, R-S3, R-S4, R-SAFE-GET | XC-01-AC01: S1 rejects a SupportedResponse without kinds[], extensions[] and signers{} | `PYTHONPATH=src python3 -m unittest -v tests.test_live.Live.test_s1_shape` | CI `test` + `vv` |
| XC-01 | R-S1, R-S2, R-S3, R-S4, R-SAFE-GET | XC-01-AC02: S2 rejects a V2 kind whose network is not CAIP-2 | `PYTHONPATH=src python3 -m unittest -v tests.test_live.Live.test_s2_non_caip2` | CI `test` + `vv` |
| XC-01 | R-S1, R-S2, R-S3, R-S4, R-SAFE-GET | XC-01-AC03: S3 rejects V1 Solana names inside V2 kinds | `PYTHONPATH=src python3 -m unittest -v tests.test_live.Live.test_s3_v1_name_in_v2` | CI `test` + `vv` |
| XC-01 | R-S1, R-S2, R-S3, R-S4, R-SAFE-GET | XC-01-AC04: S4 rejects an invalid feePayer | `PYTHONPATH=src python3 -m unittest -v tests.test_live.Live.test_s4_bad_fee_payer` | CI `test` + `vv` |
| XC-01 | R-S1, R-S2, R-S3, R-S4, R-SAFE-GET | XC-01-AC05: S4 rejects a feePayer that is not a listed signer | `PYTHONPATH=src python3 -m unittest -v tests.test_live.Live.test_s4_fee_payer_not_signer` | CI `test` + `vv` |
| XC-01 | R-S1, R-S2, R-S3, R-S4, R-SAFE-GET | XC-01-AC06: A conformant body passes S1-S4 | `PYTHONPATH=src python3 -m unittest -v tests.test_live.Live.test_s_all_pass_on_conformant_body` | CI `test` + `vv` |
| XC-01 | R-S1, R-S2, R-S3, R-S4, R-SAFE-GET | XC-01-AC07: Live mode issues exactly one GET and nothing else | `PYTHONPATH=src python3 -m unittest -v tests.test_live.Live.test_live_mode_is_get_only` | CI `test` + `vv` |
| XC-01 | R-S1, R-S2, R-S3, R-S4, R-SAFE-GET | XC-01-AC08: Every changed file is inside this task's scope | changed files ⊆ scope.allow | CI `vv` receipt |
| XC-01 | R-S1, R-S2, R-S3, R-S4, R-SAFE-GET | XC-01-AC09: Committed and pushed to main | HEAD on origin/main | CI `vv` receipt |
| XC-02 | R-F1, R-F2, R-F3, R-F4, R-F5, R-F6 | XC-02-AC01: F1 catches a facilitator that verifies malformed input as valid | `PYTHONPATH=src python3 -m unittest -v tests.test_offline.Offline.test_f1_open_on_malformed_caught` | CI `test` + `vv` |
| XC-02 | R-F1, R-F2, R-F3, R-F4, R-F5, R-F6 | XC-02-AC02: F2 catches a facilitator that accepts dust | `PYTHONPATH=src python3 -m unittest -v tests.test_offline.Offline.test_f2_accept_dust_caught` | CI `test` + `vv` |
| XC-02 | R-F1, R-F2, R-F3, R-F4, R-F5, R-F6 | XC-02-AC03: F3 catches a facilitator with no duplicate-settlement cache | `PYTHONPATH=src python3 -m unittest -v tests.test_offline.Offline.test_f3_no_dup_cache_caught` | CI `test` + `vv` |
| XC-02 | R-F1, R-F2, R-F3, R-F4, R-F5, R-F6 | XC-02-AC04: F4 catches memo/nonce replay in a new transaction | `PYTHONPATH=src python3 -m unittest -v tests.test_offline.Offline.test_f4_no_memo_check_caught` | CI `test` + `vv` |
| XC-02 | R-F1, R-F2, R-F3, R-F4, R-F5, R-F6 | XC-02-AC05: F5 catches success reported before finality | `PYTHONPATH=src python3 -m unittest -v tests.test_offline.Offline.test_f5_success_before_final_caught` | CI `test` + `vv` |
| XC-02 | R-F1, R-F2, R-F3, R-F4, R-F5, R-F6 | XC-02-AC06: F6 the resource-server guard fails closed and credits once | `PYTHONPATH=src python3 -m unittest -v tests.test_offline.Offline.test_f6_guard_fails_closed_and_credits_once` | CI `test` + `vv` |
| XC-02 | R-F1, R-F2, R-F3, R-F4, R-F5, R-F6 | XC-02-AC07: The reference double passes every F check | `PYTHONPATH=src python3 -m unittest -v tests.test_offline.Offline.test_reference_passes_all` | CI `test` + `vv` |
| XC-02 | R-F1, R-F2, R-F3, R-F4, R-F5, R-F6 | XC-02-AC08: Fixtures target Solana devnet (CAIP-2) | `PYTHONPATH=src python3 -m unittest -v tests.test_offline.Offline.test_devnet_fixture_targets_devnet` | CI `test` + `vv` |
| XC-02 | R-F1, R-F2, R-F3, R-F4, R-F5, R-F6 | XC-02-AC09: Whole suite green: >= 15 tests, none skipped | `PYTHONPATH=src python3 -m unittest discover -s tests` | CI `test` + `vv` |
| XC-02 | R-F1, R-F2, R-F3, R-F4, R-F5, R-F6 | XC-02-AC10: Every changed file is inside this task's scope | changed files ⊆ scope.allow | CI `vv` receipt |
| XC-02 | R-F1, R-F2, R-F3, R-F4, R-F5, R-F6 | XC-02-AC11: Committed and pushed to main | HEAD on origin/main | CI `vv` receipt |
| XC-03 | R-LEAN | XC-03-AC01: Toolchain pinned to leanprover/lean4:v4.35.0 | `lean/lean-toolchain` must be present for `^leanprover/lean4:v4\.35\.0$` | CI `lean` + `vv` |
| XC-03 | R-LEAN | XC-03-AC02: lake build succeeds | `cd lean && lake build` | CI `lean` + `vv` |
| XC-03 | R-LEAN | XC-03-AC03: Six theorems are axiom-checked and none depends on a non-standard axiom or sorry | `python3 tools/lean_axioms.py` → `unexpected_axioms == 0` | CI `lean` + `vv` |
| XC-03 | R-LEAN | XC-03-AC04: At least six theorems are axiom-checked | `python3 tools/lean_axioms.py` → `theorems >= 6` | CI `lean` + `vv` |
| XC-03 | R-LEAN | XC-03-AC05: Theorem credit_sound is defined | `lean/X402Conformance/Settlement.lean` must be present for `^theorem credit_sound\b` | CI `lean` + `vv` |
| XC-03 | R-LEAN | XC-03-AC06: Theorem step_idem is defined | `lean/X402Conformance/Settlement.lean` must be present for `^theorem step_idem\b` | CI `lean` + `vv` |
| XC-03 | R-LEAN | XC-03-AC07: Theorem step_nodup is defined | `lean/X402Conformance/Settlement.lean` must be present for `^theorem step_nodup\b` | CI `lean` + `vv` |
| XC-03 | R-LEAN | XC-03-AC08: Theorem run_nodup is defined | `lean/X402Conformance/Settlement.lean` must be present for `^theorem run_nodup\b` | CI `lean` + `vv` |
| XC-03 | R-LEAN | XC-03-AC09: Theorem consume_once is defined | `lean/X402Conformance/Nonce.lean` must be present for `^theorem consume_once\b` | CI `lean` + `vv` |
| XC-03 | R-LEAN | XC-03-AC10: Theorem only_open_consumes is defined | `lean/X402Conformance/Nonce.lean` must be present for `^theorem only_open_consumes\b` | CI `lean` + `vv` |
| XC-03 | R-LEAN | XC-03-AC11: No sorry in the Lean sources | `! grep -rn --include=*.lean -w sorry lean/X402Conformance lean/X402Conformance.lean` | CI `lean` + `vv` |
| XC-03 | R-LEAN | XC-03-AC12: Every changed file is inside this task's scope | changed files ⊆ scope.allow | CI `vv` receipt |
| XC-03 | R-LEAN | XC-03-AC13: Committed and pushed to main | HEAD on origin/main | CI `vv` receipt |
| XC-04 | R-DOCS | XC-04-AC01: ARCHITECTURE.md has a diagram | `docs/ARCHITECTURE.md` must be present for ````mermaid` | CI `vv` receipt |
| XC-04 | R-DOCS | XC-04-AC02: SPEC.md maps S1 to spec text | `docs/SPEC.md` must be present for `^\\\| S1 \\\|` | CI `vv` receipt |
| XC-04 | R-DOCS | XC-04-AC03: SPEC.md maps S2 to spec text | `docs/SPEC.md` must be present for `^\\\| S2 \\\|` | CI `vv` receipt |
| XC-04 | R-DOCS | XC-04-AC04: SPEC.md maps S3 to spec text | `docs/SPEC.md` must be present for `^\\\| S3 \\\|` | CI `vv` receipt |
| XC-04 | R-DOCS | XC-04-AC05: SPEC.md maps S4 to spec text | `docs/SPEC.md` must be present for `^\\\| S4 \\\|` | CI `vv` receipt |
| XC-04 | R-DOCS | XC-04-AC06: SPEC.md maps F1 to spec text | `docs/SPEC.md` must be present for `^\\\| F1 \\\|` | CI `vv` receipt |
| XC-04 | R-DOCS | XC-04-AC07: SPEC.md maps F2 to spec text | `docs/SPEC.md` must be present for `^\\\| F2 \\\|` | CI `vv` receipt |
| XC-04 | R-DOCS | XC-04-AC08: SPEC.md maps F3 to spec text | `docs/SPEC.md` must be present for `^\\\| F3 \\\|` | CI `vv` receipt |
| XC-04 | R-DOCS | XC-04-AC09: SPEC.md maps F4 to spec text | `docs/SPEC.md` must be present for `^\\\| F4 \\\|` | CI `vv` receipt |
| XC-04 | R-DOCS | XC-04-AC10: SPEC.md maps F5 to spec text | `docs/SPEC.md` must be present for `^\\\| F5 \\\|` | CI `vv` receipt |
| XC-04 | R-DOCS | XC-04-AC11: SPEC.md maps F6 to spec text | `docs/SPEC.md` must be present for `^\\\| F6 \\\|` | CI `vv` receipt |
| XC-04 | R-DOCS | XC-04-AC12: THREAT-MODEL.md present with a disclosure rule | `docs/THREAT-MODEL.md` must be present for `(?i)disclosure` | CI `vv` receipt |
| XC-04 | R-DOCS | XC-04-AC13: ROADMAP.md lists milestones M1-M6 with budgets marked as my proposal | `docs/ROADMAP.md` must be present for `(?s)my proposal.*\\\| M1 \\\|.*\\\| M6 \\\|` | CI `vv` receipt |
| XC-04 | R-DOCS | XC-04-AC14: VV.md traces every task in this contract | `python3 -c "import json,re,sys;t=[x['id'] for x in json.load(open('proofline.json'))['tasks']];d=open('docs/VV.md').read();m=[i for i in t if i not in d];print(m);sys.exit(1 if m else 0)"` | CI `vv` receipt |
| XC-04 | R-DOCS | XC-04-AC15: Every changed file is inside this task's scope | changed files ⊆ scope.allow | CI `vv` receipt |
| XC-04 | R-DOCS | XC-04-AC16: Committed and pushed to main | HEAD on origin/main | CI `vv` receipt |
| XC-05 | R-CI | XC-05-AC01: Workflow defines jobs lint, test, lean and vv | `python3 -c "import re,sys;s=open('.github/workflows/ci.yml').read();sys.exit(0 if all(re.search(r'^  '+j+':',s,re.M) for j in ['lint','test','lean','vv']) else 1)"` | CI `lean` + `vv` |
| XC-05 | R-CI | XC-05-AC02: vv job uploads the receipt | `.github/workflows/ci.yml` must be present for `upload-artifact` | CI `vv` receipt |
| XC-05 | R-CI | XC-05-AC03: Signature state is checked and an unsigned contract is reported, not hidden | `tools/verify-sig.mjs` must be present for `unsigned: awaiting owner signature` | CI `vv` receipt |
| XC-05 | R-CI | XC-05-AC04: ruff and mypy --strict clean | `ruff check . && mypy` | CI `vv` receipt |
| XC-05 | R-CI | XC-05-AC05: Every changed file is inside this task's scope | changed files ⊆ scope.allow | CI `vv` receipt |
| XC-05 | R-CI | XC-05-AC06: Committed and pushed to main | HEAD on origin/main | CI `vv` receipt |
| XC-06 | R-EVID | XC-06-AC01: SHA256SUMS verifies | `cd evidence/2026-10-20 && sha256sum -c SHA256SUMS` | CI `vv` receipt |
| XC-06 | R-EVID | XC-06-AC02: run.json is a live GET-only run | `evidence/2026-10-20/run.json` must be present for `"mode": "live-GET-only"` | CI `vv` receipt |
| XC-06 | R-EVID | XC-06-AC03: At least one public facilitator body is committed | `evidence/2026-10-20/supported-x402.dexter.cash.json` | CI `vv` receipt |
| XC-06 | R-EVID | XC-06-AC04: Committed bodies re-check to the committed verdicts | `PYTHONPATH=src python3 -m unittest -v tests.test_live.Live.test_committed_evidence_reproduces` | CI `test` + `vv` |
| XC-06 | R-EVID | XC-06-AC05: Every changed file is inside this task's scope | changed files ⊆ scope.allow | CI `vv` receipt |
| XC-06 | R-EVID | XC-06-AC06: Committed and pushed to main | HEAD on origin/main | CI `vv` receipt |
| XC-07 | R-HYG | XC-07-AC01: Hygiene scan finds nothing | `python3 tools/vv.py hygiene` → `hits == 0` | CI `vv` receipt |
| XC-07 | R-HYG | XC-07-AC02: Every changed file is inside this task's scope | changed files ⊆ scope.allow | CI `vv` receipt |
| XC-07 | R-HYG | XC-07-AC03: Committed and pushed to main | HEAD on origin/main | CI `vv` receipt |
| XC-M1 | R-GRANT | XC-M1-AC01: Devnet runner module exists | `src/x402conf/devnet/runner.py` | CI `vv` receipt |
| XC-M1 | R-GRANT | XC-M1-AC02: Devnet evidence with SHA256SUMS committed | `cd evidence/devnet && sha256sum -c SHA256SUMS` | CI `vv` receipt |
| XC-M1 | R-GRANT | XC-M1-AC03: Devnet run uses the devnet CAIP-2 ID only | `evidence/devnet/run.json` must be present for `solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1` | CI `vv` receipt |
| XC-M1 | R-GRANT | XC-M1-AC04: Every changed file is inside this task's scope | changed files ⊆ scope.allow | CI `vv` receipt |
| XC-M1 | R-GRANT | XC-M1-AC05: Committed and pushed to main | HEAD on origin/main | CI `vv` receipt |
| XC-M2 | R-GRANT | XC-M2-AC01: >= 3 facilitator reports | `test $(ls evidence/matrix/*.json 2>/dev/null \| wc -l) -ge 3` | CI `vv` receipt |
| XC-M2 | R-GRANT | XC-M2-AC02: MATRIX.md records operator permission and disclosure status | `docs/MATRIX.md` must be present for `(?i)permission` | CI `vv` receipt |
| XC-M2 | R-GRANT | XC-M2-AC03: Every changed file is inside this task's scope | changed files ⊆ scope.allow | CI `vv` receipt |
| XC-M2 | R-GRANT | XC-M2-AC04: Committed and pushed to main | HEAD on origin/main | CI `vv` receipt |
| XC-M3 | R-GRANT | XC-M3-AC01: Pending model exists | `lean/X402Conformance/Pending.lean` | CI `lean` + `vv` |
| XC-M3 | R-GRANT | XC-M3-AC02: pending_never_credits theorem defined | `lean/X402Conformance/Pending.lean` must be present for `^theorem pending_never_credits\b` | CI `lean` + `vv` |
| XC-M3 | R-GRANT | XC-M3-AC03: Every changed file is inside this task's scope | changed files ⊆ scope.allow | CI `vv` receipt |
| XC-M3 | R-GRANT | XC-M3-AC04: Committed and pushed to main | HEAD on origin/main | CI `vv` receipt |
| XC-M4 | R-GRANT | XC-M4-AC01: action.yml exists | `action.yml` | CI `vv` receipt |
| XC-M4 | R-GRANT | XC-M4-AC02: TypeScript runner exists | `ts/package.json` | CI `vv` receipt |
| XC-M4 | R-GRANT | XC-M4-AC03: Every changed file is inside this task's scope | changed files ⊆ scope.allow | CI `vv` receipt |
| XC-M4 | R-GRANT | XC-M4-AC04: Committed and pushed to main | HEAD on origin/main | CI `vv` receipt |
| XC-M5 | R-GRANT | XC-M5-AC01: MAINTENANCE.md logs six monthly reports | `test $(grep -c '^## Month ' docs/MAINTENANCE.md 2>/dev/null \|\| echo 0) -ge 6` | CI `vv` receipt |
| XC-M5 | R-GRANT | XC-M5-AC02: Every changed file is inside this task's scope | changed files ⊆ scope.allow | CI `vv` receipt |
| XC-M5 | R-GRANT | XC-M5-AC03: Committed and pushed to main | HEAD on origin/main | CI `vv` receipt |
| XC-M6 | R-GRANT | XC-M6-AC01: ADOPTION.md lists >= 3 external repos with links to their CI runs | `test $(grep -c '^- repo: ' docs/ADOPTION.md 2>/dev/null \|\| echo 0) -ge 3` | CI `vv` receipt |
| XC-M6 | R-GRANT | XC-M6-AC02: ADOPTION.md lists >= 5 facilitators with published results | `test $(grep -c '^- facilitator: ' docs/ADOPTION.md 2>/dev/null \|\| echo 0) -ge 5` | CI `vv` receipt |
| XC-M6 | R-GRANT | XC-M6-AC03: Every changed file is inside this task's scope | changed files ⊆ scope.allow | CI `vv` receipt |
| XC-M6 | R-GRANT | XC-M6-AC04: Committed and pushed to main | HEAD on origin/main | CI `vv` receipt |

Requirement ids: R-OPEN/R-GOV (open source, governance), R-S1..R-S4 and R-SAFE-GET (live checks, GET only), R-F1..R-F6 (safety checks),
R-LEAN (proofs), R-DOCS, R-CI, R-EVID (evidence), R-HYG (hygiene), R-GRANT (the roadmap milestones M1-M6 in [ROADMAP.md](ROADMAP.md), my proposal).
