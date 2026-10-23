"""The smallest paid route on FastAPI: the x402 Python SDK's payment middleware with its defaults, one GET /paid at
$0.001. X402_FACILITATOR_URL names the facilitator (the probe sets it), PORT the port, EXAMPLE_NETWORK the network
(Solana devnet by default, or eip155:84532 for Base Sepolia). Run: python server.py"""

from __future__ import annotations

import os

import uvicorn
from fastapi import FastAPI
from x402 import x402ResourceServer
from x402.http import HTTPFacilitatorClient
from x402.http.middleware.fastapi import payment_middleware
from x402.mechanisms.evm.exact.server import ExactEvmScheme
from x402.mechanisms.svm.exact.server import ExactSvmScheme

network = os.environ.get("EXAMPLE_NETWORK", "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1")
evm = network.startswith("eip155:")
pay_to = "0x209693Bc6afc0C5328bA36FaF03C514EF312287C" if evm else "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin"

server = x402ResourceServer(HTTPFacilitatorClient({"url": os.environ["X402_FACILITATOR_URL"]}))
server.register(network, ExactEvmScheme() if evm else ExactSvmScheme())
routes = {"GET /paid": {"accepts": {"scheme": "exact", "payTo": pay_to, "price": "$0.001", "network": network},
                        "description": "quickstart", "mimeType": "application/json"}}
app = FastAPI()
mw = payment_middleware(routes, server)


@app.middleware("http")
async def x402_middleware(request, call_next):  # type: ignore[no-untyped-def]
    return await mw(request, call_next)


@app.get("/paid")
async def paid() -> dict[str, str]:
    return {"content": "paid content"}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "4030")), log_level="warning")
