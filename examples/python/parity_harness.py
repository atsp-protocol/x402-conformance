"""XC-56 parity harness for the official Python library (x402 at the pin, with the evm, flask and httpx extras).

Reads JSON lines on stdin: one {config}, then one {vector} per line. Writes one outcome line per vector and a last
{done} line. Started by x402conf parity inside a virtualenv that holds only the pinned package.

  verify      x402FacilitatorSync.verify on parse_payment_payload(the payload's JSON bytes) and the requirements
              model, with the exact EVM scheme registered for the config's network and a stub signer: get_code answers
              b"" (an account with no code, so signatures are recovered locally), every other read raises, and every
              write is refused and counted.
  paid-route  GET /paid on a Flask app behind the stock payment_middleware, served on loopback, whose facilitator is
              the runner's recording double, with the vector's PAYMENT-SIGNATURE header.

Before anything is imported, socket connections and name lookups for anything but loopback are refused and counted.
Faults (self-test only) substitute the library's decision at this boundary, except wildcard-network, which
registers two networks of the family.
"""

from __future__ import annotations

import socket

LOOPBACK = {"127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"}
OUTBOUND = [0]
_connect, _connect_ex, _getaddrinfo = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo


def _host(address: object) -> str | None:
    return str(address[0]) if isinstance(address, tuple) and address else None


def _guarded_connect(self: socket.socket, address: object) -> None:
    host = _host(address)
    if host is not None and host not in LOOPBACK:
        OUTBOUND[0] += 1
        raise ConnectionRefusedError(f"parity guard: refused a connection to {host}")
    _connect(self, address)  # type: ignore[arg-type]


def _guarded_connect_ex(self: socket.socket, address: object) -> int:
    host = _host(address)
    if host is not None and host not in LOOPBACK:
        OUTBOUND[0] += 1
        return 111
    return _connect_ex(self, address)  # type: ignore[arg-type]


def _guarded_getaddrinfo(host: object, *args: object, **kw: object) -> object:
    if host is not None and str(host) not in LOOPBACK:
        OUTBOUND[0] += 1
        raise socket.gaierror(f"parity guard: refused a lookup of {host}")
    return _getaddrinfo(host, *args, **kw)  # type: ignore[arg-type]


socket.socket.connect = _guarded_connect  # type: ignore[method-assign]
socket.socket.connect_ex = _guarded_connect_ex  # type: ignore[method-assign]
socket.getaddrinfo = _guarded_getaddrinfo  # type: ignore[assignment]

import http.client  # noqa: E402
import importlib.metadata  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
from typing import Any  # noqa: E402

CALLS = {"reads": 0, "writes": 0}


class StubSigner:
    """FacilitatorEvmSigner with no chain behind it."""

    def get_addresses(self) -> list[str]:
        CALLS["reads"] += 1
        return ["0x209693Bc6afc0C5328bA36FaF03C514EF312287C"]

    def get_code(self, address: str) -> bytes:
        CALLS["reads"] += 1
        return b""

    def _read(self, *a: Any, **k: Any) -> Any:
        CALLS["reads"] += 1
        raise RuntimeError("parity stub signer: no chain")

    read_contract = verify_typed_data = get_balance = get_chain_id = _read

    def _write(self, *a: Any, **k: Any) -> Any:
        CALLS["writes"] += 1
        raise RuntimeError("parity stub signer: writes are refused")

    write_contract = send_transaction = wait_for_transaction_receipt = _write


def blank() -> dict[str, Any]:
    return {"status": None, "content_type": None, "isValid": None, "invalidReason": None, "threw": False, "error": None}


def facilitator_for(cfg: dict[str, Any]) -> Any:
    from x402 import x402FacilitatorSync
    from x402.mechanisms.evm.exact import ExactEvmFacilitatorScheme

    networks = [cfg["network"], "eip155:84533"] if cfg.get("fault") == "wildcard-network" else [cfg["network"]]
    return x402FacilitatorSync().register(networks, ExactEvmFacilitatorScheme(signer=StubSigner()))


def verify(fac: Any, v: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    from x402 import PaymentRequirements, parse_payment_payload

    out = blank()
    try:
        payload = parse_payment_payload(json.dumps(v["input"]["payload"]).encode())
        req = PaymentRequirements.model_validate(v["input"]["requirements"])
        r = fac.verify(payload, req)
        out["isValid"] = bool(r.is_valid)
        out["invalidReason"] = r.invalid_reason
    except Exception as e:  # noqa: BLE001 - an exception out of the library is the outcome being recorded
        out["threw"] = True
        out["error"] = f"{type(e).__name__}: {e}"[:200]
    if cfg.get("fault") == "swallow-reason" and out["isValid"] is False:
        out["invalidReason"] = None
    return out


def start_route(cfg: dict[str, Any]) -> tuple[str, Any]:
    from flask import Flask, jsonify
    from werkzeug.serving import make_server
    from x402.http import FacilitatorConfig, HTTPFacilitatorClientSync, PaymentOption
    from x402.http.middleware.flask import payment_middleware
    from x402.http.types import RouteConfig
    from x402.mechanisms.evm.exact import ExactEvmServerScheme
    from x402.server import x402ResourceServerSync

    app = Flask("parity")
    server = x402ResourceServerSync(HTTPFacilitatorClientSync(FacilitatorConfig(url=cfg["facilitator_url"])))
    server.register(cfg["network"], ExactEvmServerScheme())
    routes = {"GET /paid": RouteConfig(accepts=[PaymentOption(scheme="exact", pay_to=cfg["payTo"], price="$0.001",
                                                               network=cfg["network"])],
                                       mime_type="application/json", description="parity")}
    payment_middleware(app, routes=routes, server=server)

    @app.get("/paid")
    def paid() -> Any:
        return jsonify(content="paid content")

    srv = make_server("127.0.0.1", 0, app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"127.0.0.1:{srv.server_port}", srv


def paid_route(hostport: str, v: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    out = blank()
    try:
        c = http.client.HTTPConnection(hostport, timeout=15)
        c.request("GET", "/paid", headers={"PAYMENT-SIGNATURE": str(v["input"]["header"])})
        r = c.getresponse()
        r.read()
        out["status"] = r.status
        types = r.headers.get_all("Content-Type") or []
        out["content_type"] = ", ".join(types) if types else None
        c.close()
    except Exception as e:  # noqa: BLE001
        out["error"] = f"no answer: {type(e).__name__}: {e}"[:200]
    if cfg.get("fault") == "status" and isinstance(out["status"], int) and 400 <= out["status"] < 500:
        out["status"] = 500
    return out


def main() -> int:
    cfg: dict[str, Any] | None = None
    vectors: list[dict[str, Any]] = []
    for line in sys.stdin:
        if not line.strip():
            continue
        msg = json.loads(line)
        cfg = msg.get("config", cfg)
        if "vector" in msg:
            vectors.append(msg["vector"])
    if cfg is None:
        raise SystemExit("no config line")
    if cfg.get("probe_outbound"):
        try:
            socket.create_connection(("192.0.2.1", 80), timeout=1)  # TEST-NET-1
        except OSError:
            pass
    fac = facilitator_for(cfg)
    route = start_route(cfg) if any(v["target"] == "paid-route" for v in vectors) else None
    for v in vectors:
        out = verify(fac, v, cfg) if v["target"] == "verify" else paid_route(route[0], v, cfg)  # type: ignore[index]
        print(json.dumps({"vector": v["id"], **out}), flush=True)
    if route:
        route[1].shutdown()
    print(json.dumps({"done": True, "sdk": "python", "version": importlib.metadata.version("x402"),
                      "outbound_attempts": OUTBOUND[0], "signer_reads": CALLS["reads"],
                      "signer_writes": CALLS["writes"]}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
