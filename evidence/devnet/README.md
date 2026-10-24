# Devnet evidence (M1), 2026-10-20, x402-conformance 1.1.0

`x402conf devnet --faults` ran F1 to F6 over real x402 V2 `/verify` and `/settle` against my self-hosted reference
facilitator (`@x402/core` 2.28.0 `x402Facilitator` with the `@x402/svm` 2.28.0 `exact` scheme) on Solana devnet
(`solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1`). It then ran each fault-injected build of that facilitator. The payments
used a throwaway devnet test token with 6 decimals and throwaway devnet keypairs, which are never committed. No mainnet
was involved and no real funds moved.

Files: [`run.json`](run.json) is the full machine-readable result, and [`SHA256SUMS`](SHA256SUMS) is its hash
(`sha256sum -c SHA256SUMS`).

## Reference facilitator

| check | result | on chain (devnet explorer) |
|---|---|---|
| F1 malformed payload fails closed | pass: `isValid=false`, `invalid_exact_svm_payload_transaction_could_not_be_decoded` | none, `/verify` only |
| F2 dust amount is rejected | pass: `isValid=false`, `invalid_exact_svm_payload_amount_mismatch` | none, `/verify` only |
| F3 the same payload settled twice succeeds once | pass: the second settle answered `duplicate_settlement`, and the recipient received the amount once | [3Z6SFs…](https://explorer.solana.com/tx/3Z6SFsFqg7ktDouaECTXrkXUww4oaqUJS4WnAU5d8LHf6jTfNK38CM35J2yAYGM55N99sXvFWgXrBnSiJhiAUyUi?cluster=devnet) |
| F4 a used memo in a new transaction is rejected | **fail**: two different transactions carrying the same memo both settled, and the recipient received the amount twice | [2L3JxE…](https://explorer.solana.com/tx/2L3JxEsxerWsTgefipXGkgABhLA43WNhZY1cgwjnYhq6r5KW1cYqLt7dndo6y9zuw8qLvEVvZbs6ywRVUUAPMh9q?cluster=devnet), [2U31kB…](https://explorer.solana.com/tx/2U31kByAS9V1kZg7dfwkVmdDJkS4wDreFVH1KjuxUHzBoNqzX51CiamhuUgEzmDDSoxA6LQa2eQwSGin3Hcg7y4v?cluster=devnet) |
| F5 success only after confirmation | pass: the transaction was finalized when `/settle` answered success | [3GyFs6…](https://explorer.solana.com/tx/3GyFs63mQ7hBfT4Hurnpsut3ZVehNKgyUEX83WgLJoG3shnGaNcNGzyeH6DtvkFjgZZgcdbreD9o1vVVZz6PA7mG?cluster=devnet) |
| F6 a timeout or garbage answer never credits | pass: no credit on the timeout or on the garbage answer, and no double credit on retry | see `run.json` |

**About the F4 result.** The reference facilitator deduplicates by transaction (that is F3, and it passes), but it
does not track the memo across different transactions. Each of the two transactions was a real payment signed by the
payer, so the seller was paid twice rather than losing money. Still, a resource server that binds one purchase to one
memo has to reject the second payment itself, because the facilitator will not. I record the result as it came out
and haven't changed the check to make it pass.

**One more observation from F6.** The payment whose `/settle` call timed out did land on chain, and retrying the same
payload afterwards answered `duplicate_settlement`, so it was never credited. That is safe for the seller (no double
credit), but a buyer in that position needs the resource server to reconcile on chain rather than rely on a retry.

## Fault-injected builds

Every fault-injected build failed the check it targets, so each check is shown to catch the fault it exists for.

| build | injected fault | caught by |
|---|---|---|
| `open_on_malformed` | `/verify` answers `isValid=true` when the payload does not decode | F1 |
| `accept_dust` | `/verify` checks the amount against 1 instead of the requirements | F2 |
| `success_unsent` | `/settle` answers success with a transaction it never sent | F5 (the transaction does not exist on chain) |

Setup transaction (test mint and token accounts):
[NoU2pE…](https://explorer.solana.com/tx/NoU2pENnoNSev2C5JoXNXjtLJSxZLYxiX76R9DJcj8FJxsKfGhgD4mzkd86UMJtC3J4yVJRFMCr8CLtQ1PiVWHX?cluster=devnet).

## Reproduce

    cd src/x402conf/devnet/node && npm ci
    X402C_KEYS=<a directory outside the repo with throwaway devnet keypairs> node setup.mjs
    cd ../../../.. && PYTHONPATH=src X402C_KEYS=<same directory> python3 -m x402conf devnet --faults --evidence <out-dir>

The keys directory needs `feepayer.json`, `client.json` and `payto.json`, and the fee payer needs a little devnet SOL
from the faucet. `X402C_RPC` selects the devnet RPC (default `https://api.devnet.solana.com`); this run used
`solana-devnet.api.onfinality.io` (`rpc_host` in `run.json`). Public RPCs rate-limit, so the runner and the node scripts
retry HTTP 429, 500, 502, 503 and 504 answers and failed requests with exponential backoff, up to 8 retries; the node
scripts honour `Retry-After`, and `X402C_RPC_RETRIES` sets their limit.
