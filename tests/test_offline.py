"""F1-F11: the reference double passes; each faulty double is caught by the check that targets it."""

import contextlib
import io
import json
import os
import tempfile
import time
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

    MALFORMED_AMOUNTS = ("abc", None, "1e6", [1], {"v": 1}, 1.5, float("inf"), True, "", "-5", " 10000 ", "+10000",
                         "10_000", "010000", "\uff11\uff10\uff10\uff10\uff10", "10000\n", "1" * 79)

    def test_reference_rejects_malformed_amounts(self):
        # XC-09-AC01: a rejection, never an exception, for every malformed or non-canonical payload amount
        fac, v = M.Reference(), M.vectors()
        for i, amt in enumerate(self.MALFORMED_AMOUNTS):
            p = dict(v("good"), tx=f"tx-amt-{i}", memo=f"m-amt-{i}", amount=amt)
            with self.subTest(amount=amt):
                got = fac.verify(p, v("req"))
                self.assertFalse(got["isValid"], got)
                self.assertFalse(fac.settle(p, v("req"))["success"])

    def test_reference_rejects_malformed_requirement_amounts(self):
        # XC-09-AC02: malformed, zero and negative requirement amounts are invalid_payment_requirements
        fac, v = M.Reference(), M.vectors()
        for amt in self.MALFORMED_AMOUNTS + ("0", 10000):
            with self.subTest(amount=amt):
                got = fac.verify(v("good"), dict(v("req"), amount=amt))
                self.assertEqual(got, {"isValid": False, "invalidReason": "invalid_payment_requirements"})

    def test_strict_parser_accepts_canonical_amounts(self):
        # the control: canonical atomic units still parse, up to uint256
        for x, want in (("0", 0), ("10000", 10000), (str(M.UINT256_MAX), M.UINT256_MAX)):
            self.assertEqual(M.atomic_units(x), want)
        self.assertIsNone(M.atomic_units(str(M.UINT256_MAX + 1)))
        self.assertEqual(M.atomic_units(10000, allow_int=True), 10000)
        self.assertIsNone(M.atomic_units(10000))
        self.assertTrue(M.Reference().verify(M.vectors()("good"), M.vectors()("req"))["isValid"])

    def test_lenient_amounts_caught(self):
        # XC-09-AC03: a double that parses amounts with int() is caught by F1
        self.assertEqual(fails(H.check_safety(M.Faulty(lenient_amounts=True), M.vectors())), {"F1"})

    def test_f5_pending_without_tx_or_network_caught(self):
        # XC-15-AC01
        self.assertIn("F5", fails(H.check_safety(M.Faulty(pending_without_tx=True), M.vectors())))

    def test_f11_verify_commits_state_caught(self):
        # XC-15-AC02: a /verify that commits payment state (V2 7.1) is caught by F11
        self.assertIn("F11", fails(H.check_safety(M.Faulty(verify_commits=True), M.vectors())))

    def test_f12_reference_rejects_unsupported_network_and_asset(self):
        r = next(x for x in H.check_safety(M.Reference(), M.vectors()) if x["check"].startswith("F12 "))
        self.assertTrue(r["pass"], r)
        self.assertEqual(r["detail"]["unsupported_network"]["invalidReason"], "unsupported_network")
        self.assertEqual(r["detail"]["asset_without_code"]["invalidReason"], "invalid_asset")

    def test_f12_trusting_the_requirements_caught(self):
        self.assertEqual(fails(H.check_safety(M.FAULTS["trust_kind"](), M.vectors())), {"F12"})

    def test_f6_guard_crediting_on_error_caught(self):
        g = H.GUARD_FAULTS["guard_credit_on_error"]
        self.assertEqual(fails(H.check_safety(M.Reference(), M.vectors(), guard=g)), {"F6"})

    def test_credibility_matrix_complete(self):
        """XC-16-AC01: every check has a passing control and a faulty build it is proven to catch."""
        import importlib
        import pathlib
        ts = "".join(p.read_text("utf-8") for p in (pathlib.Path(__file__).parent.parent / "ts" / "test").glob("*.ts"))
        emitted = {r["check"].split()[0] for r in H.check_safety(M.Reference(), M.vectors())}
        emitted |= {"S0", "S1", "S2", "S3", "S4", "P1", "P2", "P3", "P4", "P5", "P6", "P7"}
        emitted |= {f"R{i}" for i in range(11)} | {"R11", "R11a", "R11b", "R11c", "R11d", "R11e", "R11f", "R14"}
        emitted |= {"R20", "R20a", "R20b"}
        emitted |= {"C3"}
        emitted |= {"C2"}
        emitted |= {"C1"}
        emitted |= {"R23"}
        emitted |= {"R15"}
        emitted |= {"R16"}
        emitted |= {"R16a"}
        emitted |= {"R24"}
        self.assertEqual(emitted - set(S.CATALOG), set(), "checks with no catalog entry")
        for cid, e in S.CATALOG.items():
            with self.subTest(check=cid):
                self.assertIn(e["profile"], S.PROFILES)
                self.assertTrue(e["basis"])
                self.assertTrue(e["controls"], "no passing control")
                self.assertTrue(e["faulty"], "no faulty build")
                for ref in list(e["controls"]) + list(e["faulty"]):
                    kind, _, name = str(ref).partition(":")
                    if kind == "py":
                        mod, cls, fn = name.rsplit(".", 2)
                        self.assertTrue(hasattr(getattr(importlib.import_module(mod), cls), fn), ref)
                    elif kind == "ts":
                        self.assertIn(name, ts, ref)
                    elif kind == "fault":
                        self.assertIn(cid, fails(H.check_safety(M.FAULTS[name](), M.vectors())), ref)
                    elif kind == "guard":
                        self.assertIn(cid, fails(H.check_safety(M.Reference(), M.vectors(), guard=H.GUARD_FAULTS[name])),
                                      ref)
                    else:
                        self.fail(f"unknown reference {ref}")
        # and nothing is left out of the matrix the other way round
        listed = {str(r).partition(":")[2] for e in S.CATALOG.values() for r in e["faulty"]}
        self.assertEqual(set(M.FAULTS) - {"reference"} - listed, set(), "faulty doubles no check claims")
        self.assertEqual(set(H.GUARD_FAULTS) - listed, set(), "faulty guards no check claims")

    def test_results_carry_profile_and_versions(self):
        """XC-16-AC02: evidence v2. Each result is labelled with its profile and spec basis, and runs name the format."""
        for r in H.check_safety(M.Reference(), M.vectors()):
            self.assertIn(r["profile"], S.PROFILES)
            self.assertTrue(r["basis"])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(cli.main(["offline"]), 0)
        doc = json.loads(buf.getvalue())
        self.assertEqual(doc["evidence"], S.EVIDENCE_FORMAT)
        self.assertTrue(doc["versions"]["x402-conformance"])

    def _corpus_case_holds(self, c, root, ts):
        self.assertEqual(c["schema"], "x402-conformance.case/1")
        self.assertTrue(set(c["failed_ids"]) <= set(S.CATALOG), "unknown check id")
        reg = c["regression"]
        self.assertTrue(reg["control"], "no passing control")
        expect = set(reg["expect_failed"])
        self.assertTrue(expect and expect <= set(c["failed_ids"]), "expect_failed must be some of failed_ids")
        kind, _, name = str(reg["faulty"]).partition(":")
        if kind == "fault":
            if reg["control"] == "reference":
                self.assertEqual(fails(H.check_safety(M.Reference(), M.vectors())) & expect, set(), "control fails")
            self.assertTrue(expect <= fails(H.check_safety(M.FAULTS[name](), M.vectors())), "not caught")
        elif kind == "guard":
            self.assertTrue(expect <= fails(H.check_safety(M.Reference(), M.vectors(), guard=H.GUARD_FAULTS[name])),
                            "not caught")
        elif kind == "answer":
            with open(root / "corpus" / "answers" / name) as f:
                a = json.load(f)
            resp = {"status": a["status"], "headers": a["headers"], "body": a["body"].encode(), "ms": 1}
            self.assertTrue(expect <= fails(H.check_402(resp)), "not caught")
        elif kind == "ts":
            self.assertIn(name, ts, "the TypeScript regression test is missing")
        else:
            self.fail(f"unknown faulty build {reg['faulty']}")

    def test_corpus_cases_are_complete_and_pass(self):
        """XC-20-AC04: every accepted corpus case names a passing control, a faulty build and the checks it must fail,
        and the suite still catches it. See corpus/TEMPLATE.md for the format."""
        import pathlib
        root = pathlib.Path(__file__).parent.parent
        self.assertTrue((root / "corpus" / "TEMPLATE.md").is_file())
        self.assertFalse((root / "evidence" / "corpus").exists(), "the corpus lives at top-level corpus/")
        ts = "".join(p.read_text("utf-8") for p in (root / "ts" / "test").glob("*.ts"))
        for path in sorted((root / "corpus" / "cases").glob("*.json")):
            with self.subTest(case=path.name), open(path) as f:
                self._corpus_case_holds(json.load(f), root, ts)
        # The checker itself: a case the suite catches holds, and one it does not catch, or that names an unknown
        # build or check, is refused. Without this an empty corpus would pass on nothing.
        good = {"schema": "x402-conformance.case/1", "failed_ids": ["F11"],
                "regression": {"control": "reference", "faulty": "fault:verify_commits", "expect_failed": ["F11"]}}
        name = next(k for k, f in M.FAULTS.items() if "F11" in fails(H.check_safety(f(), M.vectors())))
        good["regression"]["faulty"] = f"fault:{name}"
        self._corpus_case_holds(good, root, ts)
        for bad in ({"faulty": "fault:reference"}, {"faulty": "nope:x"}, {"expect_failed": []},
                    {"expect_failed": ["F1"]}, {"faulty": "ts:no such test anywhere"}):
            c = json.loads(json.dumps(good))
            c["regression"].update(bad)
            with self.subTest(bad=bad), self.assertRaises(AssertionError):
                self._corpus_case_holds(c, root, ts)

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

    def test_every_catalog_check_has_a_fix_section(self):
        fixes = open(os.path.join(os.path.dirname(__file__), "..", "docs", "FIXES.md")).read()
        for i in S.CATALOG:
            self.assertRegex(fixes, rf"(?m)^## {i}$", i)

    def test_ts_catalog_matches_spec_catalog(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "ts", "src", "catalog.ts")).read()
        body = src.split("CATALOG: Record<string, { profile: string; basis: string }> = ", 1)[1].split(";\n", 1)[0]
        want = {k: {"profile": v["profile"], "basis": v["basis"]} for k, v in S.CATALOG.items()}
        self.assertEqual(json.loads(body), want)
        self.assertIn(f'EVIDENCE_FORMAT = "{S.EVIDENCE_FORMAT}"', src)

    def test_demo_passes_in_under_60_seconds_with_no_wallet(self):
        d = tempfile.mkdtemp()
        out = io.StringIO()
        t0 = time.monotonic()
        with contextlib.redirect_stdout(out):
            code = cli.main(["demo", "--dir", d])
        self.assertEqual(code, 0, out.getvalue())
        self.assertLess(time.monotonic() - t0, 60)
        self.assertRegex(out.getvalue(), r"(\d+)/\1 checks pass")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["report", "--dir", d, "--fail-on-error"]), 0)

    def test_demo_faults_fail_with_a_fix_link_under_every_failure(self):
        for fault in cli.DEMO_FAULTS:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(cli.main(["demo", "--fault", fault]), 1, fault)
            lines = out.getvalue().splitlines()
            fails = [x for x in lines if x.strip().startswith("FAIL")]
            fixes = [x for x in lines if x.strip().startswith("fix: https://")]
            self.assertTrue(fails, fault)
            self.assertEqual(len(fails), len(fixes), fault)

    def test_badge_is_a_shields_endpoint(self):
        ok = [{"pass": True, "severity": "error"}] * 3
        self.assertEqual(cli.badge(ok), {"schemaVersion": 1, "label": "x402 conformance", "message": "pass 3/3",
                                         "color": "brightgreen"})
        bad = cli.badge(ok + [{"pass": False, "severity": "error"}, {"pass": False, "severity": "warning"}])
        self.assertEqual((bad["message"], bad["color"]), ("1 failing", "red"))
        self.assertEqual(cli.badge([], "unsupported")["message"], "unsupported")
        d = tempfile.mkdtemp()
        with contextlib.redirect_stdout(io.StringIO()):
            cli.main(["demo", "--dir", d])
            cli.main(["report", "--dir", d, "--badge", os.path.join(d, "b.json")])
        self.assertEqual(json.load(open(os.path.join(d, "b.json")))["color"], "brightgreen")

    def test_action_summary_writes_the_sticky_comment_and_badge(self):
        d = tempfile.mkdtemp()
        with contextlib.redirect_stdout(io.StringIO()):
            cli.main(["demo", "--fault", "no_402", "--dir", d])
            cli.action_summary({"X402C_DIR": d, "X402C_WANT_402": "true", "X402C_FAIL": "false"})
        body = open(os.path.join(d, "pr-comment.md")).read()
        self.assertTrue(body.startswith(cli.COMMENT_MARKER))
        self.assertIn("FIXES.md#p1", body)
        self.assertEqual(json.load(open(os.path.join(d, "badge.json")))["color"], "red")

    def test_pr_comment_posts_once_then_updates_in_place(self):
        import http.server
        import threading
        comments: list[dict] = []
        calls: list[str] = []

        class Fake(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def _json(self, code, body):
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                calls.append("GET")
                assert self.headers["Authorization"] == "Bearer t0ken"
                self._json(200, comments)

            def do_POST(self):
                calls.append("POST")
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                comments.append({"id": 7, "body": body["body"]})
                self._json(201, comments[-1])

            def do_PATCH(self):
                calls.append("PATCH " + self.path)
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                comments[0]["body"] = body["body"]
                self._json(200, comments[0])

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        d = tempfile.mkdtemp()
        ev = os.path.join(d, "event.json")
        json.dump({"pull_request": {"number": 3}}, open(ev, "w"))
        md = os.path.join(d, "c.md")
        env = {"GITHUB_EVENT_PATH": ev, "GITHUB_TOKEN": "t0ken", "GITHUB_REPOSITORY": "o/r",
               "GITHUB_API_URL": f"http://127.0.0.1:{srv.server_address[1]}"}
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                open(md, "w").write("first")
                self.assertEqual(cli.pr_comment(md, env), 0)
                open(md, "w").write("second")
                self.assertEqual(cli.pr_comment(md, env), 0)
                out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(cli.pr_comment(md, {**env, "GITHUB_EVENT_PATH": "/nonexistent"}), 0)
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertEqual(calls, ["GET", "POST", "GET", "PATCH /repos/o/r/issues/comments/7"])
        self.assertEqual(len(comments), 1)
        self.assertTrue(comments[0]["body"].startswith(cli.COMMENT_MARKER) and comments[0]["body"].endswith("second"))
        self.assertIn("no comment posted", out.getvalue())

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
