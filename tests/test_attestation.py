"""tools/attestation.py and src/x402conf/tiers.py (XC-98): the run queue verifies a project's own signed full-suite
run and never runs it. A row becomes tier 2, Full suite (self-hosted), only with an attestation from the row's own
repository, on a release tag, signed by GitHub Actions OIDC for that repository at the attested commit, tag and run,
over this exact file, with every check of the pinned suite present (a check that does not apply has a reason). An
attestation from another suite ref is recorded and the row is marked 'rerun on current suite'."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from x402conf import spec  # noqa: E402
from x402conf import tiers as T  # noqa: E402

TOOL = os.path.join(ROOT, "tools", "attestation.py")
ISSUE = "https://github.com/atsp-protocol/x402-conformance/issues/7"
COMMIT = "c0ffee" + "0" * 34
PIN = {"tag": "v1.7.0", "commit": "1" * 40, "version": "1.7.0"}


def make_root() -> str:
    root = tempfile.mkdtemp()
    shutil.copytree(os.path.join(ROOT, "matrix"), os.path.join(root, "matrix"))
    shutil.copytree(os.path.join(ROOT, "evidence", "impl-matrix"), os.path.join(root, "evidence", "impl-matrix"))
    shutil.copytree(os.path.join(ROOT, "docs"), os.path.join(root, "docs"))
    p = os.path.join(root, "matrix", "queue", "suite.json")
    d = json.load(open(p))
    d.update(PIN)
    json.dump(d, open(p, "w"))
    row = {"schema": "x402-conformance.matrix-row/1", "slug": "example-pay", "project": "Example Pay", "type": "sdk",
           "repo": "https://github.com/example/example-pay", "site": None, "languages": ["TypeScript"],
           "chains": ["EVM"], "networks": ["eip155:84532"], "environments": ["testnet"],
           "testnet_endpoint": "https://sandbox.example.com/paid", "version": "1.4.0", "contact": "@example",
           "consent": {"listing": True, "data_license": True, "testnet_only": True, "badge": True, "hook": True},
           "source_issue": ISSUE, "evidence": None, "tier": None, "attestation": None,
           "program_start": "2026-10-25", "program_end": "2027-04-25"}
    json.dump(row, open(os.path.join(root, "matrix", "rows", "example-pay.json"), "w"))
    return root


def make_attestation(root: str, **over: object) -> tuple[str, str]:
    """An attestation file and the gh attestation verify output that signs it."""
    results = {cid: {"status": "pass"} for cid in spec.CATALOG}
    for cid in ("U1", "U2", "U3", "B1", "B2", "B3", "X1", "X2", "G1", "W1", "W2", "W3", "D1"):
        results[cid] = {"status": "not_applicable", "reason": "this server has no such surface"}
    results["R13"] = {"status": "fail"}
    doc = {"schema": T.ATTESTATION_FORMAT, "row": "example-pay",
           "suite": {"repository": "atsp-protocol/x402-conformance", "ref": "v1", "version": "1.7.0"},
           "vendor": {"repository": "example/example-pay", "ref": "v1.5.0", "ref_type": "tag", "commit": COMMIT,
                      "workflow_ref": "example/example-pay/.github/workflows/x402-conformance-notify.yml@refs/tags/v1.5.0",
                      "run_id": "123", "run_attempt": "1"},
           "generated_at": "2026-10-22T10:00:00Z", "results": results}
    for k, v in over.items():
        if k == "results":
            doc["results"] = {**results, **v}  # type: ignore[dict-item]
        elif isinstance(v, dict):
            doc[k] = {**doc[k], **v}  # type: ignore[dict-item]
        else:
            doc[k] = v
    f = os.path.join(root, "x402-conformance-attestation.json")
    with open(f, "w") as fh:
        json.dump(doc, fh)
    cert = {"issuer": "https://token.actions.githubusercontent.com",
            "sourceRepositoryURI": "https://github.com/example/example-pay", "sourceRepositoryDigest": COMMIT,
            "sourceRepositoryRef": "refs/tags/v1.5.0",
            "runInvocationURI": "https://github.com/example/example-pay/actions/runs/123/attempts/1"}
    g = os.path.join(root, "verify.json")
    gh = [{"verificationResult": {"signature": {"certificate": cert}, "statement": {
        "subject": [{"name": "x402-conformance-attestation.json",
                     "digest": {"sha256": hashlib.sha256(open(f, "rb").read()).hexdigest()}}]}}}]
    json.dump(gh, open(g, "w"))
    return f, g


def verify(root: str, f: str, g: str, *extra: str) -> tuple[int, str]:
    p = subprocess.run([sys.executable, TOOL, "verify", "--file", f, "--gh-json", g, "--slug", "example-pay",
                        "--now", "2026-10-25T20:00:00Z", "--root", root, *extra], capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


class Attestation(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_root()
        self.addCleanup(shutil.rmtree, self.root, True)

    def row(self) -> dict:
        return json.load(open(os.path.join(self.root, "matrix", "rows", "example-pay.json")))

    def test_a_verified_attestation_makes_the_row_tier_2(self) -> None:
        f, g = make_attestation(self.root)
        rc, out = verify(self.root, f, g, "--apply")
        self.assertEqual(rc, 0, out)
        row = self.row()
        self.assertEqual((row["tier"], row["attestation"], row["version"]),
                         ("full-suite-self-hosted", "matrix/attestations/example-pay.json", "1.5.0"))
        md = open(os.path.join(self.root, "docs", "MATRIX.md")).read()
        line = next(x for x in md.splitlines() if "project-example-pay" in x)
        self.assertIn("| Full suite (self-hosted) |", line)
        self.assertIn("| 65/66 | 1 | 66 exercised / 13 NA / 0 needs self-hosted | v1.7.0 |", line)
        svg = open(os.path.join(self.root, "docs", "site", "badge", "example-pay.svg")).read()
        self.assertIn("Full suite (self-hosted) \u00b7 x402-conformance v1.7.0 \u00b7 Optitransfer", svg)
        self.assertIn("65/66 checks \u00b7 2026-10-22", svg)
        self.assertIn("#2e7d32", svg)
        r = subprocess.run([sys.executable, TOOL, "check", "--root", self.root], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "matrix_rows.py"), "--check", "--root", self.root],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_an_older_suite_is_listed_as_rerun_on_current_suite(self) -> None:
        f, g = make_attestation(self.root, suite={"ref": "v1.6.0", "version": "1.6.0"})
        rc, out = verify(self.root, f, g, "--apply")
        self.assertEqual(rc, 0, out)
        self.assertIn("rerun on current suite", out)
        md = open(os.path.join(self.root, "docs", "MATRIX.md")).read()
        self.assertIn("| v1.6.0 (rerun on current suite) |", md)
        svg = open(os.path.join(self.root, "docs", "site", "badge", "example-pay.svg")).read()
        self.assertIn(">rerun on current suite<", svg)
        self.assertIn("#9e9e9e", svg)

    def test_refused_attestations_write_nothing(self) -> None:
        cases = {
            "another repository": {"vendor": {"repository": "evil/repo"}},
            "a branch": {"vendor": {"ref_type": "branch", "ref": "main"}},
            "another row": {"row": "other"},
            "a missing applicable check": {"results": {"R2": {"status": "not_run"}}},
            "a reasonless not applicable": {"results": {"R3": {"status": "not_applicable"}}},
            "an email": {"results": {"U1": {"status": "not_applicable", "reason": "ask me@example.com"}}},
        }
        for name, over in cases.items():
            f, g = make_attestation(self.root, **over)
            rc, out = verify(self.root, f, g, "--apply")
            self.assertEqual(rc, 1, f"{name}: {out}")
            self.assertIsNone(self.row()["tier"], name)
            self.assertFalse(os.path.exists(os.path.join(self.root, "matrix", "attestations", "example-pay.json")), name)

    def test_the_signature_must_be_over_this_file_by_the_rows_repository(self) -> None:
        f, g = make_attestation(self.root)
        gh = json.load(open(g))
        for field, value in (("sourceRepositoryURI", "https://github.com/evil/repo"),
                             ("sourceRepositoryDigest", "d" * 40), ("sourceRepositoryRef", "refs/heads/main"),
                             ("issuer", "https://example.com"),
                             ("runInvocationURI", "https://github.com/example/example-pay/actions/runs/999/attempts/1")):
            bad = json.loads(json.dumps(gh))
            bad[0]["verificationResult"]["signature"]["certificate"][field] = value
            json.dump(bad, open(g, "w"))
            rc, out = verify(self.root, f, g)
            self.assertEqual(rc, 1, f"{field}: {out}")
            self.assertIn("signing identity", out)
        json.dump(gh, open(g, "w"))
        with open(f, "a") as fh:
            fh.write(" ")  # the signature no longer covers the file
        rc, out = verify(self.root, f, g)
        self.assertEqual(rc, 1, out)
        self.assertIn("no verified signature", out)
        rc, out = verify(self.root, f, os.path.join(self.root, "missing.json"))
        self.assertEqual(rc, 1, out)

    def test_nothing_is_verified_without_a_pinned_suite_or_after_the_program(self) -> None:
        p = os.path.join(self.root, "matrix", "queue", "suite.json")
        d = json.load(open(p))
        f, g = make_attestation(self.root)
        json.dump({**d, "tag": None}, open(p, "w"))
        self.assertIn("no suite release is pinned", verify(self.root, f, g)[1])
        json.dump(d, open(p, "w"))
        r = subprocess.run([sys.executable, TOOL, "verify", "--file", f, "--gh-json", g, "--slug", "example-pay",
                            "--now", "2027-04-26T00:00:00Z", "--root", self.root], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("has ended", r.stdout)

    def test_the_action_writes_one_entry_per_check_with_reasons(self) -> None:
        d = os.path.join(self.root, "results")
        os.makedirs(d)
        shutil.copy2(os.path.join(ROOT, "evidence", "impl-matrix", "express-2.28.0", "run.json"),
                     os.path.join(d, "resource-server.json"))
        out = os.path.join(self.root, "gh-out")
        env = {"X402C_DIR": d, "X402C_ROW": "example-pay", "X402C_NOT_APPLICABLE": "U1: no upto scheme; X1: no MCP tools",
               "X402C_SUITE_REF": "v1.7.0", "GITHUB_REPOSITORY": "example/example-pay", "GITHUB_REF_NAME": "v1.5.0",
               "GITHUB_REF_TYPE": "tag", "GITHUB_SHA": COMMIT, "GITHUB_RUN_ID": "123", "GITHUB_OUTPUT": out}
        self.assertEqual(T.action_attestation(env), 0)
        doc = json.load(open(os.path.join(d, "attestation", T.ATTESTATION_FILE)))
        self.assertEqual(sorted(doc["results"]), sorted(spec.CATALOG))
        self.assertEqual(doc["results"]["U1"], {"status": "not_applicable", "reason": "no upto scheme", "declared": True})
        self.assertEqual(doc["results"]["R0"]["status"], "pass")
        self.assertEqual(doc["results"]["S0"]["status"], "not_run")
        self.assertEqual((doc["vendor"]["repository"], doc["vendor"]["commit"], doc["suite"]["ref"]),
                         ("example/example-pay", COMMIT, "v1.7.0"))
        self.assertIn("attestation=", open(out).read())
        self.assertEqual(T.action_attestation({**env, "X402C_NOT_APPLICABLE": "Z9: nope"}), 1)
        self.assertNotRegex(json.dumps(doc), r"[0-9a-f]{64}|BEGIN|@[a-z]+\.[a-z]")

    def test_tier_1_counts_only_the_external_checks(self) -> None:
        r = T.tier1_results(T.results_from_run(os.path.join(ROOT, "tests", "tier1_run.json")))
        self.assertEqual(set(r), set(T.EXTERNAL))
        c = T.denominator(r, T.TIER1)
        self.assertEqual((c["passed"], c["applicable"], c["failed"], c["not_applicable"], c["needs_self_hosted"]),
                         (8, 9, 1, 2, len(spec.CATALOG) - len(T.EXTERNAL)))
        self.assertEqual((r["R16a"]["status"], r["R24"]["status"]), ("pass", "pass"))
        self.assertTrue(T.EXTERNAL <= set(spec.CATALOG))
        pin = json.load(open(os.path.join(ROOT, "matrix", "queue", "suite.json")))
        self.assertTrue(set(pin["checks"]) <= set(spec.CATALOG))


if __name__ == "__main__":
    unittest.main()
