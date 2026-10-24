# express-2.27.0: a row of the implementation matrix

The probe ran R0 to R10 against this stock server on loopback, behind the facilitator double. Nothing left the
machine, nothing was paid, and no third party was contacted.

- Stack: the same stock Express example compiled from `ts/example/express-server.ts`, run from a separate project whose packages are `@x402/express`, `@x402/core`, `@x402/svm` and `@x402/evm` pinned at 2.27.0 with Express 4.22.3
- Network: Solana devnet (`solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1`), the example's default
- Probe: x402-conformance x402-conformance-svm 1.5.0 (`cli-ts`), run on 2026-10-24
- Command: `node ts/dist/src/cli.js probe --resource http://127.0.0.1:47505/paid --port 0 --start "cd <project with the 2.27.0 packages> && PORT=47505 node express-server.mjs" --out evidence/impl-matrix/express-2.27.0/run.json`
- Result: 11 checks, 0 failed

`run.json` is the document the probe wrote, unchanged. Check the files with `shasum -a 256 -c SHA256SUMS` from this
directory. `.github/workflows/impl-matrix.yml` rebuilds this row the same way.
