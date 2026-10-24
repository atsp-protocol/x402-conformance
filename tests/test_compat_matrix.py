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
        edited = md.replace(f"| {self.rows[0]} |", f"| {self.rows[0]} (edited by hand) |", 1)
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


if __name__ == "__main__":
    unittest.main()
