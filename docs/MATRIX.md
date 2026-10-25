# Facilitator matrix

Devnet results for x402 V2 facilitators on Solana: F1 to F6 over real `/verify` and `/settle`, run by
`x402conf devnet`. I run it against a third-party facilitator only with that operator's written **permission**,
and only on devnet. Each third-party report will sit in `evidence/matrix/<operator>.json` with its permission record linked below.

Disclosure: a failing check in someone else's facilitator goes to that operator privately first. I publish it only
after a fix or 90 days after the report, whichever is first (SECURITY.md). Until then the row says "under disclosure".

Every row in this file has an environment: **testnet** (run against a public testnet or devnet endpoint), **devnet**
(run locally, from source or fixtures, on loopback with testnet ids), **live-not-run** (mainnet only, not exercised) or
**out-of-reach** (hosted only, or nothing public to run against). Results are checks passed out of checks run, and
failed checks are a count only. Rows are listed by name, never by result, and carry no composite number.

| facilitator | environment | operator permission | last run | version tested | passed/run | failed | disclosure status |
|---|---|---|---|---|---|---|---|
| self-hosted reference (@x402/core + @x402/svm 2.28.0) | devnet | mine, not needed | [2026-10-20](../evidence/devnet) | @x402/core, @x402/svm 2.28.0 | 5/6 | 1 | n/a: my own instance of open-source code |
| facilitator.payai.network | out-of-reach: hosted only, until the operator gives permission | not yet requested | none | - | - | - | n/a |
| facilitator.x402.rs | out-of-reach: hosted only, until the operator gives permission | not yet requested | none | - | - | - | n/a |
| x402.dexter.cash | out-of-reach: hosted only, until the operator gives permission | not yet requested | none | - | - | - | n/a |
| x402.org/facilitator | out-of-reach: hosted only, until the operator gives permission | not yet requested | none | - | - | - | n/a |
| facilitator.daydreams.systems | out-of-reach: hosted only, until the operator gives permission | not yet requested | none | - | - | - | n/a |
| facilitator.goplausible.xyz | out-of-reach: hosted only, until the operator gives permission | not yet requested | none | - | - | - | n/a |
| facilitator.ultravioletadao.xyz | out-of-reach: hosted only, until the operator gives permission | not yet requested | none | - | - | - | n/a |

In the live run of 2026-10-20 ([evidence/2026-10-20-v1.3.0](../evidence/2026-10-20-v1.3.0)), seven named facilitators advertise a V2 `exact` kind on Solana devnet in `GET /supported`: the seven above. One more is withheld in that run. XC-M2 is done when at least
three facilitators have a report here, each with its permission recorded. No third-party report exists yet.

Per-check results for the reference are in [evidence/devnet](../evidence/devnet).

Want your facilitator in the matrix? See [rerun or get listed](#rerun-or-get-listed). For a hosted facilitator, the issue is the permission record.

## Self-hosted open-source facilitators

Seventeen facilitators publish their source and can run on my own machine. I build each one at a pinned commit, start it
on 127.0.0.1 against public testnets with throwaway keys, and run the suite against that loopback instance: `x402conf live`
(S0 to S4) today, and the verify-only F checks on Base Sepolia once XC-51 lands. No hosted instance is called and no operator
permission is needed, because the instance is mine (the same footing as the self-hosted reference above). A failing check
still goes to the project privately first (SECURITY.md); until then its row says "under disclosure".

| facilitator | environment | source @ pin (version tested) | networks | suite today | status |
|---|---|---|---|---|---|
| x402 TypeScript example | devnet | x402-foundation/x402 @ 2cf50eb | Base Sepolia, Solana devnet | S0-S4 on loopback | run on loopback 2026-10-24; F checks with XC-51 |
| x402 Python example | devnet | x402-foundation/x402 @ 2cf50eb | Base Sepolia, Solana devnet | S0-S4 on loopback | as above |
| x402 Go example | devnet | x402-foundation/x402 @ 2cf50eb | Base Sepolia, Solana devnet | S0-S4 on loopback | as above |
| x402-rs | devnet | x402-rs/x402-rs @ e75adda | Base Sepolia | S0-S4 on loopback | as above |
| qntx facilitator | devnet | qntx/facilitator @ df75698 | Base Sepolia | S0-S4 on loopback | as above |
| faremeter | devnet | faremeter/faremeter @ 68e024e | Base Sepolia, SKALE and Monad testnets | S0-S4 on loopback | as above |
| daydreams | devnet | daydreamsai/facilitator @ 9d99d61 | Base Sepolia | S0-S4 on loopback (bearer token) | as above |
| mogami | devnet | mogami-tech/x402-facilitator @ 8e76b2d | Base Sepolia | S0-S4 on loopback | as above |
| raid-guild | devnet | raid-guild/x402-facilitator-go @ 83744bf | Base Sepolia | S0-S4 on loopback | as above |
| agent-guide go-x402-facilitator | devnet | agent-guide/go-x402-facilitator @ 164747c | Base Sepolia (V1) | S0-S4 on loopback | V1 only |
| Stellar x402 | devnet | stellar/x402-stellar @ 953caa5 | Stellar testnet | S0-S4 on loopback | F checks need a Stellar `exact` client |
| Accensa Stellar | devnet | accensa/x402-facilitator-stellar @ 016c16b | Stellar testnet | S0-S4 on loopback | as above |
| Casper x402 | devnet | make-software/casper-x402 @ 3ee705e | Casper testnet | S0-S4 on loopback | F checks need a Casper client |
| Fireblocks | out-of-reach: needs a custody key | fireblocks/x402-facilitator @ ca7dd59 | Base Sepolia | not yet | a payments API, not the facilitator API; needs a custody key |
| OpenZeppelin relayer plugin | out-of-reach: needs an OpenZeppelin Relayer | OpenZeppelin/relayer-plugin-x402-facilitator @ 831fb05 | Stellar testnet | not yet | runs only inside an OpenZeppelin Relayer |
| TRDEFI Arc | live-not-run: no testnet configuration at this pin | TRDEFI/arc-x402-facilitator @ efbe999 | Arc | not yet | no testnet configuration at this pin |
| PipRail | out-of-reach: a client, no server | piprail/piprail @ a8d7c35 | none | n/a | a facilitator client, no server |

## Implementation matrix

<!-- compat-matrix:start -->

Stock example servers at pinned SDK versions, probed on loopback behind the facilitator double (R0 to R10), so the environment is devnet: local, from source, with testnet ids. Generated by `python3 tools/compat_matrix.py --write` from `evidence/impl-matrix/*/run.json`; CI fails when this table or `docs/compat-matrix.json` is stale, a row has no hashes, or a hash does not match its file. Each row links the run it was built from and the `SHA256SUMS` that pins it. Passed/run counts the checks that ran; failed is a count only.

| row | environment | stack | version tested | network | passed/run | failed | last run | hashes | badge | rerun / get listed | missing check? |
|---|---|---|---|---|---|---|---|---|---|---|---|
| <a id="row-express-2.27.0"></a>express-2.27.0 | devnet | express | 2.27.0 | `solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1` | 11/11 | 0 | [2026-10-24](../evidence/impl-matrix/express-2.27.0/run.json) | [`4cb84a761d1f`](../evidence/impl-matrix/express-2.27.0/SHA256SUMS) | [svg](https://atsp-protocol.github.io/x402-conformance/badge/express-2.27.0.svg) | [rerun](#rerun-or-get-listed) | [propose a check](https://github.com/atsp-protocol/x402-conformance/issues/new?template=check-proposal.yml) |
| <a id="row-express-2.28.0"></a>express-2.28.0 | devnet | express | 2.28.0 | `solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1` | 11/11 | 0 | [2026-10-24](../evidence/impl-matrix/express-2.28.0/run.json) | [`dc7730d56b44`](../evidence/impl-matrix/express-2.28.0/SHA256SUMS) | [svg](https://atsp-protocol.github.io/x402-conformance/badge/express-2.28.0.svg) | [rerun](#rerun-or-get-listed) | [propose a check](https://github.com/atsp-protocol/x402-conformance/issues/new?template=check-proposal.yml) |
| <a id="row-fastapi-2.25.0"></a>fastapi-2.25.0 | devnet | fastapi | 2.25.0 | `solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1` | 11/11 | 0 | [2026-10-23](../evidence/impl-matrix/fastapi-2.25.0/run.json) | [`de0969cd88e4`](../evidence/impl-matrix/fastapi-2.25.0/SHA256SUMS) | [svg](https://atsp-protocol.github.io/x402-conformance/badge/fastapi-2.25.0.svg) | [rerun](#rerun-or-get-listed) | [propose a check](https://github.com/atsp-protocol/x402-conformance/issues/new?template=check-proposal.yml) |
| <a id="row-flask-2.25.0"></a>flask-2.25.0 | devnet | flask | 2.25.0 | `solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1` | 11/11 | 0 | [2026-10-23](../evidence/impl-matrix/flask-2.25.0/run.json) | [`eae4e6e5f705`](../evidence/impl-matrix/flask-2.25.0/SHA256SUMS) | [svg](https://atsp-protocol.github.io/x402-conformance/badge/flask-2.25.0.svg) | [rerun](#rerun-or-get-listed) | [propose a check](https://github.com/atsp-protocol/x402-conformance/issues/new?template=check-proposal.yml) |
| <a id="row-hono-2.28.0"></a>hono-2.28.0 | devnet | hono | 2.28.0 | `solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1` | 11/11 | 0 | [2026-10-24](../evidence/impl-matrix/hono-2.28.0/run.json) | [`892b9a4a29d0`](../evidence/impl-matrix/hono-2.28.0/SHA256SUMS) | [svg](https://atsp-protocol.github.io/x402-conformance/badge/hono-2.28.0.svg) | [rerun](#rerun-or-get-listed) | [propose a check](https://github.com/atsp-protocol/x402-conformance/issues/new?template=check-proposal.yml) |

<!-- compat-matrix:end -->

## Rerun or get listed

Every row can be added or refreshed by the project itself, without waiting for me. You need no permission to test
your own code or your own testnet endpoint.

1. Run the suite on your own testnet or devnet endpoint, or on a local build: the CLI, the GitHub Action or the MCP
   server, as in [RUN-IT-YOURSELF.md](RUN-IT-YOURSELF.md). Never point it at mainnet or at someone else's facilitator.
2. Open the [Add or update my row](https://github.com/atsp-protocol/x402-conformance/issues/new?template=add-or-update-row.yml)
   issue form with your details, your consent to be listed and a link to your run.
3. Open a PR (or I open it from your issue) that adds the run as `evidence/impl-matrix/<row>/` with its `run.json`, a
   README and `SHA256SUMS`, then run `python3 tools/compat_matrix.py --write`. CI regenerates the row and its badge from
   that evidence and fails if anything was edited by hand.

A row is listed only with consent recorded in the issue or the PR. A failing check in a third-party project goes to that
project privately first (SECURITY.md); until then the row shows the failed count and "under disclosure".

Missing a check? Propose one with the [check proposal](https://github.com/atsp-protocol/x402-conformance/issues/new?template=check-proposal.yml)
form (see CONTRIBUTING.md). Proposals follow the project's governance: spec text first, a failing faulty build and a
passing control.

## Badge and data licence

A row with committed evidence has a badge, "Tested with x402-conformance", at
`https://atsp-protocol.github.io/x402-conformance/badge/<row>.svg`, linking back to its row. The terms are in
[BADGE.md](BADGE.md). It says a run exists. It does not certify anything and it is not an endorsement.

The public matrix data and committed evidence are licensed CC BY 4.0 ([DATA-LICENSE](../DATA-LICENSE)). Attribution:
"x402-conformance by Optitransfer", https://github.com/atsp-protocol/x402-conformance. The code is Apache-2.0
([LICENSE](../LICENSE), [NOTICE](../NOTICE)).
