# Quickstart: Next (@x402/next 2.28.0, App Router API route)

The smallest paid route on this stack: one `GET` at $0.001 on Solana devnet (set `EXAMPLE_NETWORK=eip155:84532` for Base Sepolia). It reads its facilitator from `X402_FACILITATOR_URL` and its port from `PORT`.

From the repository root, one command goes from a clean checkout to a first conformance result:

```
sh tools/quickstart.sh next
```

To run it by hand, from this directory, with a facilitator at `X402_FACILITATOR_URL`:

```
npm ci && X402_FACILITATOR_URL=http://127.0.0.1:4402 npx next dev -p 4020 -H 127.0.0.1   # the route is /api/paid
```
