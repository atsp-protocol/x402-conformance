"""tools/mutation_matrix.py: the committed matrix is current and every check catches a faulty build, and the checker
fails on a check that catches nothing, on a stale file and on a missing file."""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import mutation_matrix as MM  # noqa: E402
from x402conf import spec as S  # noqa: E402

TOOL = str(ROOT / "tools" / "mutation_matrix.py")


def run(*args: str) -> tuple[int, str]:
    p = subprocess.run([sys.executable, TOOL, *args], capture_output=True, text=True, cwd=ROOT)
    return p.returncode, p.stdout + p.stderr


class MutationMatrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.matrix = MM.build(S.CATALOG, str(ROOT), MM.spec_sha256(str(ROOT)))

    # ---------------- the real tree ----------------
    def test_committed_matrix_is_current(self) -> None:
        rc, out = run("--check")
        self.assertEqual(rc, 0, out)

    def test_every_check_catches_a_faulty_build(self) -> None:
        for cid, c in self.matrix["checks"].items():
            with self.subTest(check=cid):
                self.assertGreater(c["caught"], 0, c["faults"])

    def test_every_catalogue_check_is_in_the_matrix(self) -> None:
        self.assertEqual(set(self.matrix["checks"]), set(S.CATALOG))

    def test_the_build_is_deterministic(self) -> None:
        again = MM.build(S.CATALOG, str(ROOT), MM.spec_sha256(str(ROOT)))
        self.assertEqual(MM.dump(again), MM.dump(self.matrix))
        self.assertNotIn("generated_at", MM.dump(self.matrix))

    def test_a_fault_reference_is_proven_by_running_it(self) -> None:
        row = MM.resolve("F1", "fault:open_on_malformed", str(ROOT), "")
        self.assertTrue(row["caught"], row)
        row = MM.resolve("F2", "fault:open_on_malformed", str(ROOT), "")
        self.assertFalse(row["caught"], "F2 is not what open_on_malformed breaks")

    def test_a_ts_reference_is_proven_by_the_test_title(self) -> None:
        ts = MM.ts_titles(str(ROOT))
        self.assertTrue(MM.resolve("R0", "ts:a server that serves without payment is caught", str(ROOT), ts)["caught"])
        self.assertFalse(MM.resolve("R0", "ts:no such test anywhere", str(ROOT), MM.ts_titles(str(ROOT)))["caught"])

    # ---------------- the checker can fail ----------------
    def test_a_check_with_no_caught_fault_fails_the_matrix_check(self) -> None:
        cat = copy.deepcopy(dict(S.CATALOG))
        cat["F1"] = dict(cat["F1"], faulty=[])
        m = MM.build(cat, str(ROOT), MM.spec_sha256(str(ROOT)))
        found = MM.problems(m, m)
        self.assertEqual(len(found), 1, found)
        self.assertIn("F1 catches no faulty build", found[0])

    def test_a_fault_that_does_not_catch_counts_as_nothing(self) -> None:
        cat = copy.deepcopy(dict(S.CATALOG))
        cat["F2"] = dict(cat["F2"], faulty=["fault:open_on_malformed"])
        m = MM.build(cat, str(ROOT), MM.spec_sha256(str(ROOT)))
        self.assertEqual(m["checks"]["F2"]["caught"], 0)
        self.assertTrue(any(p.startswith("F2 catches no faulty build") for p in MM.problems(m, m)))

    def test_a_stale_file_fails_the_matrix_check(self) -> None:
        stale = copy.deepcopy(self.matrix)
        stale["generated_from"] = "0" * 64
        self.assertTrue(any("stale" in p for p in MM.problems(self.matrix, stale)))
        self.assertTrue(any("missing" in p for p in MM.problems(self.matrix, None)))

    def test_the_cli_fails_on_a_stale_file_in_a_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for d in ("src", "tests", "tools", "ts/test", "docs/site", "corpus"):
                shutil.copytree(ROOT / d, Path(tmp) / d, ignore=shutil.ignore_patterns("__pycache__", "node_modules"))
            path = Path(tmp) / MM.OUT
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
            doc["checks"]["F1"]["caught"] = 99
            with open(path, "w", encoding="utf-8") as f:
                json.dump(doc, f)
            rc, out = run("--check", "--root", tmp)
            self.assertEqual(rc, 1, out)
            self.assertIn("stale", out)
            os.remove(path)
            rc, out = run("--check", "--root", tmp)
            self.assertEqual(rc, 1, out)
            self.assertIn("missing", out)
            rc, out = run("--write", "--root", tmp)
            self.assertEqual(rc, 0, out)
            rc, out = run("--check", "--root", tmp)
            self.assertEqual(rc, 0, out)


if __name__ == "__main__":
    unittest.main()
