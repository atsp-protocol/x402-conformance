"""tools/build_coverage.py: the generated block of docs/COVERAGE.md matches the catalogue, and the check fails when it
does not.

The negative tests copy src/x402conf and docs/COVERAGE.md to a temporary root, break one thing and run the tool with
--root on the copy, so the checker is shown to fail on exactly what it claims to catch."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "tools", "build_coverage.py")
PAGE = Path(ROOT, "docs", "COVERAGE.md")


def run(*args: str) -> tuple[int, str]:
    p = subprocess.run([sys.executable, TOOL, *args], capture_output=True, text=True, timeout=120)
    return p.returncode, p.stdout + p.stderr


def copy_tree(tmp: str) -> Path:
    shutil.copytree(os.path.join(ROOT, "src", "x402conf"), os.path.join(tmp, "src", "x402conf"))
    os.makedirs(os.path.join(tmp, "docs"))
    page = Path(tmp, "docs", "COVERAGE.md")
    shutil.copy(PAGE, page)
    return page


class CoverageDoc(unittest.TestCase):
    def test_committed_page_is_current(self) -> None:
        rc, out = run("--check")
        self.assertEqual(rc, 0, out)
        self.assertIn("is current", out)

    def test_check_fails_on_a_changed_row_and_passes_after_a_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = copy_tree(tmp)
            text = page.read_text(encoding="utf-8")
            self.assertIn("\n| R3 | ", text)
            page.write_text(text.replace("\n| R3 | ", "\n| R3 | CHANGED-ROW ", 1), encoding="utf-8")
            rc, out = run("--check", "--root", tmp)
            self.assertEqual(rc, 1, out)
            self.assertIn("out of date", out)
            rc, out = run("--root", tmp)
            self.assertEqual(rc, 0, out)
            rc, out = run("--check", "--root", tmp)
            self.assertEqual(rc, 0, out)
            self.assertNotIn("CHANGED-ROW", page.read_text(encoding="utf-8"))

    def test_check_fails_when_the_catalogue_gains_a_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            copy_tree(tmp)
            spec = Path(tmp, "src", "x402conf", "spec.py")
            text = spec.read_text(encoding="utf-8")
            marker = '    "R10": {'
            self.assertIn(marker, text)
            spec.write_text(text.replace(marker, '    "R98": {"profile": "resilience", "basis": "x"},\n' + marker, 1),
                            encoding="utf-8")
            rc, out = run("--check", "--root", tmp)
            self.assertNotEqual(rc, 0, out)

    def test_hand_written_sections_survive_a_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = copy_tree(tmp)
            before = page.read_text(encoding="utf-8")
            rc, out = run("--root", tmp)
            self.assertEqual(rc, 0, out)
            after = page.read_text(encoding="utf-8")
            self.assertEqual(after, before)
            self.assertIn("## Networks and schemes", after)
            self.assertIn("## Not covered", after)

    def test_every_catalogue_check_has_a_row(self) -> None:
        sys.path.insert(0, os.path.join(ROOT, "src"))
        from x402conf import spec

        page = PAGE.read_text(encoding="utf-8")
        missing = [i for i in spec.CATALOG if f"\n| {i} | " not in page]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
