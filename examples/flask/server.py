"""The smallest paid route on Flask: the x402 Python SDK's Flask payment middleware with its defaults, one GET /paid
at $0.001. X402_FACILITATOR_URL names the facilitator (the probe sets it), PORT the port, EXAMPLE_NETWORK the
network (Solana devnet by default, or eip155:84532 for Base Sepolia). Run: python server.py"""

from __future__ import annotations

import os

from flask import Flask, jsonify
from x402 import x402ResourceServerSync
from x402.http import HTTPFacilitatorClientSync
from x402.http.middleware.flask import payment_middleware
from x402.mechanisms.evm.exact.server import ExactEvmScheme
from x402.mechanisms.svm.exact.server import ExactSvmScheme

network = os.environ.get("EXAMPLE_NETWORK", "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1")
evm = network.startswith("eip155:")
pay_to = "0x209693Bc6afc0C5328bA36FaF03C514EF312287C" if evm else "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin"

server = x402ResourceServerSync(HTTPFacilitatorClientSync({"url": os.environ["X402_FACILITATOR_URL"]}))
server.register(network, ExactEvmScheme() if evm else ExactSvmScheme())
routes = {"GET /paid": {"accepts": {"scheme": "exact", "payTo": pay_to, "price": "$0.001", "network": network},
                        "description": "quickstart", "mimeType": "application/json"}}
app = Flask(__name__)
payment_middleware(app, routes, server)


@app.get("/paid")
def paid():  # type: ignore[no-untyped-def]
    return jsonify(content="paid content")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "4031")), threaded=True)
