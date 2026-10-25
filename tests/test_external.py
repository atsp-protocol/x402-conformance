"""XC-110: R16a and R24 from outside the stack, the external modes the tier-1 queue runs (src/x402conf/external.py).

A paid route on loopback stands in for a project's testnet endpoint: the control passes, each broken build is caught,
nothing is paid or signed, and off loopback the HEAD is sent only with the operator's permission."""
from __future__ import annotations

import base64
import contextlib
import io
import json
import os
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from x402conf import cli as C
from x402conf import external as X
from x402conf import harness as H
from x402conf import tiers as T

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OFFER = {"x402Version": 2, "resource": {"url": "http://127.0.0.1/paid"},
         "accepts": [{"scheme": "exact", "network": "eip155:84532", "amount": "10000",
                      "asset": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
                      "payTo": "0x000000000000000000000000000000000000dEaD", "maxTimeoutSeconds": 300,
                      "extra": {"name": "USDC", "version": "2"}}]}
PR = base64.b64encode(json.dumps(OFFER).encode()).decode()


def serve(fault: str = "") -> tuple[ThreadingHTTPServer, list[tuple[str, str]]]:
    """A paid route. Faults: head_bypass (HEAD reaches the handler), head_405 (HEAD refused, a pass), head_402_bare
    (402 without an offer), decode_unchecked (500 on a malformed header), drop (connection dropped), unstructured
    (400 with a plain-text body)."""
    seen: list[tuple[str, str]] = []

    class Paid(BaseHTTPRequestHandler):
        def log_message(self, *a: Any) -> None:
            pass

        def _402(self, offer: bool = True, body: bool = True) -> None:
            self.send_response(402)
            if offer:
                self.send_header("PAYMENT-REQUIRED", PR)
            self.send_header("content-type", "application/json")
            data = b'{"error":"payment required"}' if body else b""
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def do_HEAD(self) -> None:
            seen.append(("HEAD", self.headers.get("PAYMENT-SIGNATURE") or ""))
            if fault == "head_bypass":
                self.send_response(200)
                self.send_header("content-length", "7")
                self.end_headers()
            elif fault == "head_405":
                self.send_response(405)
                self.send_header("allow", "GET")
                self.send_header("content-length", "0")
                self.end_headers()
            else:
                self._402(offer=fault != "head_402_bare")

        def do_GET(self) -> None:
            sig = self.headers.get("PAYMENT-SIGNATURE")
            seen.append(("GET", sig or ""))
            if sig is None:
                return self._402()
            if fault == "decode_unchecked":
                self.send_response(500)
                self.send_header("content-length", "5")
                self.end_headers()
                self.wfile.write(b"boom!")
            elif fault == "drop":
                self.close_connection = True
                self.connection.shutdown(2)
            elif fault == "unstructured":
                self.send_response(400)
                self.send_header("content-type", "text/plain")
                self.send_header("content-length", "3")
                self.end_headers()
                self.wfile.write(b"bad")
            else:
                self._402()

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Paid)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, seen


def run(fault: str = "", **kw: Any) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    srv, seen = serve(fault)
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/paid"
        return H.run_resource(url, **kw), seen
    finally:
        srv.shutdown()


def check(out: dict[str, Any], cid: str) -> dict[str, Any]:
    return next(c for c in out["checks"] if c["check"].split()[0] == cid)


class External(unittest.TestCase):
    def test_control_passes_r16a_and_r24_with_unpaid_requests_only(self) -> None:
        out, seen = run(unpaid_head=True, malformed_header=True)
        self.assertTrue(check(out, "R16a")["pass"], check(out, "R16a"))
        self.assertTrue(check(out, "R24")["pass"], check(out, "R24"))
        self.assertEqual(len(check(out, "R24")["detail"]["cases"]), len(X.MALFORMED_HEADERS))
        # one shared unpaid GET, one HEAD, five malformed GETs; nothing carries a real payment
        self.assertEqual([m for m, _ in seen], ["GET", "HEAD"] + ["GET"] * 5)
        self.assertEqual({s for _, s in seen[2:]}, set(X.MALFORMED_HEADERS.values()))
        self.assertEqual(len(seen), 1 + sum(X.REQUESTS.values()))

    def test_r16a_passes_a_405_and_catches_a_head_that_reaches_the_handler(self) -> None:
        self.assertTrue(check(run("head_405", unpaid_head=True)[0], "R16a")["pass"])
        for fault in ("head_bypass", "head_402_bare"):
            r = check(run(fault, unpaid_head=True)[0], "R16a")
            self.assertFalse(r["pass"], fault)
            self.assertIn("error", r["detail"])

    def test_r24_catches_a_5xx_a_dropped_connection_and_an_unstructured_400(self) -> None:
        for fault, words in (("decode_unchecked", "got 500"), ("drop", "no answer"), ("unstructured", "without a structured")):
            r = check(run(fault, malformed_header=True)[0], "R24")
            self.assertFalse(r["pass"], fault)
            self.assertIn(words, r["detail"]["error"], fault)

    def test_off_loopback_the_head_needs_the_operators_permission(self) -> None:
        sent: list[str] = []

        def opener(req: Any, *a: Any, **kw: Any) -> Any:
            sent.append(req.get_method())
            hdrs = {"PAYMENT-REQUIRED": PR, "content-type": "application/json"}
            import email.message
            m = email.message.Message()
            for k, v in hdrs.items():
                m[k] = v
            raise urllib.error.HTTPError(req.full_url, 402, "Payment Required", m, io.BytesIO(b'{"error":"x"}'))

        url = "https://testnet.example.com/paid"
        out = H.run_resource(url, opener=opener, unpaid_head=True, malformed_header=True)
        self.assertNotIn("HEAD", sent)
        self.assertIn("--operator-permission", out["skipped"])
        self.assertFalse(any(c["check"].startswith("R16a") for c in out["checks"]))
        self.assertTrue(check(out, "R24")["pass"])
        sent.clear()
        ref = "https://github.com/atsp-protocol/x402-conformance/issues/1"
        out = H.run_resource(url, opener=opener, unpaid_head=True, operator_permission=ref)
        self.assertEqual(sent, ["GET", "HEAD"])
        self.assertTrue(check(out, "R16a")["pass"])
        self.assertEqual(out["operator_permission"], ref)
        self.assertTrue(X.head_needs_permission(url, None) and not X.head_needs_permission(url, ref)
                        and not X.head_needs_permission("http://127.0.0.1:1/paid", None))

    def test_the_cli_stays_inside_max_requests_and_reports_the_rest_skipped(self) -> None:
        srv, seen = serve()
        try:
            url = f"http://127.0.0.1:{srv.server_address[1]}/paid"
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                code = C.main(["resource", url, "--malformed-header", "--unpaid-head", "--max-requests", "3"])
        finally:
            srv.shutdown()
        doc = json.loads(buf.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(doc["mode"], "resource-unpaid")
        self.assertEqual(doc["pacing"]["sent"], 3)
        self.assertEqual(len(seen), 3)
        self.assertIn("--max-requests 3 reached", doc["results"][0]["skipped"])

    def test_tier_1_has_eleven_external_checks_within_eight_requests(self) -> None:
        self.assertEqual(len(T.EXTERNAL), 11)
        self.assertTrue({"R16a", "R24"} <= T.EXTERNAL)
        self.assertEqual(2 + sum(X.REQUESTS.values()), T.MAX_EXTERNAL_REQUESTS)
        r = T.tier1_results({})
        self.assertEqual(r["R16a"]["status"], "not_run")
        self.assertIn("did not allow", r["R16a"]["reason"])
        d = T.denominator(r, T.TIER1)
        self.assertEqual(d["needs_self_hosted"], d["catalogue"] - 11 + d["not_run"])

    def test_the_queue_runs_the_external_modes_and_the_head_only_with_permission(self) -> None:
        import yaml
        wf = yaml.safe_load(open(os.path.join(ROOT, ".github", "workflows", "run-queue.yml")))
        run = "\n".join(str(st.get("run", "")) for st in wf["jobs"]["run"]["steps"])
        self.assertIn("--malformed-header", run)
        self.assertIn("--unpaid-head --operator-permission", run)
        self.assertIn('if [ "$HEAD_ALLOWED" = "true" ]', run)
        self.assertIn("--max-requests 8", run)
        self.assertEqual(wf["jobs"]["run"]["permissions"], {"contents": "read"})
        self.assertNotIn("secrets.", yaml.dump(wf["jobs"]["run"]))


if __name__ == "__main__":
    unittest.main()
