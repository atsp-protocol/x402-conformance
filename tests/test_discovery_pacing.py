"""P9 (bazaar info against its own schema), P10 (/.well-known/x402 against the live 402) and the live-request pacing."""

import base64
import contextlib
import copy
import io
import json
import unittest
import urllib.error

from x402conf import cli as C
from x402conf import discovery as D
from x402conf import harness as H
from x402conf import pacing as PG

OFFER = {"scheme": "exact", "network": "eip155:84532", "amount": "25000",
         "asset": "0x036CbD53842c5426634e7929541eC2318f3dCF7e", "payTo": "0x8E2d8e2850Baf623A8A886DE7c80CDfB83a5cfa3",
         "maxTimeoutSeconds": 60, "extra": {"name": "USDC", "version": "2"}}
SCHEMA = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "required": ["input"],
          "properties": {"input": {"type": "object", "additionalProperties": False, "required": ["type", "method"],
                                   "properties": {"type": {"type": "string", "const": "http"},
                                                  "method": {"type": "string", "enum": ["GET"]},
                                                  "queryParams": {"type": "object", "properties": {
                                                      "q": {"type": "string"}, "limit": {"type": "integer"},
                                                      "offset": {"type": "integer"}}}}}}}


def pr_with(info, schema=None):
    return {"x402Version": 2, "resource": {"url": "https://shop.example/api/sources?q=spinach"}, "accepts": [OFFER],
            "extensions": {"bazaar": {"info": info, "schema": copy.deepcopy(schema or SCHEMA)}}}


def resp(pr):
    return {"status": 402, "headers": {"payment-required": base64.b64encode(json.dumps(pr).encode()).decode()},
            "body": b"null", "ms": 1}


def p(results, cid):
    return [r for r in results if r["check"].split()[0] == cid]


class Discovery(unittest.TestCase):
    def test_p9_example_matches_schema(self):
        out = p(H.check_402(resp(pr_with({"input": {"type": "http", "method": "GET",
                                                     "queryParams": {"q": "spinach", "limit": 3}}}))), "P9")
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]["pass"], out[0]["detail"])

    def test_p9_example_type_mismatch(self):
        # the shape seen live: limit sent as the string "3" while the schema types it integer
        out = p(H.check_402(resp(pr_with({"input": {"type": "http", "method": "GET",
                                                     "queryParams": {"q": "spinach", "limit": "3"}}}))), "P9")
        self.assertFalse(out[0]["pass"])
        self.assertIn("/input/queryParams/limit", " ".join(out[0]["detail"]["problems"]))
        self.assertIn("integer", " ".join(out[0]["detail"]["problems"]))

    def test_p9_external_ref_and_missing_required(self):
        schema = copy.deepcopy(SCHEMA)
        schema["properties"]["input"]["properties"]["queryParams"] = {"$ref": "https://evil.example/s.json"}
        out = p(H.check_402(resp(pr_with({"input": {"type": "http"}}, schema))), "P9")
        probs = " ".join(out[0]["detail"]["problems"])
        self.assertFalse(out[0]["pass"])
        self.assertIn("same-document", probs)
        self.assertIn("'method' is missing", probs)

    def test_p9_absent_without_bazaar(self):
        pr = pr_with({})
        del pr["extensions"]
        self.assertEqual(p(H.check_402(resp(pr)), "P9"), [])

    def test_p9_validator_keywords(self):
        v = D.Validator({"$defs": {"n": {"type": "number", "minimum": 1}}, "type": "array", "items": {"$ref": "#/$defs/n"},
                         "minItems": 1, "x-vendor": True})
        self.assertEqual(v.validate([1, 2.5]), [])
        self.assertTrue(v.validate([0]))
        self.assertTrue(v.validate([]))
        self.assertTrue(v.validate([True]))
        self.assertEqual(v.not_graded, {"x-vendor"})
        self.assertEqual(D.Validator({"type": "integer"}).validate(3.0), [])
        self.assertTrue(D.Validator({"anyOf": [{"type": "string"}, {"type": "null"}]}).validate(1))
        self.assertTrue(D.Validator({"oneOf": [{"type": "number"}, {"type": "integer"}]}).validate(1))

    MANIFEST = {"x402Version": 2, "resources": ["https://shop.example/api/sources", "https://shop.example/mcp"],
                "accepts": {"scheme": "exact", "network": "eip155:84532",
                            "asset": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
                            "payTo": "0x8E2d8e2850Baf623A8A886DE7c80CDfB83a5cfa3", "price": "0.025"}}

    def wk(self, doc, status=200):
        return {"url": "https://shop.example/.well-known/x402", "status": status, "doc": doc}

    def test_p10_manifest_matches_live_offer(self):
        out = D.check_well_known(self.wk(self.MANIFEST), "https://shop.example/api/sources?q=spinach&limit=1", [OFFER])
        self.assertTrue(out[0]["pass"], out[0]["detail"])
        self.assertEqual(out[0]["severity"], "warning")

    def test_p10_unlisted_offsite_and_stale_terms(self):
        doc = copy.deepcopy(self.MANIFEST)
        doc["resources"] = ["https://other.example/api/sources", "http://shop.example/mcp"]
        doc["accepts"]["payTo"] = "0x0000000000000000000000000000000000000001"
        out = D.check_well_known(self.wk(doc), "https://shop.example/api/sources", [OFFER])
        probs = " ".join(out[0]["detail"]["problems"])
        self.assertFalse(out[0]["pass"])
        for want in ("other.example", "http://shop.example/mcp", "not listed", "match no live offer"):
            self.assertIn(want, probs)

    def test_p10_atomic_amount_mismatch(self):
        doc = {"resources": [{"url": "https://shop.example/api/sources", "accepts": [dict(OFFER, amount="1")]}]}
        out = D.check_well_known(self.wk(doc), "https://shop.example/api/sources", [OFFER])
        self.assertIn("differs from the live amount", " ".join(out[0]["detail"]["problems"]))

    def test_p10_no_manifest_is_not_graded(self):
        self.assertEqual(D.check_well_known(self.wk(None, 404), "https://shop.example/x", [OFFER]), [])
        self.assertFalse(D.check_well_known(self.wk("[]"), "https://shop.example/x", [OFFER])[0]["pass"])

    def test_resource_well_known_fetches_each_origin_once(self):
        seen = []
        manifest = json.dumps(self.MANIFEST).encode()
        pr = resp(pr_with({"input": {"type": "http", "method": "GET"}}))["headers"]["payment-required"]

        class Ok(io.BytesIO):
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def opener(req, timeout):
            seen.append((req.get_method(), req.full_url))
            if req.full_url.endswith("/.well-known/x402"):
                return Ok(manifest)
            raise urllib.error.HTTPError(req.full_url, 402, "Payment Required", {"payment-required": pr},  # type: ignore[arg-type]
                                         io.BytesIO(b"null"))
        cache: dict = {}
        a = H.run_resource("https://shop.example/api/sources", opener=opener, well_known=True, manifests=cache)
        b = H.run_resource("https://shop.example/api/sources?q=x", opener=opener, well_known=True, manifests=cache)
        self.assertEqual([m for m, _ in seen], ["GET"] * 3)
        self.assertEqual(sum(1 for _, u in seen if u.endswith("/.well-known/x402")), 1)
        self.assertTrue(p(a["checks"], "P10")[0]["pass"])
        self.assertTrue(p(b["checks"], "P10")[0]["pass"])


class Pacing(unittest.TestCase):
    def clock(self):
        t = [100.0]
        slept = []

        def sleep(s):
            slept.append(s)
            t[0] += s
        return t, slept, (lambda: t[0]), sleep

    def test_min_interval_between_live_requests(self):
        t, slept, now, sleep = self.clock()
        log = io.StringIO()
        pc = PG.Pacer(5, None, log=log, clock=now, sleep=sleep, wall=lambda: 0)
        pc.before("GET", "https://a.example/x")
        t[0] += 1.5
        pc.before("GET", "https://a.example/y")
        pc.before("HEAD", "https://a.example/y")
        self.assertEqual([round(s, 3) for s in slept], [3.5, 5.0])
        self.assertEqual(len(log.getvalue().splitlines()), 3)
        self.assertIn("request 2 at 1970-01-01T00:00:00Z: GET https://a.example/y, after waiting 3.5 s", log.getvalue())
        self.assertEqual(pc.summary()["sent"], 3)

    def test_loopback_is_logged_but_not_spaced(self):
        _, slept, now, sleep = self.clock()
        pc = PG.Pacer(5, None, log=io.StringIO(), clock=now, sleep=sleep)
        for _ in range(3):
            pc.before("GET", "http://127.0.0.1:4020/paid")
        pc.before("GET", "http://localhost/paid")
        self.assertEqual(slept, [])
        self.assertEqual(len(pc.requests), 4)

    def test_max_requests_stops_before_sending(self):
        _, _, now, sleep = self.clock()
        sent = []
        pc = PG.Pacer(0, 2, log=io.StringIO(), clock=now, sleep=sleep)

        def opener(req, timeout):
            sent.append(req.full_url)
            raise urllib.error.HTTPError(req.full_url, 402, "Payment Required", {}, io.BytesIO(b"{}"))  # type: ignore[arg-type]
        runs = [H.run_resource(f"https://a.example/{i}", opener=pc.wrap(opener)) for i in range(3)]
        self.assertEqual(len(sent), 2)
        self.assertEqual(runs[2]["checks"], [])
        self.assertIn("--max-requests 2 reached", runs[2]["skipped"])

    def test_cli_flags_and_log(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = C.main(["resource", "http://127.0.0.1:9/paid", "--min-interval", "7", "--max-requests", "1"])
        self.assertEqual(code, 0)
        doc = json.loads(out.getvalue())
        self.assertEqual((doc["pacing"]["min_interval_s"], doc["pacing"]["max_requests"], doc["pacing"]["sent"]),
                         (7.0, 1, 1))
        self.assertIn("x402conf: request 1 of at most 1", err.getvalue())
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(C.main(["resource", "http://127.0.0.1:9/paid", "--max-requests", "0"]), 2)
            self.assertEqual(C.main(["live", "http://127.0.0.1:9", "--min-interval", "-1"]), 2)


class NotApplicable(unittest.TestCase):
    """C2 and C3 graded not_applicable (a client that never signs, by design) reach every report format as non-failures."""

    def test_report_sarif_junit_badge_treat_na_as_not_failed(self):
        import os
        import tempfile
        d = tempfile.mkdtemp()
        res = {"resource": "client fixture", "results": [
            {"check": "C1 client never treats 402 as success", "pass": True, "status": "pass", "detail": {}},
            {"check": "C2 given several offers ...", "pass": False, "status": "not_applicable",
             "detail": {"reason": "the client is declared not to sign"}},
            {"check": "C3 client keeps V2 ...", "pass": False, "status": "not_applicable", "detail": {}}]}
        with open(os.path.join(d, "resource-server.json"), "w") as f:
            json.dump(res, f)
        rows = C.collect(d)
        self.assertEqual(C.sarif(rows, d)["runs"][0]["results"], [])
        j = C.junit(rows)
        self.assertIn('failures="0"', j)
        self.assertIn("C2 not applicable to this implementation", j)
        self.assertEqual(C.badge(rows)["message"], "pass 1/1")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(C.main(["report", "--dir", d, "--fail-on-error"]), 0)
        self.assertEqual(json.loads(out.getvalue())["not_applicable"], ["C2", "C3"])
        rep = C.make_report("resource-server", "x", res["results"])
        self.assertEqual((rep["summary"]["failed"], rep["summary"]["not_applicable"]), (0, ["C2", "C3"]))


if __name__ == "__main__":
    unittest.main()
