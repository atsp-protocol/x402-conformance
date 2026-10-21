"""S1-S4 over GET /supported bodies. No network: bodies are inline or come from the committed evidence."""

import base64
import contextlib
import glob
import io
import json
import os
import tempfile
import unittest
import urllib.error

from x402conf import __version__
from x402conf import cli as C
from x402conf import harness as H
from x402conf import spec as S

FP = "DeXterR2kQm8AvRHnNPatWkE46TfAcMeBDjb6FySoAb8"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fails(results):
    return {r["check"].split()[0] for r in results if not r["pass"]}


class Live(unittest.TestCase):
    def test_s_all_pass_on_conformant_body(self):
        doc = {"kinds": [{"x402Version": 2, "scheme": "exact", "network": S.SOLANA_DEVNET, "extra": {"feePayer": FP}}],
               "extensions": [], "signers": {"solana:*": [FP]}}
        self.assertEqual(fails(H.check_supported(doc)), set())

    def test_s1_shape(self):
        self.assertIn("S1", fails(H.check_supported({"kinds": {}})))

    def test_s2_non_caip2(self):
        doc = {"kinds": [{"x402Version": 2, "scheme": "exact", "network": "base sepolia"}], "extensions": [], "signers": {}}
        self.assertIn("S2", fails(H.check_supported(doc)))

    def test_s3_v1_name_in_v2(self):
        doc = {"kinds": [{"x402Version": 2, "scheme": "exact", "network": "solana-devnet"}], "extensions": [], "signers": {}}
        self.assertIn("S3", fails(H.check_supported(doc)))

    def test_s4_bad_fee_payer(self):
        doc = {"kinds": [{"x402Version": 2, "scheme": "exact", "network": S.SOLANA_MAINNET, "extra": {"feePayer": "x"}}],
               "extensions": [], "signers": {}}
        self.assertEqual(fails(H.check_supported(doc)), {"S4"})

    def test_s4_fee_payer_not_signer(self):
        doc = {"kinds": [{"x402Version": 2, "scheme": "exact", "network": S.SOLANA_MAINNET, "extra": {"feePayer": FP}}],
               "extensions": [], "signers": {"solana:*": ["11111111111111111111111111111111"]}}
        self.assertEqual(fails(H.check_supported(doc)), {"S4"})

    def test_s4_exact_network_signer_key(self):
        doc = {"kinds": [{"x402Version": 2, "scheme": "exact", "network": S.SOLANA_DEVNET, "extra": {"feePayer": FP}}],
               "extensions": [], "signers": {S.SOLANA_DEVNET: [FP]}}
        self.assertEqual(fails(H.check_supported(doc)), set())

    def test_s4_signer_under_other_network_does_not_count(self):
        doc = {"kinds": [{"x402Version": 2, "scheme": "exact", "network": S.SOLANA_MAINNET, "extra": {"feePayer": FP}}],
               "extensions": [], "signers": {S.SOLANA_DEVNET: [FP]}}
        self.assertEqual(fails(H.check_supported(doc)), {"S4"})

    def test_live_mode_is_get_only(self):
        seen = []

        class R:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, n):
                return b'{"kinds":[],"extensions":[],"signers":{}}'

        def opener(req, timeout):
            seen.append(req.get_method())
            return R()

        H.run_live("https://f.example", opener=opener)
        self.assertEqual(seen, ["GET"])

    def test_committed_evidence_reproduces(self):
        """The committed bodies re-check to the committed verdicts."""
        runs = sorted(glob.glob(os.path.join(ROOT, "evidence", "*", "run.json")))
        self.assertTrue(runs)
        for run in runs:
            d = json.load(open(run))
            for r in d["results"]:
                if "body_sha256" not in r:
                    continue
                name = "supported-" + r["target"].split("//", 1)[-1].replace("/", "_") + ".json"
                body = json.load(open(os.path.join(os.path.dirname(run), name)))
                self.assertEqual([c["pass"] for c in H.check_supported(body)], [c["pass"] for c in r["checks"]])

    # ---- 1.3.0 regressions ----
    def test_s1_v1_only_response_graded_as_v1(self):
        """A V1 facilitator (V1 7.3: kinds[] only) is not failed against the V2 shape."""
        doc = {"kinds": [{"x402Version": 1, "scheme": "exact", "network": "base-sepolia"},
                         {"x402Version": 1, "scheme": "exact", "network": "base"}]}
        res = H.check_supported(doc)
        self.assertEqual(fails(res), set())
        self.assertEqual(res[0]["detail"]["graded_as"], "v1")

    def test_s1_mixed_versions_need_v2_shape(self):
        doc = {"kinds": [{"x402Version": 1, "scheme": "exact", "network": "base"},
                         {"x402Version": 2, "scheme": "exact", "network": "eip155:8453"}]}
        self.assertIn("S1", fails(H.check_supported(doc)))

    def test_s4_not_signer_is_a_warning_and_missing_fee_payer_an_error(self):
        not_signer = {"kinds": [{"x402Version": 2, "scheme": "exact", "network": S.SOLANA_MAINNET,
                                 "extra": {"feePayer": FP}}], "extensions": [], "signers": {}}
        bad = {"kinds": [{"x402Version": 2, "scheme": "exact", "network": S.SOLANA_MAINNET, "extra": {}}],
               "extensions": [], "signers": {}}
        self.assertEqual(H.check_supported(not_signer)[3]["severity"], "warning")
        self.assertEqual(H.check_supported(bad)[3]["severity"], "error")

    def test_s0_unreachable_is_a_check(self):
        def opener(req, timeout):
            raise OSError("connection refused")
        r = H.run_live("https://f.example", opener=opener)
        self.assertEqual([(c["check"].split()[0], c["pass"]) for c in r["checks"]], [("S0", False)])

    def test_s0_401_hints_at_credentials(self):
        def opener(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", None, None)  # type: ignore[arg-type]
        r = H.run_live("https://f.example", opener=opener)
        self.assertIn(H.AUTH_ENV, r["checks"][0]["detail"]["hint"])

    def test_auth_header_only_to_its_host_and_never_printed(self):
        secret = "Bearer sk-test-0123456789"
        env = {H.AUTH_ENV: secret, H.AUTH_HOST_ENV: "fac.example"}
        seen = {}

        def opener(req, timeout):
            seen[req.full_url] = req.get_header("Authorization")
            raise OSError("boom " + secret)
        a = H.run_live("https://fac.example", opener=opener, env=env)
        b = H.run_live("https://other.example", opener=opener, env=env)
        self.assertEqual(seen["https://fac.example/supported"], secret)
        self.assertIsNone(seen["https://other.example/supported"])
        self.assertNotIn(secret, json.dumps([a, b]))

    def test_auth_without_host_is_a_usage_error(self):
        with self.assertRaises(H.UsageError):
            H.run_live("https://f.example", env={H.AUTH_ENV: "Bearer x"})

    def _resp(self, status=402, pr=None, headers=None, body=b"{}"):
        h = dict(headers or {})
        if pr is not None:
            h["payment-required"] = base64.b64encode(json.dumps(pr).encode()).decode()
        return {"status": status, "headers": h, "body": body, "ms": 1}

    V2_EVM = {"x402Version": 2, "resource": {"url": "https://api.example/x"},
              "accepts": [{"scheme": "exact", "network": "eip155:84532", "amount": "10000",
                           "asset": "0x036CbD53842c5426634e7929541eC2318f3dCF7e", "payTo": "0x2096",
                           "maxTimeoutSeconds": 60, "extra": {"name": "USDC", "version": "2"}}]}

    def test_p_all_pass_on_spec_example(self):
        self.assertEqual(fails(H.check_402(self._resp(pr=self.V2_EVM))), set())

    def test_p1_served_without_payment(self):
        self.assertEqual(fails(H.check_402(self._resp(status=200))), {"P1"})

    def test_p2_missing_header(self):
        self.assertEqual(fails(H.check_402(self._resp())), {"P2"})

    def test_p3_p4_p5_field_problems(self):
        pr = json.loads(json.dumps(self.V2_EVM))
        pr["accepts"][0].update({"amount": "0.01", "network": "base-sepolia", "extra": {}})
        self.assertEqual(fails(H.check_402(self._resp(pr=pr))), {"P4", "P5"})
        pr2 = dict(self.V2_EVM, resource=None)
        self.assertIn("P3", fails(H.check_402(self._resp(pr=pr2))))

    def test_p_svm_needs_fee_payer(self):
        pr = {"x402Version": 2, "resource": {"url": "u"}, "accepts": [
            {"scheme": "exact", "network": S.SOLANA_DEVNET, "amount": "1", "asset": S.SOLANA_DEVNET_USDC,
             "payTo": FP, "maxTimeoutSeconds": 60, "extra": {}}]}
        self.assertEqual(fails(H.check_402(self._resp(pr=pr))), {"P5"})

    def test_p_v1_body_graded_as_v1(self):
        body = {"x402Version": 1, "error": "X-PAYMENT header is required", "accepts": [
            {"scheme": "exact", "network": "base-sepolia", "maxAmountRequired": "1000", "asset": "0xabc", "payTo": "0xdef",
             "resource": "https://api.example/x", "description": "d", "maxTimeoutSeconds": 60,
             "extra": {"name": "USDC", "version": "2"}}]}
        self.assertEqual(fails(H.check_402(self._resp(body=json.dumps(body).encode()))), set())

    def test_resource_mode_is_get_only(self):
        seen = []

        def opener(req, timeout):
            seen.append(req.get_method())
            raise urllib.error.HTTPError(req.full_url, 402, "Payment Required", None, io.BytesIO(b"{}"))  # type: ignore[arg-type]
        H.run_resource("https://r.example/paid", opener=opener)
        self.assertEqual(seen, ["GET"])

    def _cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = C.main(list(args))
            except SystemExit as e:
                code = int(e.code or 0)
        return code, out.getvalue(), err.getvalue()

    def test_cli_version_and_help_list_every_mode(self):
        code, out, _ = self._cli("--version")
        self.assertEqual((code, out.strip()), (0, f"x402conf {__version__}"))
        code, out, _ = self._cli("--help")
        self.assertEqual(code, 0)
        for m in ("live", "resource", "offline", "report", "devnet"):
            self.assertIn(m, out)
        self.assertEqual(self._cli("bogus")[0], 2)

    def test_report_fail_on_error_and_fail_closed_on_probe_error(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "resource-server.json"), "w") as f:
                json.dump({"resource": "http://127.0.0.1:1/paid", "error": "EADDRINUSE", "results": []}, f)
            self.assertEqual(self._cli("report", "--dir", d)[0], 0)
            code, out, _ = self._cli("report", "--dir", d, "--fail-on-error")
            self.assertEqual(code, 1)
            self.assertIn("RX", json.loads(out)["failed_ids"])
            self.assertEqual(self._cli("report", "--dir", os.path.join(d, "missing"))[0], 2)

    def test_live_auth_usage_error_exits_2(self):
        os.environ[H.AUTH_ENV] = "Bearer x"
        try:
            self.assertEqual(self._cli("live", "https://f.example")[0], 2)
        finally:
            del os.environ[H.AUTH_ENV]

    def _summary(self, d, **want):
        env = {"X402C_DIR": d, "X402C_FAIL": "true", "GITHUB_OUTPUT": os.path.join(d, "out"),
               "GITHUB_STEP_SUMMARY": os.path.join(d, "summary.md")}
        env.update({k: "true" for k in want})
        with contextlib.redirect_stdout(io.StringIO()):
            code = C.action_summary(env)
        return code, open(env["GITHUB_OUTPUT"]).read().strip()

    def test_action_summary_fails_closed_when_the_probe_left_no_results(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self._summary(d, X402C_WANT_PROBE=1), (1, "result=fail"))

    def test_action_summary_reports_unsupported(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "resource-server.json"), "w") as f:
                json.dump({"resource": "http://x/paid", "results": [
                    {"check": "R0 unpaid", "pass": False, "status": "unsupported", "detail": {}}]}, f)
            self.assertEqual(self._summary(d, X402C_WANT_PROBE=1), (1, "result=unsupported"))

    def test_action_summary_passes_complete_results(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "resource-server.json"), "w") as f:
                json.dump({"resource": "http://x/paid", "results": [
                    {"check": f"R{i} ok", "pass": True, "status": "pass", "detail": {}} for i in range(11)]}, f)
            self.assertEqual(self._summary(d, X402C_WANT_PROBE=1), (0, "result=pass"))


if __name__ == "__main__":
    unittest.main()
