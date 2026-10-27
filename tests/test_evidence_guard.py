"""The Action's evidence mode (XC-94): the guard refuses a missing row name and a mainnet network before any request,
and the bundle is one row's evidence with verifying hashes, refused when the run graded mainnet or used a facilitator
that is not on loopback."""
import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest

from x402conf import cli


def quiet(fn, env):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        rc = fn(env)
    return rc, out.getvalue()


def probe_run(d, network="solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1", facilitator="http://127.0.0.1:4402"):
    doc = {"tool": "x402-conformance-svm 1.6.0", "run_at": "2026-10-25T18:00:00Z", "resource": "http://127.0.0.1:4020/paid",
           "facilitator_double": facilitator, "provenance": cli.provenance(),
           "results": [{"check": "R0 unpaid request", "pass": True, "status": "pass", "detail": {"graded_on": network}}],
           "summary": {"checks": 1, "failed": 0}}
    with open(os.path.join(d, "resource-server.json"), "w") as f:
        json.dump(doc, f)


class ActionEvidenceMode(unittest.TestCase):
    def test_guard_refuses_a_mainnet_network(self):
        rc, out = quiet(cli.action_evidence_guard, {"X402C_ROW": "mine-1.0.0", "X402C_NETWORK": "eip155:8453"})
        self.assertEqual(rc, 1)
        self.assertIn("testnet or devnet only", out)
        rc, _ = quiet(cli.action_evidence_guard, {"X402C_ROW": "mine-1.0.0",
                                                  "X402C_NETWORK": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"})
        self.assertEqual(rc, 1)

    def test_guard_refuses_a_missing_or_bad_row_name(self):
        for row in ("", "Has Spaces", "../escape"):
            rc, _ = quiet(cli.action_evidence_guard, {"X402C_ROW": row, "X402C_NETWORK": "auto"})
            self.assertEqual(rc, 1, row)

    def test_guard_control_passes_on_testnet_ids(self):
        for net in ("auto", "eip155:84532", "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"):
            rc, _ = quiet(cli.action_evidence_guard, {"X402C_ROW": "mine-1.0.0", "X402C_NETWORK": net})
            self.assertEqual(rc, 0, net)

    def test_bundle_has_the_run_a_readme_and_verifying_hashes(self):
        d = tempfile.mkdtemp()
        probe_run(d)
        rc, _ = quiet(cli.action_evidence, {"X402C_DIR": d, "X402C_ROW": "mine-1.0.0", "X402C_NETWORK": "auto"})
        self.assertEqual(rc, 0)
        out = os.path.join(d, "evidence-bundle", "mine-1.0.0")
        self.assertEqual(open(os.path.join(out, "run.json"), "rb").read(),
                         open(os.path.join(d, "resource-server.json"), "rb").read())
        for line in open(os.path.join(out, "SHA256SUMS")):
            h, name = line.split()
            self.assertEqual(hashlib.sha256(open(os.path.join(out, name), "rb").read()).hexdigest(), h)
        readme = open(os.path.join(out, "README.md")).read()
        self.assertIn("Environment: devnet", readme)
        self.assertIn("by Optitransfer", readme)

    def test_bundle_refuses_a_mainnet_graded_run(self):
        d = tempfile.mkdtemp()
        probe_run(d, network="eip155:8453")
        rc, out = quiet(cli.action_evidence, {"X402C_DIR": d, "X402C_ROW": "mine-1.0.0", "X402C_NETWORK": "auto"})
        self.assertEqual(rc, 1)
        self.assertIn("mainnet", out)
        self.assertFalse(os.path.exists(os.path.join(d, "evidence-bundle")))

    def test_bundle_refuses_a_facilitator_off_loopback(self):
        d = tempfile.mkdtemp()
        probe_run(d, facilitator="https://facilitator.example.com")
        rc, out = quiet(cli.action_evidence, {"X402C_DIR": d, "X402C_ROW": "mine-1.0.0", "X402C_NETWORK": "auto"})
        self.assertEqual(rc, 1)
        self.assertIn("not on loopback", out)

    def test_bundle_with_nothing_to_bundle_fails(self):
        rc, _ = quiet(cli.action_evidence, {"X402C_DIR": tempfile.mkdtemp(), "X402C_ROW": "mine-1.0.0"})
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
