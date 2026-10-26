"""Parity runner: the shared vector set against each SDK's harness, offline.

    x402conf parity --sdk ts,python,go --upstream-pin COMMIT --offline --out FILE [--fault MODE]

Run from a checkout of this repository. COMMIT must equal docs/parity/pin. For each SDK the runner prepares the
harness once (npm ci and tsc in ts/parity-harness, a virtualenv with the pinned x402 package, go build in
examples/go/parity), then starts it and sends it JSON lines: one config line, then one line per vector from
docs/parity/vectors.json. The harness answers one line per vector, {vector, status, content_type, isValid,
invalidReason, threw, error}, and a last line with the library version it loaded, the connections it was asked to
open to anything but loopback, and the reads and writes its stub signer was asked for.

No chain, key or RPC. The facilitator a paid-route vector needs is a recording double on 127.0.0.1 started here;
each harness refuses and counts any connection to another address. Its signer is a stub: getCode answers "0x" (no
code, so a signature is recovered locally), other reads fail, and every write (a transaction) is refused and counted.
Preparing a harness downloads the pinned packages; running the vectors does not use the network.

--fault MODE makes every harness substitute the library's decision on one path (status: a paid route answers 500
instead of its 4xx; swallow-reason: verify returns no invalidReason; wildcard-network: verify accepts a network of
the registered family that was never registered). The report must then show a divergence on the vectors that path
covers. The run file records the mode."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
import venv
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

SDKS = ("ts", "python", "go")
FAULTS = ("status", "swallow-reason", "wildcard-network")
NETWORK = "eip155:84532"
PAY_TO = "0x209693Bc6afc0C5328bA36FaF03C514EF312287C"
ASSET = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"  # USDC on Base Sepolia
FIELDS = ("status", "content_type", "isValid", "invalidReason", "threw", "error")


class Recorder:
    """A facilitator double on loopback that records every request and never approves anything."""

    def __init__(self) -> None:
        self.calls: dict[str, int] = {}
        lock = threading.Lock()
        rec = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *_: Any) -> None:
                pass

            def _send(self, code: int, body: dict[str, Any]) -> None:
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _count(self) -> str:
                path = self.path.split("?")[0].rstrip("/") or "/"
                with lock:
                    rec.calls[path] = rec.calls.get(path, 0) + 1
                return path

            def do_GET(self) -> None:
                if self._count().endswith("/supported"):
                    self._send(200, {"kinds": [{"x402Version": 2, "scheme": "exact", "network": NETWORK}],
                                     "extensions": [], "signers": {"eip155:*": [PAY_TO]}})
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self) -> None:
                n = int(self.headers.get("content-length") or 0)
                self.rfile.read(n)
                path = self._count()
                if path.endswith("/verify"):
                    self._send(200, {"isValid": False, "invalidReason": "invalid_payload"})
                elif path.endswith("/settle"):
                    self._send(200, {"success": False, "errorReason": "invalid_payload", "transaction": "",
                                     "network": NETWORK})
                else:
                    self._send(404, {"error": "not found"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def _run(cmd: list[str], cwd: str, env: dict[str, str] | None = None) -> None:
    p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f"{' '.join(cmd)} (in {cwd}) exited {p.returncode}: {(p.stdout + p.stderr)[-600:]}")


def prepare(sdk: str, root: str, cache: str, pins: dict[str, Any]) -> list[str]:
    """Install the pinned library for one SDK and return the command that starts its harness."""
    if sdk == "ts":
        d = os.path.join(root, "ts", "parity-harness")
        _run(["npm", "ci", "--silent", "--no-audit", "--no-fund"], d)
        _run(["npx", "tsc", "-p", "."], d)
        return ["node", "--import", os.path.join(d, "dist", "src", "guard.js"), os.path.join(d, "dist", "src", "harness.js")]
    if sdk == "python":
        want = pins["sdks"]["python"]
        env_dir = os.path.join(cache, f"python-{want['package']}-{want['version']}")
        py = os.path.join(env_dir, "bin", "python")
        if not os.path.exists(py):
            venv.EnvBuilder(with_pip=True, clear=True).create(env_dir)
            _run([py, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                  f"{want['package']}[{','.join(want.get('extras', []))}]=={want['version']}"
                  if want.get("extras") else f"{want['package']}=={want['version']}"], root)
        return [py, "-I", os.path.join(root, "examples", "python", "parity_harness.py")]
    if sdk == "go":
        d = os.path.join(root, "examples", "go", "parity")
        out = os.path.join(cache, "parity-go")
        _run(["go", "build", "-o", out, "."], d, env=dict(os.environ, GOFLAGS="-mod=readonly"))
        return [out]
    raise ValueError(f"unknown SDK {sdk}")


def drive(cmd: list[str], config: dict[str, Any], vectors: list[dict[str, Any]], sdk: str,
          timeout: int = 600) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Send the config and the vectors, read one outcome per vector and the closing summary."""
    lines = [json.dumps({"config": config})] + [json.dumps({"vector": v}) for v in vectors]
    p = subprocess.run(cmd, input="\n".join(lines) + "\n", capture_output=True, text=True, timeout=timeout)
    results: list[dict[str, Any]] = []
    summary: dict[str, Any] | None = None
    for line in p.stdout.splitlines():
        if not line.startswith("{"):
            continue
        msg = json.loads(line)
        if "done" in msg:
            summary = msg
        elif "vector" in msg:
            results.append({"vector": msg["vector"], "sdk": sdk, **{k: msg.get(k) for k in FIELDS}})
    if p.returncode or summary is None:
        raise RuntimeError(f"{sdk} harness exited {p.returncode} without a summary: {p.stderr[-800:]}")
    return results, summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="x402conf parity")
    ap.add_argument("--sdk", default=",".join(SDKS), help="comma-separated: " + ",".join(SDKS))
    ap.add_argument("--upstream-pin", required=True, metavar="COMMIT", help="must equal docs/parity/pin")
    ap.add_argument("--offline", action="store_true", help="required: the vectors run without network")
    ap.add_argument("--out", required=True, help="write the run file here")
    ap.add_argument("--fault", choices=FAULTS, help="substitute the library's decision on one path (self-test)")
    ap.add_argument("--probe-outbound", action="store_true",
                    help="self-test: each harness tries one connection to 192.0.2.1:80, which its guard must refuse and count")
    ap.add_argument("--root", default=os.getcwd(), help="checkout of this repository (default: the current directory)")
    ap.add_argument("--cache", default=os.path.join(os.path.expanduser("~"), ".cache", "x402conf-parity"))
    a = ap.parse_args(argv)
    if not a.offline:
        ap.error("parity runs offline only; pass --offline")
    sdks = [s for s in a.sdk.split(",") if s]
    if not sdks or set(sdks) - set(SDKS):
        ap.error(f"--sdk takes {','.join(SDKS)}")
    try:
        with open(os.path.join(a.root, "docs", "parity", "pin"), encoding="utf-8") as f:
            pin = f.read().strip()
        with open(os.path.join(a.root, "docs", "parity", "pins.json"), encoding="utf-8") as f:
            pins: dict[str, Any] = json.load(f)
        with open(os.path.join(a.root, "docs", "parity", "vectors.json"), "rb") as fb:
            raw = fb.read()
    except OSError as e:
        print(f"x402conf parity: run from a checkout of x402-conformance ({e})", file=sys.stderr)
        return 2
    if a.upstream_pin != pin or pins.get("commit") != pin:
        print(f"x402conf parity: --upstream-pin {a.upstream_pin} is not docs/parity/pin {pin}", file=sys.stderr)
        return 2
    vectors: list[dict[str, Any]] = json.loads(raw)["vectors"]
    os.makedirs(a.cache, exist_ok=True)
    rec = Recorder()
    config = {"network": NETWORK, "payTo": PAY_TO, "asset": ASSET, "facilitator_url": rec.url, "fault": a.fault,
              "probe_outbound": a.probe_outbound}
    run: dict[str, Any] = {"schema": "x402conf.parity-run/1", "pin": pin, "offline": True, "fault": a.fault,
                           "vectors_sha256": hashlib.sha256(raw).hexdigest(), "sdks": {}, "results": []}
    outbound = reads = writes = 0
    try:
        for sdk in sdks:
            cmd = prepare(sdk, a.root, a.cache, pins)
            results, summary = drive(cmd, config, vectors, sdk)
            run["results"] += results
            run["sdks"][sdk] = {"package": pins["sdks"][sdk]["package"], "version": summary.get("version"),
                                **{k: summary.get(k) for k in ("outbound_attempts", "signer_reads", "signer_writes")}}
            outbound += int(summary.get("outbound_attempts", -1))
            reads += int(summary.get("signer_reads", -1))
            writes += int(summary.get("signer_writes", -1))
    except (RuntimeError, subprocess.TimeoutExpired, ValueError) as e:
        print(f"x402conf parity: {e}", file=sys.stderr)
        return 1
    finally:
        rec.close()
    run["network"] = {"outbound_connections": outbound, "signer_writes": writes, "signer_reads": reads,
                      "facilitator_double_calls": dict(sorted(rec.calls.items()))}
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(json.dumps(run, indent=1, sort_keys=True) + "\n")
    print(f"x402conf parity: {len(run['results'])} results from {', '.join(sdks)} written to {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
