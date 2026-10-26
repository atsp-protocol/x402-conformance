"""tools/traceability.py (XC-82): every check is normative or hardening, once, and each way a table can be wrong fails."""
import contextlib
import copy
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from traceability import build, load_catalog, load_registry, main, problems  # noqa: E402

CATALOG = load_catalog(ROOT)
TABLE = build(CATALOG, *load_registry(ROOT))


def row(table: dict, cid: str) -> dict:
    return next(r for r in table["rows"] if r["id"] == cid)


def first(table: dict, cls: str) -> str:
    return next(r["id"] for r in table["rows"] if r["class"] == cls)


class Classification(unittest.TestCase):
    def test_the_catalogue_classifies_cleanly(self) -> None:
        self.assertEqual(problems(TABLE, CATALOG, ROOT), [])
        self.assertEqual(sum(TABLE["counts"].values()), len(CATALOG))
        self.assertTrue(TABLE["counts"]["normative"] and TABLE["counts"]["hardening"])

    def test_an_unclassified_check_fails(self) -> None:
        t = copy.deepcopy(TABLE)
        gone = t["rows"].pop()
        t["counts"][gone["class"]] -= 1
        self.assertIn(f"{gone['id']}: not classified", problems(t, CATALOG, ROOT))

    def test_a_check_in_both_classes_fails(self) -> None:
        t = copy.deepcopy(TABLE)
        cid = first(t, "hardening")
        t["rows"].append({**row(t, cid), "class": "normative", "anchor": row(t, first(t, "normative"))["anchor"]})
        t["counts"]["normative"] += 1
        self.assertIn(f"{cid}: in both classes", problems(t, CATALOG, ROOT))

    def test_a_normative_row_with_no_anchor_fails(self) -> None:
        t = copy.deepcopy(TABLE)
        cid = first(t, "normative")
        row(t, cid)["anchor"] = None
        self.assertIn(f"{cid}: a normative row with no spec anchor", problems(t, CATALOG, ROOT))

    def test_an_anchor_whose_quoted_text_changed_fails(self) -> None:
        t = copy.deepcopy(TABLE)
        cid = first(t, "normative")
        row(t, cid)["anchor"] = {**row(t, cid)["anchor"], "quoted_text_sha256": "0" * 64}
        self.assertTrue(any(p.startswith(f"{cid}: its anchor's quoted text") for p in problems(t, CATALOG, ROOT)))

    def test_a_hardening_row_with_no_reason_fails(self) -> None:
        t = copy.deepcopy(TABLE)
        cid = first(t, "hardening")
        row(t, cid)["reason"] = ""
        self.assertIn(f"{cid}: a hardening row with no reason", problems(t, CATALOG, ROOT))


class Freshness(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, "docs"))
        os.symlink(os.path.join(ROOT, "src"), os.path.join(self.root, "src"))
        os.symlink(os.path.join(ROOT, "docs", "spec-snapshots"), os.path.join(self.root, "docs", "spec-snapshots"))
        shutil.copy(os.path.join(ROOT, "docs", "check-ids.json"), os.path.join(self.root, "docs", "check-ids.json"))

    def run_main(self, *args: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = main([*args, "--root", self.root])
        return rc, out.getvalue()

    def test_a_written_table_is_fresh(self) -> None:
        self.assertEqual(self.run_main()[0], 0)
        rc, out = self.run_main("--check")
        self.assertEqual(rc, 0, out)
        self.assertIn("ok ", out)

    def test_a_stale_table_fails(self) -> None:
        self.run_main()
        path = os.path.join(self.root, "docs", "traceability.json")
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        doc["rows"][0]["property"] = "edited by hand"
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
        rc, out = self.run_main("--check")
        self.assertEqual(rc, 1)
        self.assertIn("is stale", out)

    def test_a_missing_table_fails(self) -> None:
        self.assertEqual(self.run_main("--check")[0], 1)


if __name__ == "__main__":
    unittest.main()
