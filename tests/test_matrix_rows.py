"""tools/matrix_rows.py (XC-96): an 'Add or update my row' issue becomes matrix/rows/<slug>.json and a row in
docs/MATRIX.md only with all three consents and only when it passes the schema and the public-safe rules; anything
else writes nothing. Pasted evidence goes through the same refusals as tools/row_from_evidence.py."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "tools", "matrix_rows.py")
ISSUE = "https://github.com/atsp-protocol/x402-conformance/issues/7"
FORM = "https://github.com/atsp-protocol/x402-conformance/issues/new?template=matrix-row.yml"


def body(**over: str) -> str:
    f = {
        "Project name": "Example Pay", "Type": "SDK", "Repository URL": "https://github.com/example/example-pay",
        "Docs or site URL": "_No response_", "Languages": "TypeScript, Go", "Chain families": "EVM, SVM",
        "Networks (CAIP-2 ids)": "eip155:84532, solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1",
        "Environments you offer": "testnet, devnet", "Testnet endpoint URL (if any)": "_No response_",
        "Version or commit": "1.4.0", "Evidence JSON from your own run (optional)": "_No response_",
        "Public contact handle": "@example",
        "Consent": "- [X] I'm authorised to list this project, and I agree to list this project in the public matrix.\n"
                   "- [X] I agree that its public results are published under CC BY 4.0 (DATA-LICENSE)\n"
                   "- [X] I agree to testnet-only probes of the endpoints above, never mainnet.",
    }
    f.update(over)
    return "\n\n".join(f"### {k}\n\n{v}" for k, v in f.items()) + "\n"


class MatrixRows(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        shutil.copytree(os.path.join(ROOT, "matrix", "schema"), os.path.join(self.root, "matrix", "schema"))
        shutil.copytree(os.path.join(ROOT, "evidence", "impl-matrix"), os.path.join(self.root, "evidence", "impl-matrix"))
        os.makedirs(os.path.join(self.root, "docs", "site"))
        for f in ("MATRIX.md", "compat-matrix.json"):
            shutil.copy2(os.path.join(ROOT, "docs", f), os.path.join(self.root, "docs", f))
        shutil.copytree(os.path.join(ROOT, "docs", "site", "badge"), os.path.join(self.root, "docs", "site", "badge"))

    def submit(self, text: str, issue: str = ISSUE) -> tuple[int, str]:
        p = os.path.join(self.root, "issue.md")
        with open(p, "w") as f:
            f.write(text)
        r = subprocess.run([sys.executable, TOOL, "--from-issue", p, "--issue-url", issue, "--root", self.root],
                           capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    def rows(self) -> list[str]:
        d = os.path.join(self.root, "matrix", "rows")
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    def test_valid_issue_writes_row_and_table(self) -> None:
        rc, out = self.submit(body())
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.rows(), ["example-pay.json"])
        row = json.load(open(os.path.join(self.root, "matrix", "rows", "example-pay.json")))
        self.assertEqual(row["type"], "sdk")
        self.assertEqual(row["consent"], {"listing": True, "data_license": True, "testnet_only": True})
        self.assertEqual(row["source_issue"], ISSUE)
        md = open(os.path.join(self.root, "docs", "MATRIX.md")).read()
        line = next(x for x in md.splitlines() if "project-example-pay" in x)
        self.assertIn("| testnet |", line)
        self.assertIn("not run yet", line)
        self.assertIn(FORM, line)
        self.assertNotRegex(md.lower(), r"overall score|\branking\b|certified")
        r = subprocess.run([sys.executable, TOOL, "--check", "--root", self.root], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_project_names_with_score_or_rank_are_not_wording(self) -> None:
        for name in ("agent-score", "Rank Labs"):
            shutil.rmtree(os.path.join(self.root, "matrix", "rows"), True)
            rc, out = self.submit(body(**{"Project name": name}))
            self.assertEqual(rc, 0, out)
            r = subprocess.run([sys.executable, TOOL, "--check", "--root", self.root], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout)
        md = os.path.join(self.root, "docs", "MATRIX.md")
        with open(md, "a") as f:
            f.write("\nThe overall score is shown here.\n")
        r = subprocess.run([sys.executable, TOOL, "--check", "--root", self.root], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("wording", r.stdout)

    def test_each_missing_consent_writes_nothing(self) -> None:
        lines = body().split("### Consent\n\n")[1].strip().splitlines()
        for i in range(3):
            c = "\n".join(x.replace("[X]", "[ ]") if j == i else x for j, x in enumerate(lines))
            rc, out = self.submit(body(Consent=c))
            self.assertEqual(rc, 1, out)
            self.assertIn("consent not given", out)
            self.assertEqual(self.rows(), [])

    def test_public_safe_rules(self) -> None:
        for over in ({"Public contact handle": "someone@example.com"},
                     {"Version or commit": "1.0 " + "ab" * 32},
                     {"Repository URL": "http://github.com/example/x"},
                     {"Environments you offer": "mainnet-only, testnet"},
                     {"Networks (CAIP-2 ids)": "base mainnet"},
                     {"Type": "exchange"},
                     {"Project name": "<script>x</script>"}):
            rc, out = self.submit(body(**over))
            self.assertEqual(rc, 1, f"{over}: {out}")
            self.assertEqual(self.rows(), [], over)

    def test_mainnet_only_is_live_not_run(self) -> None:
        rc, out = self.submit(body(**{"Environments you offer": "mainnet-only", "Networks (CAIP-2 ids)": "eip155:8453"}))
        self.assertEqual(rc, 0, out)
        md = open(os.path.join(self.root, "docs", "MATRIX.md")).read()
        self.assertIn("| live-not-run |", next(x for x in md.splitlines() if "project-example-pay" in x))

    def test_another_issue_cannot_take_a_row(self) -> None:
        self.assertEqual(self.submit(body())[0], 0)
        rc, out = self.submit(body(**{"Version or commit": "9.9.9"}), issue=ISSUE[:-1] + "8")
        self.assertEqual(rc, 1, out)
        self.assertIn("belongs to another issue", out)
        rc, out = self.submit(body(**{"Version or commit": "1.5.0"}))
        self.assertEqual(rc, 0, out)

    def test_pasted_evidence_is_guarded_and_counted(self) -> None:
        doc = json.load(open(os.path.join(ROOT, "evidence", "impl-matrix", "express-2.28.0", "run.json")))
        rc, out = self.submit(body(**{"Evidence JSON from your own run (optional)": "```json\n" + json.dumps(doc) + "\n```"}))
        self.assertEqual(rc, 0, out)
        row = json.load(open(os.path.join(self.root, "matrix", "rows", "example-pay.json")))
        self.assertEqual(row["evidence"], "evidence/impl-matrix/example-pay")
        md = open(os.path.join(self.root, "docs", "MATRIX.md")).read()
        line = next(x for x in md.splitlines() if "project-example-pay" in x)
        self.assertRegex(line, r"\| \d+/\d+ \| \d+ \|")
        bad = json.dumps(doc).replace("solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1", "eip155:8453")
        shutil.rmtree(os.path.join(self.root, "matrix", "rows"))
        shutil.rmtree(os.path.join(self.root, "evidence", "impl-matrix", "example-pay"))
        rc, out = self.submit(body(**{"Evidence JSON from your own run (optional)": bad}))
        self.assertEqual(rc, 1, out)
        self.assertEqual(self.rows(), [])
        rc, out = self.submit(body(**{"Evidence JSON from your own run (optional)": "{\"not\": \"a run\"}"}))
        self.assertEqual(rc, 1, out)

    def test_check_flags_bad_row_and_stale_table(self) -> None:
        self.assertEqual(self.submit(body())[0], 0)
        p = os.path.join(self.root, "matrix", "rows", "example-pay.json")
        row = json.load(open(p))
        row["consent"]["listing"] = False
        json.dump(row, open(p, "w"))
        r = subprocess.run([sys.executable, TOOL, "--check", "--root", self.root], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        row["consent"]["listing"] = True
        row["version"] = "2.0.0"
        json.dump(row, open(p, "w"))
        r = subprocess.run([sys.executable, TOOL, "--check", "--root", self.root], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("stale", r.stdout)


if __name__ == "__main__":
    unittest.main()
