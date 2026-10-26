"""tools/check_ids.py (XC-53): a removed id, a reused id and a silently changed property are each detected."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from check_ids import meaning_problems  # noqa: E402

SINCE = {"F1": {"profile": "normative", "basis": "pays once"}}


def entry(prop: str, status: str = "active") -> dict[str, str]:
    return {"id": "F1", "profile": "normative", "property": prop, "basis": prop,
            "first_release": "v1.6.0", "status": status}


class CheckIds(unittest.TestCase):
    def test_removed_id_is_detected(self) -> None:
        got = meaning_problems(SINCE, [], "")
        self.assertIn("removed F1", got)

    def test_reused_id_is_detected(self) -> None:
        # A deprecation entry keeps the old meaning. It does not let the same id say something else.
        got = meaning_problems(SINCE, [entry("pays twice")], "deprecated F1, the old property stays")
        self.assertIn("reused F1", got)
        self.assertFalse(any(p.startswith("silent") for p in got))

    def test_silent_property_change_is_detected(self) -> None:
        got = meaning_problems(SINCE, [entry("pays twice")], "")
        self.assertIn("silent F1", got)

    def test_unchanged_property_is_clean(self) -> None:
        self.assertEqual(meaning_problems(SINCE, [entry("pays once")], ""), [])


if __name__ == "__main__":
    unittest.main()
