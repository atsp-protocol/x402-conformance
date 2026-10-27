"""tools/compat_matrix.py: the committed matrix matches the evidence, and each way a row can drift from its evidence
is caught: a hand-edited table row, a row with no SHA256SUMS, a tampered run.json and a stale JSON."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "tools", "compat_matrix.py")


def run(*args: str, root: str) -> tuple[int, str]:
    p = subprocess.run([sys.executable, TOOL, *args, "--root", root], capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


class CompatMatrix(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        shutil.copytree(os.path.join(ROOT, "evidence", "impl-matrix"), os.path.join(self.tmp, "evidence", "impl-matrix"))
        os.makedirs(os.path.join(self.tmp, "docs"))
        for f in ("MATRIX.md", "compat-matrix.json"):
            shutil.copy2(os.path.join(ROOT, "docs", f), os.path.join(self.tmp, "docs", f))
        shutil.copytree(os.path.join(ROOT, "docs", "site", "badge"), os.path.join(self.tmp, "docs", "site", "badge"))
        self.rows = sorted(os.listdir(os.path.join(self.tmp, "evidence", "impl-matrix")))

    # ---------------- the real tree ----------------
    def test_committed_matrix_is_current(self) -> None:
        rc, out = run("--check", root=ROOT)
        self.assertEqual(rc, 0, out)
        self.assertIn("0 problem(s)", out)

    def test_at_least_five_rows_each_linking_run_and_hashes(self) -> None:
        with open(os.path.join(ROOT, "docs", "MATRIX.md"), encoding="utf-8") as f:
            md = f.read()
        table = md[md.index("<!-- compat-matrix:start -->"):md.index("<!-- compat-matrix:end -->")]
        rows = [line for line in table.splitlines() if line.startswith("| ") and "run.json" in line]
        self.assertGreaterEqual(len(rows), 5)
        for line in rows:
            self.assertIn("/run.json)", line)
            self.assertIn("/SHA256SUMS)", line)

    def test_control_an_untouched_copy_passes(self) -> None:
        rc, out = run("--check", root=self.tmp)
        self.assertEqual(rc, 0, out)

    # ---------------- drift ----------------
    def test_a_hand_edited_table_row_is_detected(self) -> None:
        p = os.path.join(self.tmp, "docs", "MATRIX.md")
        with open(p, encoding="utf-8") as f:
            md = f.read()
        edited = md.replace(f"</a>{self.rows[0]} |", f"</a>{self.rows[0]} (edited by hand) |", 1)
        self.assertNotEqual(edited, md)
        with open(p, "w", encoding="utf-8") as f:
            f.write(edited)
        rc, out = run("--check", root=self.tmp)
        self.assertEqual(rc, 1, out)
        self.assertIn("stale or hand-edited", out)

    def test_a_row_without_hashes_is_detected(self) -> None:
        os.remove(os.path.join(self.tmp, "evidence", "impl-matrix", self.rows[0], "SHA256SUMS"))
        rc, out = run("--check", root=self.tmp)
        self.assertEqual(rc, 1, out)
        self.assertIn(f"{self.rows[0]}: no SHA256SUMS", out)

    def test_a_tampered_run_is_detected(self) -> None:
        p = os.path.join(self.tmp, "evidence", "impl-matrix", self.rows[1], "run.json")
        with open(p, "a", encoding="utf-8") as f:
            f.write("\n")
        rc, out = run("--check", root=self.tmp)
        self.assertEqual(rc, 1, out)
        self.assertIn(f"{self.rows[1]}: run.json does not match its hash", out)

    def test_a_stale_json_is_detected(self) -> None:
        p = os.path.join(self.tmp, "docs", "compat-matrix.json")
        with open(p, "a", encoding="utf-8") as f:
            f.write("\n")
        rc, out = run("--check", root=self.tmp)
        self.assertEqual(rc, 1, out)
        self.assertIn("compat-matrix.json is stale", out)

    def test_write_is_deterministic_and_repairs_a_stale_copy(self) -> None:
        p = os.path.join(self.tmp, "docs", "compat-matrix.json")
        with open(p, "a", encoding="utf-8") as f:
            f.write("\n")
        rc, _ = run("--write", root=self.tmp)
        self.assertEqual(rc, 0)
        with open(p, encoding="utf-8") as f:
            first = f.read()
        run("--write", root=self.tmp)
        with open(p, encoding="utf-8") as f:
            self.assertEqual(f.read(), first)
        rc, out = run("--check", root=self.tmp)
        self.assertEqual(rc, 0, out)


class RowFormat(unittest.TestCase):
    """XC-93 and XC-95: the row format (environment, passed/run, failed count only, date, links) and the badges."""

    setUp = CompatMatrix.setUp

    def table_rows(self, root: str) -> list[str]:
        with open(os.path.join(root, "docs", "MATRIX.md"), encoding="utf-8") as f:
            md = f.read()
        table = md[md.index("<!-- compat-matrix:start -->"):md.index("<!-- compat-matrix:end -->")]
        return [line for line in table.splitlines() if line.startswith("| <a id=")]

    def test_every_row_has_environment_counts_date_and_links(self) -> None:
        import json
        d = json.load(open(os.path.join(ROOT, "docs", "compat-matrix.json")))
        for r in d["rows"]:
            self.assertIn(r["environment"], ("testnet", "devnet", "live-not-run", "out-of-reach"))
            self.assertEqual(r["checks_passed"] + r["failed_count"], r["checks_run"])
        rows = self.table_rows(ROOT)
        self.assertEqual(len(rows), len(d["rows"]))
        for line in rows:
            cells = [c.strip() for c in line.strip("|").split("|")]
            self.assertRegex(cells[5], r"^\d+/\d+$")
            self.assertRegex(cells[6], r"^\d+$")
            self.assertRegex(cells[7], r"^\[\d{4}-\d{2}-\d{2}\]\(\.\./evidence/.+/run\.json\)$")
            self.assertIn("(#rerun-or-get-listed)", cells[10])
            self.assertIn("template=check-proposal.yml", cells[11])

    def test_counts_come_from_the_run(self) -> None:
        import json
        p = os.path.join(self.tmp, "evidence", "impl-matrix", self.rows[0], "run.json")
        doc = json.load(open(p))
        doc["results"][0]["status"], doc["results"][0]["pass"] = "fail", False
        with open(p, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=1)
        sums = os.path.join(self.tmp, "evidence", "impl-matrix", self.rows[0], "SHA256SUMS")
        import hashlib
        lines = []
        for line in open(sums, encoding="utf-8"):
            h, name = line.split()
            fp = os.path.join(os.path.dirname(sums), name.lstrip("*"))
            lines.append(f"{hashlib.sha256(open(fp, 'rb').read()).hexdigest()}  {name}")
        with open(sums, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        rc, out = run("--check", root=self.tmp)
        self.assertEqual(rc, 1, out)
        self.assertIn("stale or hand-edited", out)
        self.assertEqual(run("--write", root=self.tmp)[0], 0)
        line = [x for x in self.table_rows(self.tmp) if f'id="row-{self.rows[0]}"' in x][0]
        cells = [c.strip() for c in line.strip("|").split("|")]
        n = len(doc["results"])
        self.assertEqual(cells[5], f"{n - 1}/{n}")
        self.assertEqual(cells[6], "1")
        self.assertNotIn(str(doc["results"][0]["check"]).split(" ")[0] + ",", line)

    def test_a_hand_edited_count_is_detected(self) -> None:
        p = os.path.join(self.tmp, "docs", "MATRIX.md")
        md = open(p, encoding="utf-8").read()
        edited = md.replace(" | 11/11 | ", " | 12/12 | ", 1)
        self.assertNotEqual(edited, md)
        open(p, "w", encoding="utf-8").write(edited)
        rc, out = run("--check", root=self.tmp)
        self.assertEqual(rc, 1, out)

    def test_the_reference_baseline_has_no_badge_and_is_not_a_listing(self) -> None:
        # Opt-in (XC-96): a row without recorded consent is the suite's own baseline; badges belong to listed projects.
        md = open(os.path.join(ROOT, "docs", "MATRIX.md"), encoding="utf-8").read()
        for name in self.rows:
            line = next(x for x in md.splitlines() if f'id="row-{name}"' in x)
            self.assertIn("| baseline |", line)
            self.assertFalse(os.path.exists(os.path.join(ROOT, "docs", "site", "badge", f"{name}.svg")))

    def test_the_matrix_has_no_score_rank_or_certified_wording(self) -> None:
        # Our own headers and prose only: a third-party project name (for example agent-score) is not wording.
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        from matrix_rows import own_text
        md = own_text(open(os.path.join(ROOT, "docs", "MATRIX.md"), encoding="utf-8").read())
        self.assertNotRegex(md, r"(?i)\bcertified\b|\boverall score\b|\branking\b|\branked\b")


if __name__ == "__main__":
    unittest.main()
