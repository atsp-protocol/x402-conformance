# Python examples

`fastapi_server.py` is a stock FastAPI resource server: the upstream x402 Python SDK's payment middleware with its
defaults. It takes its facilitator from `X402_FACILITATOR_URL`, the network from `EXAMPLE_NETWORK` (Solana devnet by
default, or `eip155:84532`) and its port from `PORT`. CI runs the pytest plugin against it.

Mount the same middleware in your own app and hand it the facilitator the suite gives you:

<!-- runnable: python -->
```python
import os

from fastapi_server import create_app

app = create_app(os.environ["X402_FACILITATOR_URL"], os.environ.get("EXAMPLE_NETWORK", "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"))
```

Run it with `python examples/python/fastapi_server.py`, then probe it from the tree root:

<!-- runnable: cli subst="npx -y x402-conformance-svm=node ts/dist/src/cli.js" -->
```
npx -y x402-conformance-svm --help                                   # the probe's flags; exits 0
```
