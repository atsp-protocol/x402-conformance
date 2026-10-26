"""Drift reports exactly the normative ids whose anchored text changed."""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from spec_anchors import digest, drifted, quote  # noqa: E402

PIN = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
NEWER = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def _tree(root: str, old: str, new: str) -> None:
    checks = {
        "ids": [],
        "checks": [
            {"id": "F1", "profile": "normative", "anchor": _anchor("same.md", 1, 1, old)},
            {"id": "S0", "profile": "normative", "anchor": _anchor("moved.md", 1, 1, old)},
            {"id": "P1", "profile": "security-profile"},
        ],
    }
    os.makedirs(os.path.join(root, "docs"), exist_ok=True)
    with open(os.path.join(root, "docs", "check-ids.json"), "w", encoding="utf-8") as f:
        json.dump(checks, f)
    for commit, moved in ((PIN, old), (NEWER, new)):
        for name, text in (("same.md", old), ("moved.md", moved)):
            path = os.path.join(root, "docs", "spec-snapshots", commit, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text + "\n")


def _anchor(spec_file: str, start: int, end: int, text: str) -> dict:
    return {
        "spec_file": spec_file,
        "upstream_commit": PIN,
        "line_start": start,
        "line_end": end,
        "quoted_text_sha256": digest(quote([text])),
    }


class Drift(unittest.TestCase):
    def test_lists_only_the_id_whose_text_changed(self) -> None:
        root = tempfile.mkdtemp()
        try:
            _tree(root, "alpha", "beta")
            self.assertEqual(drifted(root, NEWER), ["S0"])
        finally:
            shutil.rmtree(root)

    def test_unchanged_text_lists_nothing(self) -> None:
        root = tempfile.mkdtemp()
        try:
            _tree(root, "alpha", "alpha")
            self.assertEqual(drifted(root, NEWER), [])
        finally:
            shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
