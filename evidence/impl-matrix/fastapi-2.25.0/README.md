# fastapi-2.25.0: a row of the implementation matrix

The probe ran R0 to R10 against this stock server on loopback, behind the facilitator double. Nothing left the
machine, nothing was paid, and no third party was contacted.

- Stack: FastAPI with the stock `x402` 2.25.0 Python SDK's FastAPI payment middleware (`x402[fastapi,evm,svm]==2.25.0`, uvicorn 0.38.0, Python 3.12), `examples/python/fastapi_server.py`
- Network: Solana devnet (`solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1`), the example's default
- Probe: x402-conformance x402-conformance-svm 1.4.0 (`cli-ts`), run on 2026-10-23
- Command: `node ts/dist/src/cli.js probe --resource http://127.0.0.1:47503/paid --port 0 --start "PORT=47503 python examples/python/fastapi_server.py" --out evidence/impl-matrix/fastapi-2.25.0/run.json`
- Result: 11 checks, 0 failed

`run.json` is the document the probe wrote, unchanged. Check the files with `shasum -a 256 -c SHA256SUMS` from this
directory. `.github/workflows/impl-matrix.yml` rebuilds this row the same way.
