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
sys.path.insert(0, os.path.join(ROOT, "tools"))
from matrix_rows import alignment, badge_svg, own_text  # noqa: E402

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
        shutil.copytree(os.path.join(ROOT, "docs", "site", "matrix"), os.path.join(self.root, "docs", "site", "matrix"))

    def submit(self, text: str, issue: str = ISSUE) -> tuple[int, str]:
        p = os.path.join(self.root, "issue.md")
        with open(p, "w") as f:
            f.write(text)
        r = subprocess.run([sys.executable, TOOL, "--from-issue", p, "--issue-url", issue, "--root", self.root],
                           capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    def pages(self) -> dict:
        return json.load(open(os.path.join(self.root, "docs", "site", "matrix", "rows.json")))

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
        self.assertIn("| total | 1 accepted, 0 with committed evidence |", md)
        self.assertNotIn("project-example-pay", md)  # MATRIX.md lists accepted rows with evidence only
        pages = self.pages()
        v = next(x for x in pages["rows"] if x["slug"] == "example-pay")
        self.assertEqual((v["environment"], v["checks_run"], v["release_alignment"]), ("testnet", None, "not run yet"))
        html = open(os.path.join(self.root, "docs", "site", "matrix", "index.html")).read()
        self.assertIn('<tr id="example-pay">', html)
        self.assertNotRegex(own_text(md).lower(), r"overall score|\branking\b|certified")
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
        v = next(x for x in self.pages()["rows"] if x["slug"] == "example-pay")
        self.assertEqual(v["environment"], "live-not-run")

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
        self.assertIn("badge/example-pay.svg)](https://atsp-protocol.github.io/x402-conformance/matrix/#example-pay)", line)
        svg = open(os.path.join(self.root, "docs", "site", "badge", "example-pay.svg")).read()
        self.assertIn("Tested with x402-conformance \u00b7 Optitransfer", svg)
        self.assertIn("v1.4.0", svg)
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


class Freshness(unittest.TestCase):
    def test_alignment(self) -> None:
        rel = {"checked_at": "2026-10-25", "latest": "v1.5.0", "default_branch_commit": None, "behind_since": None}
        self.assertEqual(alignment("1.5.0", "2026-10-20", rel), ("current", False))
        self.assertEqual(alignment("1.4.0", "2026-10-20", {**rel, "behind_since": "2026-10-18"}),
                         ("behind (v1.4.0 tested, v1.5.0 latest)", False))
        self.assertEqual(alignment("1.4.0", "2026-10-20", {**rel, "behind_since": "2026-09-25"})[1], True)
        self.assertEqual(alignment("1.5.0", "2026-09-24", rel), ("stale", True))
        self.assertEqual(alignment("1.5.0", "2026-10-20", None), ("not checked yet", False))
        self.assertEqual(alignment("1.5.0", None, rel), ("not run yet", False))

    def test_badge_shows_version_and_greys_when_stale(self) -> None:
        fresh, stale = badge_svg("p", "1.5.0", False), badge_svg("p", "1.5.0", True)
        self.assertIn(">v1.5.0<", fresh)
        self.assertIn("#2e7d32", fresh)
        self.assertIn(">stale<", stale)
        self.assertIn("#9e9e9e", stale)
        for svg in (fresh, stale):
            self.assertIn("Tested with x402-conformance \u00b7 Optitransfer", svg)
            self.assertIn("https://atsp-protocol.github.io/x402-conformance/matrix/#p", svg)
            self.assertNotRegex(svg.lower(), r"certified|compliant|approved|endorsed|<script|<image|<img|x402 logo")

    def test_example_row_is_labelled_and_not_counted(self) -> None:
        md = open(os.path.join(ROOT, "docs", "MATRIX.md"), encoding="utf-8").read()
        line = next(x for x in md.splitlines() if 'id="project-example"' in x)
        self.assertIn("Example (illustrative, not a real result)", line)
        self.assertIn("example-org/example-x402-server", line)
        html = open(os.path.join(ROOT, "docs", "site", "matrix", "index.html"), encoding="utf-8").read()
        self.assertIn('<tr id="example" class="example"><td><strong>Example (illustrative, not a real result):', html)
        pages = json.load(open(os.path.join(ROOT, "docs", "site", "matrix", "rows.json"), encoding="utf-8"))
        self.assertNotIn("example", [r["slug"] for r in pages["rows"]])

    def test_weekly_check_records_release_and_pulls_vendor_evidence(self) -> None:
        import io
        import zipfile
        t = MatrixRows("test_valid_issue_writes_row_and_table")
        t.setUp()
        self.addCleanup(shutil.rmtree, t.root, True)
        self.assertEqual(t.submit(body())[0], 0)
        run = open(os.path.join(ROOT, "evidence", "impl-matrix", "express-2.28.0", "run.json"), "rb").read()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("run.json", run)
            z.writestr("../escape.txt", "x")
        zp = os.path.join(t.root, "a.zip")
        open(zp, "wb").write(buf.getvalue())
        facts = os.path.join(t.root, "facts.json")
        json.dump({"example-pay": {"latest": "v1.5.0", "latest_commit": "a" * 40, "default_branch_commit": "b" * 40,
                                   "run": {"head_sha": "a" * 40, "zip": zp}}}, open(facts, "w"))
        tool = os.path.join(ROOT, "tools", "matrix_freshness.py")
        r = subprocess.run([sys.executable, tool, "--today", "2026-10-25", "--root", t.root, "--facts", facts],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        row = json.load(open(os.path.join(t.root, "matrix", "rows", "example-pay.json")))
        self.assertEqual(row["version"], "1.5.0")
        self.assertEqual(row["evidence"], "evidence/impl-matrix/example-pay")
        self.assertEqual(row["release"]["behind_since"], None)
        self.assertFalse(os.path.exists(os.path.join(t.root, "escape.txt")))
        v = next(x for x in t.pages()["rows"] if x["slug"] == "example-pay")
        self.assertEqual(v["release_alignment"], "current")
        # A later release puts it behind; behind_since stays the first day it fell behind.
        json.dump({"example-pay": {"latest": "v1.6.0", "latest_commit": "c" * 40, "default_branch_commit": "c" * 40}},
                  open(facts, "w"))
        for day in ("2026-11-01", "2026-11-08"):
            subprocess.run([sys.executable, tool, "--today", day, "--root", t.root, "--facts", facts], capture_output=True)
        row = json.load(open(os.path.join(t.root, "matrix", "rows", "example-pay.json")))
        self.assertEqual(row["release"]["behind_since"], "2026-11-01")
        r = subprocess.run([sys.executable, TOOL, "--check", "--root", t.root], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)


if __name__ == "__main__":
    unittest.main()
