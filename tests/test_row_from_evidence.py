"""tools/row_from_evidence.py (XC-94): a bundle becomes one committed, listed row, and each unsafe bundle is
refused with nothing written: a bad hash, a mainnet network, a facilitator off loopback, a payment against a live
endpoint, no consent, and an existing row without --update."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "tools", "row_from_evidence.py")
CONSENT = "https://github.com/atsp-protocol/x402-conformance/issues/1"


def run(*args: str) -> tuple[int, str]:
    p = subprocess.run([sys.executable, TOOL, *args], capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


class RowFromEvidence(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        shutil.copytree(os.path.join(ROOT, "evidence", "impl-matrix"), os.path.join(self.root, "evidence", "impl-matrix"))
        os.makedirs(os.path.join(self.root, "docs", "site"))
        for f in ("MATRIX.md", "compat-matrix.json"):
            shutil.copy2(os.path.join(ROOT, "docs", f), os.path.join(self.root, "docs", f))
        shutil.copytree(os.path.join(ROOT, "docs", "site", "badge"), os.path.join(self.root, "docs", "site", "badge"))
        self.bundle = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.bundle, True)
        src = os.path.join(ROOT, "evidence", "impl-matrix", "express-2.28.0", "run.json")
        self.doc = json.load(open(src))
        self.write()

    def write(self, sums: bool = True) -> None:
        with open(os.path.join(self.bundle, "run.json"), "w") as f:
            json.dump(self.doc, f, indent=1)
        with open(os.path.join(self.bundle, "README.md"), "w") as f:
            f.write("# mine-1.0.0\n")
        if sums:
            with open(os.path.join(self.bundle, "SHA256SUMS"), "w") as f:
                for n in ("README.md", "run.json"):
                    f.write(f"{hashlib.sha256(open(os.path.join(self.bundle, n), 'rb').read()).hexdigest()}  {n}\n")

    def go(self, *extra: str) -> tuple[int, str]:
        return run(self.bundle, "--row", "mine-1.0.0", "--root", self.root, *extra)

    def refused(self, rc: int, out: str, text: str) -> None:
        self.assertEqual(rc, 1, out)
        self.assertIn(text, out)
        self.assertFalse(os.path.exists(os.path.join(self.root, "evidence", "impl-matrix", "mine-1.0.0")))

    def test_control_a_good_bundle_becomes_a_listed_row(self) -> None:
        rc, out = self.go("--consent", CONSENT)
        self.assertEqual(rc, 0, out)
        d = os.path.join(self.root, "evidence", "impl-matrix", "mine-1.0.0")
        self.assertIn(CONSENT, open(os.path.join(d, "README.md")).read())
        self.assertIn("| [listed](", next(x for x in open(os.path.join(self.root, "docs", "MATRIX.md")).read().splitlines()
                                          if 'id="row-mine-1.0.0"' in x))
        self.assertIn('id="row-mine-1.0.0"', open(os.path.join(self.root, "docs", "MATRIX.md")).read())
        p = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "compat_matrix.py"), "--check", "--root", self.root],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout)

    def test_a_bad_hash_is_refused(self) -> None:
        with open(os.path.join(self.bundle, "run.json"), "a") as f:
            f.write("\n")
        self.refused(*self.go("--consent", CONSENT), "does not match its hash")

    def test_a_mainnet_network_is_refused(self) -> None:
        self.doc["results"][0]["detail"]["graded_on"] = "eip155:8453"
        self.write()
        self.refused(*self.go("--consent", CONSENT), "mainnet")

    def test_a_facilitator_off_loopback_is_refused(self) -> None:
        self.doc["facilitator_double"] = "https://facilitator.example.com"
        self.write()
        self.refused(*self.go("--consent", CONSENT), "not on loopback")

    def test_a_payment_against_a_live_endpoint_is_refused(self) -> None:
        self.doc["resource"] = "https://shop.example.com/paid"
        self.write()
        self.refused(*self.go("--consent", CONSENT), "payment against a live endpoint")

    def test_no_consent_is_refused(self) -> None:
        self.refused(*self.go(), "no consent")
        self.refused(*self.go("--consent", "yes"), "no consent")

    def test_an_existing_row_needs_update(self) -> None:
        rc, out = run(self.bundle, "--row", "express-2.28.0", "--root", self.root, "--consent", CONSENT)
        self.assertEqual(rc, 1, out)
        self.assertIn("pass --update", out)


if __name__ == "__main__":
    unittest.main()
