"""A stock Flask resource server: the upstream x402 Python SDK's Flask payment middleware with its defaults, as the x402
examples set it up. X402_FACILITATOR_URL names its facilitator, EXAMPLE_NETWORK picks Solana devnet (default) or Base
Sepolia (eip155:84532), PORT its port. Run: python examples/python/flask_server.py"""

from __future__ import annotations

import os

from flask import Flask
from x402 import x402ResourceServerSync
from x402.http import HTTPFacilitatorClientSync
from x402.http.middleware.flask import payment_middleware
from x402.mechanisms.evm.exact.server import ExactEvmScheme
from x402.mechanisms.svm.exact.server import ExactSvmScheme

DEVNET = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"
BASE_SEPOLIA = "eip155:84532"


def create_app(facilitator_url: str, network: str = DEVNET) -> Flask:
    evm = network == BASE_SEPOLIA
    pay_to = "0x209693Bc6afc0C5328bA36FaF03C514EF312287C" if evm else "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin"
    server = x402ResourceServerSync(HTTPFacilitatorClientSync({"url": facilitator_url}))
    server.register(network, ExactEvmScheme() if evm else ExactSvmScheme())
    routes = {"GET /paid": {"accepts": {"scheme": "exact", "payTo": pay_to, "price": "$0.001", "network": network},
                            "description": "stock flask example", "mimeType": "application/json"}}
    app = Flask(__name__)
    payment_middleware(app, routes, server)

    @app.get("/paid")
    def paid() -> dict[str, str]:
        return {"content": "paid content"}

    return app


if __name__ == "__main__":
    app = create_app(os.environ["X402_FACILITATOR_URL"], os.environ.get("EXAMPLE_NETWORK", DEVNET))
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "4031")), debug=False, use_reloader=False)
