# hono-2.28.0: a row of the implementation matrix

The probe ran R0 to R10 against this stock server on loopback, behind the facilitator double. Nothing left the
machine, nothing was paid, and no third party was contacted.

- Stack: Hono 4.13.13 with the stock `@x402/hono` 2.28.0 middleware (`@x402/core`, `@x402/svm`, `@x402/evm` 2.28.0), `ts/example/hono-server.ts`
- Network: Solana devnet (`solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1`), the example's default
- Probe: x402-conformance x402-conformance-svm 1.4.0 (`cli-ts`), run on 2026-10-23
- Command: `node ts/dist/src/cli.js probe --resource http://127.0.0.1:47502/paid --port 0 --start "PORT=47502 node ts/dist/example/hono-server.js" --out evidence/impl-matrix/hono-2.28.0/run.json`
- Result: 11 checks, 0 failed

`run.json` is the document the probe wrote, unchanged. Check the files with `shasum -a 256 -c SHA256SUMS` from this
directory. `.github/workflows/impl-matrix.yml` rebuilds this row the same way.
