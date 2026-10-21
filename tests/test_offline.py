"""F1-F9: the reference double passes; each faulty double is caught by the check that targets it."""

import json
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET

from x402conf import cli
from x402conf import harness as H
from x402conf import mock as M
from x402conf import spec as S


def fails(results):
    return {r["check"].split()[0] for r in results if not r["pass"]}


class Offline(unittest.TestCase):
    def test_reference_passes_all(self):
        self.assertEqual(fails(H.check_safety(M.Reference(), M.vectors())), set())

    def test_f1_open_on_malformed_caught(self):
        self.assertIn("F1", fails(H.check_safety(M.Faulty(open_on_malformed=True), M.vectors())))

    def test_f2_accept_dust_caught(self):
        self.assertIn("F2", fails(H.check_safety(M.Faulty(accept_dust=True), M.vectors())))

    def test_f3_no_dup_cache_caught(self):
        self.assertIn("F3", fails(H.check_safety(M.Faulty(no_dup_cache=True), M.vectors())))

    def test_f4_no_memo_check_caught(self):
        self.assertIn("F4", fails(H.check_safety(M.Faulty(no_memo_check=True), M.vectors())))

    def test_f5_success_before_final_caught(self):
        self.assertIn("F5", fails(H.check_safety(M.Faulty(success_before_final=True), M.vectors())))

    def test_f6_guard_fails_closed_and_credits_once(self):
        g = H.ResourceServerGuard(M.Reference())
        v = M.vectors()
        self.assertFalse(g.settle_and_credit(v("good"), v("req"), simulate="timeout"))
        self.assertFalse(g.settle_and_credit(v("good"), v("req"), simulate="garbage"))
        self.assertTrue(g.settle_and_credit(v("good"), v("req")))
        self.assertFalse(g.settle_and_credit(v("good"), v("req")))
        self.assertFalse(g.settle_and_credit(v("unfinalized"), v("req")))

    def test_f7_burn_on_pending_caught(self):
        self.assertIn("F7", fails(H.check_safety(M.Faulty(burn_on_pending=True), M.vectors())))

    def test_f8_stuck_pending_caught(self):
        self.assertIn("F8", fails(H.check_safety(M.Faulty(stuck_pending=True), M.vectors())))

    def test_f9_guard_trusting_a_503_caught(self):
        g = H.GUARD_FAULTS["guard_trust_any_status"]
        self.assertEqual(fails(H.check_safety(M.Reference(), M.vectors(), guard=g)), {"F9"})

    def test_f9_guard_that_never_retries_caught(self):
        g = H.GUARD_FAULTS["guard_give_up_after_error"]
        self.assertEqual(fails(H.check_safety(M.Reference(), M.vectors(), guard=g)), {"F9"})

    def test_reference_pending_retry_reaches_final_and_credits_once(self):
        fac, v = M.Reference(), M.vectors()
        p, req = v("pending_ok"), v("req")
        g = H.ResourceServerGuard(fac)
        first = fac.settle(p, req)
        self.assertEqual((first["errorReason"], first["transaction"]), (S.SETTLEMENT_PENDING, p["tx"]))
        self.assertFalse(g.settle_and_credit(p, req))          # still pending: retried, not a duplicate, no credit
        self.assertEqual(fac.settle(p, req)["errorReason"], S.SETTLEMENT_PENDING)
        fac.chain.set(p["tx"], M.Chain.CONFIRMED)
        self.assertTrue(g.settle_and_credit(p, req))           # same body, final success, credited once
        again = fac.settle(p, req)
        self.assertEqual(again["errorReason"], S.DUPLICATE_SETTLEMENT)   # a true duplicate after final success
        self.assertFalse(g.settle_and_credit(p, req))
        self.assertEqual(g.credited, {p["tx"]})

    def test_reference_failure_after_pending_is_terminal(self):
        fac, v = M.Reference(), M.vectors()
        p, req = v("pending_fail"), v("req")
        self.assertEqual(fac.settle(p, req)["errorReason"], S.SETTLEMENT_PENDING)
        fac.chain.set(p["tx"], M.Chain.FAILED)
        for _ in range(3):
            r = fac.settle(p, req)
            self.assertEqual((r["success"], r["errorReason"]), (False, S.INVALID_TRANSACTION_STATE))
        fac.chain.set(p["tx"], M.Chain.CONFIRMED)              # a failed transaction never turns into a success
        self.assertEqual(fac.settle(p, req)["errorReason"], S.INVALID_TRANSACTION_STATE)

    def test_guard_never_credits_503_non_json_or_truncated_and_retries(self):
        fac, v = M.Reference(), M.vectors()
        p, req = v("transport_retry"), v("req")
        g = H.ResourceServerGuard(fac)
        for mode in ("http503", "non_json", "truncated"):
            self.assertFalse(g.settle_and_credit(p, req, simulate=mode), mode)
        self.assertEqual(g.credited, set())
        fac.chain.set(p["tx"], M.Chain.CONFIRMED)
        self.assertTrue(g.settle_and_credit(p, req))
        self.assertFalse(g.settle_and_credit(p, req))

    def test_devnet_fixture_targets_devnet(self):
        fx = M.load_fixture("devnet")
        self.assertEqual(fx["requirements"]["network"], "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1")

    def test_f10_cross_request_replay_caught(self):
        self.assertIn("F10", fails(H.check_safety(M.Faulty(cross_request_replay=True), M.vectors())))

    def test_f10_reference_binding_passes(self):
        self.assertNotIn("F10", fails(H.check_safety(M.Reference(), M.vectors())))

    def test_reference_rejects_amount_escalation(self):
        fac, v = M.Reference(), M.vectors()
        p, req = v("good"), v("req")
        self.assertTrue(fac.settle(p, req)["success"])
        higher = dict(req, amount=str(int(req["amount"]) * 2))
        self.assertFalse(fac.verify(p, higher)["isValid"])

    def test_reference_rejects_recipient_substitution(self):
        fac, v = M.Reference(), M.vectors()
        p, req = v("good"), v("req")
        self.assertTrue(fac.settle(p, req)["success"])
        other_dest = dict(req, payTo="AnotherRecipie111111111111111111111111111111")
        self.assertFalse(fac.verify(p, other_dest)["isValid"])

    def test_reference_rejects_resource_substitution(self):
        fac, v = M.Reference(), M.vectors()
        p, req = v("good"), v("req")
        self.assertTrue(fac.settle(p, req)["success"])
        same_price_other_resource = dict(req, resource="https://other.example/protected")
        self.assertFalse(fac.verify(p, same_price_other_resource)["isValid"])
        self.assertFalse(fac.settle(p, same_price_other_resource)["success"])

    def test_verify_fails_closed_on_malformed_requirements(self):
        fac, v = M.Reference(), M.vectors()
        p = v("good")
        for bad in ({}, {"asset": "A"}, {"asset": "A", "payTo": "B", "network": "n"}):
            self.assertFalse(fac.verify(p, bad)["isValid"])
        self.assertFalse(fac.settle(p, {"asset": "A"})["success"])

    def test_same_request_retry_preserves_idempotency(self):
        fac, v = M.Reference(), M.vectors()
        p, req = v("good"), v("req")
        self.assertTrue(fac.settle(p, req)["success"])
        self.assertEqual(fac.settle(p, req)["errorReason"], S.DUPLICATE_SETTLEMENT)
        self.assertTrue(fac.verify(p, req)["isValid"])

    def test_new_payment_for_higher_request_settles(self):
        fac, v = M.Reference(), M.vectors()
        req_b = dict(v("req"), amount="20000")
        p2 = dict(v("good"), tx="tx-higher", memo="m-higher", amount=20000)
        self.assertTrue(fac.settle(p2, req_b)["success"])


class Report(unittest.TestCase):
    """x402conf report: SARIF for code scanning and JUnit for test viewers, built from the Action's results files."""

    def write(self, d, name, obj):
        with open(os.path.join(d, name), "w") as f:
            json.dump(obj, f)

    def results_dir(self):
        d = tempfile.mkdtemp()
        res = {"reference": H.check_safety(M.Faulty(no_dup_cache=True), M.vectors()),
               "no_memo_check": H.check_safety(M.Reference(), M.vectors())}
        self.write(d, "offline.json", {"results": res})
        self.write(d, "live.json", {"results": [
            {"target": "https://f.example", "checks": H.check_supported({"kinds": []})},
            {"target": "https://down.example", "error": "timed out"}]})
        self.write(d, "resource-server.json", {"resource": "http://127.0.0.1:4020/paid", "results": [
            {"check": "R1 a settled payment is served", "pass": True, "detail": {}},
            {"check": "R3 /settle timeout: content not served (F6)", "pass": False, "detail": {"status": 200}}]})
        return d

    def test_sarif_has_one_result_per_failed_check_with_a_fix_link(self):
        d = self.results_dir()
        out = os.path.join(d, "x.sarif")
        self.assertEqual(cli.main(["report", "--dir", d, "--sarif", out]), 0)
        doc = json.load(open(out))
        self.assertEqual(doc["version"], "2.1.0")
        run = doc["runs"][0]
        rules = [r["id"] for r in run["tool"]["driver"]["rules"]]
        got = {r["ruleId"] for r in run["results"]}
        ref_failed = {c["check"].split()[0] for c in json.load(open(os.path.join(d, "offline.json")))["results"]["reference"]
                      if not c["pass"]}
        self.assertEqual(got, ref_failed | {"FX", "S0", "S1", "R3"})
        self.assertIn("F3", got)
        for r in run["results"]:
            self.assertEqual(rules[r["ruleIndex"]], r["ruleId"])
            self.assertIn("docs/FIXES.md#" + r["ruleId"].lower(), r["message"]["text"])
            self.assertTrue(r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"].endswith(".json"))
            self.assertIn("x402ConformanceCheck/v1", r["partialFingerprints"])

    def test_junit_is_wellformed_and_counts_failures(self):
        d = self.results_dir()
        out = os.path.join(d, "junit.xml")
        self.assertEqual(cli.main(["report", "--dir", d, "--junit", out]), 0)
        root = ET.parse(out).getroot()
        self.assertEqual(root.tag, "testsuites")
        failed = {c.get("classname") for c in root.iter("testcase") if c.find("failure") is not None}
        self.assertLessEqual({"x402.F3", "x402.FX", "x402.S0", "x402.S1", "x402.R3"}, failed)
        self.assertEqual(int(root.get("failures")), len(failed))

    def test_every_check_id_has_a_fix_section(self):
        fixes = open(os.path.join(os.path.dirname(__file__), "..", "docs", "FIXES.md")).read()
        ids = ["S0", "S1", "S2", "S3", "S4", "FX"] + [f"F{i}" for i in range(1, 10)] + [f"R{i}" for i in range(10)]
        for i in ids:
            self.assertRegex(fixes, rf"(?m)^## {i}\b", i)

    def test_report_without_results_exits_2(self):
        self.assertEqual(cli.main(["report", "--dir", tempfile.mkdtemp()]), 2)


class VVPreMerge(unittest.TestCase):
    """tools/vv.py: on a pull request only the "pushed" criterion may be pending; everything else stays strict."""

    def setUp(self):
        import importlib.util
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_file_location("vv_under_test", os.path.join(root, "tools", "vv.py"))
        assert spec and spec.loader
        self.vv = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.vv)
        self.vv.sh = lambda cmd, timeout: (0, "  origin/release-x\n")  # HEAD only on a PR branch

    def test_pushed_is_pending_before_the_merge(self):
        self.vv.PRE_MERGE = True
        ok, detail = self.vv.check({"type": "pushed"}, {})
        self.assertTrue(ok)
        self.assertTrue(detail.startswith(self.vv.PENDING))

    def test_pushed_is_strict_on_main(self):
        self.vv.PRE_MERGE = False
        self.assertEqual(self.vv.check({"type": "pushed"}, {}), (False, "HEAD is not on origin/main yet"))

    def test_other_criteria_still_fail_before_the_merge(self):
        self.vv.PRE_MERGE = True
        ok, _ = self.vv.check({"type": "file_exists", "path": "no/such/file"}, {})
        self.assertFalse(ok)
        self.vv.sh = lambda cmd, timeout: (1, "boom")
        ok, _ = self.vv.check({"type": "command", "cmd": "false", "expect_exit": "0"}, {})
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
