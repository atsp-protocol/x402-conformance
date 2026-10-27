"""tools/matrix_rows.py (XC-96, XC-98): an 'Add or update my row' issue becomes matrix/rows/<slug>.json and a row in
docs/MATRIX.md only with all four consents and only when it passes the schema and the public-safe rules; anything
else writes nothing. A linked full-suite run must be a run in the row's own repository; its attestation is verified
by tools/attestation.py. Rows show their tier, passed/applicable, the denominator, the suite tag and the date."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from matrix_rows import alignment, badge_svg, badge_text, own_text  # noqa: E402

TOOL = os.path.join(ROOT, "tools", "matrix_rows.py")
ISSUE = "https://github.com/atsp-protocol/x402-conformance/issues/7"
FORM = "https://github.com/atsp-protocol/x402-conformance/issues/new?template=matrix-row.yml"
COMMIT_A = "c0ffee" + "0" * 34
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def body(**over: str) -> str:
    f = {
        "Project name": "Example Pay", "Type": "SDK", "Repository URL": "https://github.com/example/example-pay",
        "Docs or site URL": "_No response_", "Languages": "TypeScript, Go", "Chain families": "EVM, SVM",
        "Networks (CAIP-2 ids)": "eip155:84532, solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1",
        "Environments you offer": "testnet, devnet", "Testnet endpoint URL (if any)": "_No response_",
        "Version or commit": "1.4.0", "Full-suite run with an attestation (optional)": "_No response_",
        "Public contact handle": "@example",
        "Consent": "- [X] I'm authorised to list this project, and I agree to list this project in the public matrix.\n"
                   "- [X] I agree that its public results are published under CC BY 4.0 (DATA-LICENSE)\n"
                   "- [X] I agree to testnet-only probes of the endpoints above, never mainnet.\n"
                   "- [X] Display the badge in our README with attribution to Optitransfer/x402-conformance",
        "Free run program": "- [ ] Install the notify hook so each new release joins the x402-conformance run queue",
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
        self.assertEqual(row["consent"], {"listing": True, "data_license": True, "testnet_only": True, "badge": True,
                                          "hook": False, "unpaid_head": False})
        self.assertIsNone(row["tier"])
        self.assertNotIn("run", row)
        self.assertEqual(row["source_issue"], ISSUE)
        md = open(os.path.join(self.root, "docs", "MATRIX.md")).read()
        self.assertIn("| total | 1 accepted, 0 with results |", md)
        self.assertNotIn("project-example-pay", md)  # MATRIX.md lists accepted rows with evidence only
        pages = self.pages()
        v = next(x for x in pages["rows"] if x["slug"] == "example-pay")
        self.assertEqual((v["environment"], v["tier"], v["checks_applicable"], v["release_alignment"]),
                         ("testnet", None, None, "not run yet"))
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
        for i in range(4):
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

    def test_free_run_program_needs_hook_and_testnet_endpoint(self) -> None:
        hook = "- [X] Install the notify hook so each new release joins the x402-conformance run queue"
        rc, out = self.submit(body(**{"Free run program": hook}))
        self.assertEqual(rc, 1, out)
        self.assertIn("public testnet endpoint", out)
        rc, out = self.submit(body(**{"Free run program": hook, "Environments you offer": "devnet",
                                      "Testnet endpoint URL (if any)": "https://sandbox.example.com/paid"}))
        self.assertEqual(rc, 1, out)
        rc, out = self.submit(body(**{"Free run program": hook,
                                      "Testnet endpoint URL (if any)": "http://sandbox.example.com/paid"}))
        self.assertEqual(rc, 1, out)
        rc, out = self.submit(body(**{"Free run program": hook,
                                      "Testnet endpoint URL (if any)": "https://sandbox.example.com/paid"}))
        self.assertEqual(rc, 0, out)
        row = json.load(open(os.path.join(self.root, "matrix", "rows", "example-pay.json")))
        self.assertTrue(row["consent"]["hook"])
        self.assertEqual(row["testnet_endpoint"], "https://sandbox.example.com/paid")
        self.assertNotIn("run", row)  # the queue never runs the project's code: no start command
        from matrix_rows import add_months
        self.assertEqual(row["program_end"], add_months(row["program_start"], 6))
        self.assertFalse(row["consent"]["unpaid_head"])  # R16a's HEAD is opt-in on its own (XC-110)

    def test_the_unpaid_head_is_a_separate_optional_permission(self) -> None:
        boxes = ("- [X] Install the notify hook so each new release joins the x402-conformance run queue\n"
                 "- [X] Optional: also allow one unpaid HEAD request per tier-1 run (R16a, is HEAD paywalled like GET)")
        rc, out = self.submit(body(**{"Free run program": boxes,
                                      "Testnet endpoint URL (if any)": "https://sandbox.example.com/paid"}))
        self.assertEqual(rc, 0, out)
        row = json.load(open(os.path.join(self.root, "matrix", "rows", "example-pay.json")))
        self.assertEqual((row["consent"]["hook"], row["consent"]["unpaid_head"]), (True, True))
        form = open(os.path.join(ROOT, ".github", "ISSUE_TEMPLATE", "matrix-row.yml"), encoding="utf-8").read()
        self.assertIn("also allow one unpaid HEAD request per tier-1 run", form)

    def test_readme_snippet_has_badge_and_attribution_line(self) -> None:
        md = open(os.path.join(ROOT, "docs", "MATRIX.md"), encoding="utf-8").read()
        line = next(x for x in md.splitlines() if x.startswith("- Markdown: "))
        self.assertIn("badge/<slug>.svg", line)
        self.assertIn("Conformance tested by [Optitransfer/x402-conformance](https://atsp-protocol.github.io/"
                      "x402-conformance/matrix/#<slug>)", line)
        self.assertIn("Conformance tested by <a href=", next(x for x in md.splitlines() if x.startswith("- HTML: ")))

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

    def test_attestation_link_must_be_a_run_in_the_rows_repo(self) -> None:
        key = "Full-suite run with an attestation (optional)"
        for bad in ("https://github.com/evil/repo/actions/runs/123", "https://example.com/runs/1",
                    "https://github.com/example/example-pay/actions/runs/abc", "{\"results\": []}"):
            rc, out = self.submit(body(**{key: bad}))
            self.assertEqual(rc, 1, f"{bad}: {out}")
            self.assertEqual(self.rows(), [])
        gh_out = os.path.join(self.root, "gh-out")
        p = os.path.join(self.root, "issue.md")
        open(p, "w").write(body(**{key: "https://github.com/example/example-pay/actions/runs/123"}))
        r = subprocess.run([sys.executable, TOOL, "--from-issue", p, "--issue-url", ISSUE, "--root", self.root,
                            "--github-output", gh_out], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)
        out = dict(x.split("=", 1) for x in open(gh_out).read().splitlines())
        self.assertEqual((out["attest_repo"], out["attest_run"]), ("example/example-pay", "123"))
        row = json.load(open(os.path.join(self.root, "matrix", "rows", "example-pay.json")))
        self.assertIsNone(row["tier"])  # tier 2 only once tools/attestation.py has verified the attestation

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
        # after the free run program ends, a row whose last run predates the end goes stale; a later self-run does not
        ended = ("stale (free run program ended 2026-10-24)", True)
        self.assertEqual(alignment("1.5.0", "2026-10-20", rel, "2026-10-24"), ended)
        same_day = {**rel, "checked_at": "2026-10-24"}
        self.assertEqual(alignment("1.5.0", "2026-10-24", same_day, "2026-10-24"), ("current", False))
        self.assertEqual(alignment("1.5.0", "2026-10-25", rel, "2026-10-24"), ("current", False))

    def test_badge_shows_version_and_greys_when_stale(self) -> None:
        """The badge shows the tier, the suite tag (the suite version), checks passed out of applicable and the date;
        it greys out when the row is stale or needs a rerun on the current suite."""
        l1, r1 = badge_text("external-verified", "v1.7.0", 6, 7, "2026-10-20", False, False)
        self.assertEqual((l1, r1), ("External-verified \u00b7 x402-conformance v1.7.0 \u00b7 Optitransfer",
                                    "6/7 checks \u00b7 2026-10-20"))
        l2, r2 = badge_text("full-suite-self-hosted", "v1.7.0", 65, 66, "2026-10-22", False, False)
        self.assertEqual(l2, "Full suite (self-hosted) \u00b7 x402-conformance v1.7.0 \u00b7 Optitransfer")
        self.assertEqual(badge_text("external-verified", "v1.7.0", 6, 7, "2026-10-20", True, False)[1], "stale")
        self.assertEqual(badge_text("full-suite-self-hosted", "v1.6.0", 6, 7, "x", False, True)[1], "rerun on current suite")
        fresh, stale = badge_svg("p", l1, r1, False), badge_svg("p", l1, "stale", True)
        self.assertIn(">6/7 checks \u00b7 2026-10-20<", fresh)
        self.assertIn("#2e7d32", fresh)
        self.assertIn(">stale<", stale)
        self.assertIn("#9e9e9e", stale)
        for svg in (fresh, stale):
            self.assertIn("x402-conformance v1.7.0 \u00b7 Optitransfer", svg)
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

    def test_weekly_check_records_release_and_verifies_attestations(self) -> None:
        from test_attestation import make_attestation, make_root
        root = make_root()
        self.addCleanup(shutil.rmtree, root, True)
        f, g = make_attestation(root)
        facts = os.path.join(root, "facts.json")
        reqs = os.path.join(root, "req.jsonl")
        readme = "[![b](https://atsp-protocol.github.io/x402-conformance/badge/example-pay.svg)](x)"
        json.dump({"example-pay": {"latest": "v1.5.0", "latest_commit": COMMIT_A, "default_branch_commit": "b" * 40,
                                   "attest": {"file": f, "gh_json": g}, "readme": readme}}, open(facts, "w"))
        tool = os.path.join(ROOT, "tools", "matrix_freshness.py")
        r = subprocess.run([sys.executable, tool, "--today", "2026-10-25", "--root", root, "--facts", facts,
                            "--requests", reqs], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("attestation verified", r.stdout)
        row = json.load(open(os.path.join(root, "matrix", "rows", "example-pay.json")))
        self.assertEqual((row["version"], row["tier"]), ("1.5.0", "full-suite-self-hosted"))
        self.assertEqual(row["release"]["behind_since"], None)
        self.assertFalse(os.path.exists(reqs))  # the version tested is the latest release: no rerun asked
        pages = json.load(open(os.path.join(root, "docs", "site", "matrix", "rows.json")))
        v = next(x for x in pages["rows"] if x["slug"] == "example-pay")
        self.assertEqual((v["release_alignment"], v["readme_badge"], v["tier_label"]),
                         ("current", "shown", "Full suite (self-hosted)"))
        # A later release asks the run queue for a tier-1 rerun and puts the row behind from that day.
        json.dump({"example-pay": {"latest": "v1.6.0", "latest_commit": "c" * 40, "default_branch_commit": "c" * 40}},
                  open(facts, "w"))
        for day in ("2026-11-01", "2026-11-08"):
            subprocess.run([sys.executable, tool, "--today", day, "--root", root, "--facts", facts, "--requests", reqs],
                           capture_output=True)
        row = json.load(open(os.path.join(root, "matrix", "rows", "example-pay.json")))
        self.assertEqual(row["release"]["behind_since"], "2026-11-01")
        self.assertIs(row["release"]["readme_badge"], None)  # README not read this time
        req = json.loads(open(reqs).read().splitlines()[0])
        self.assertEqual(req, {"slug": "example-pay", "repo": "example/example-pay", "ref": "v1.6.0", "version": "1.6.0"})
        json.dump({"example-pay": {"latest": "v1.6.0", "latest_commit": "c" * 40, "default_branch_commit": "c" * 40,
                                   "readme": "# no badge here"}}, open(facts, "w"))
        subprocess.run([sys.executable, tool, "--today", "2026-11-08", "--root", root, "--facts", facts], capture_output=True)
        pages = json.load(open(os.path.join(root, "docs", "site", "matrix", "rows.json")))
        v = next(x for x in pages["rows"] if x["slug"] == "example-pay")
        self.assertEqual(v["readme_badge"], "missing (flagged)")
        r = subprocess.run([sys.executable, TOOL, "--check", "--root", root], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_renewal_heads_up_at_five_months(self) -> None:
        t = MatrixRows("test_valid_issue_writes_row_and_table")
        t.setUp()
        self.addCleanup(shutil.rmtree, t.root, True)
        hook = "- [X] Install the notify hook so each new release joins the x402-conformance run queue"
        issue = os.path.join(t.root, "i.md")
        open(issue, "w").write(body(**{"Free run program": hook,
                                       "Testnet endpoint URL (if any)": "https://sandbox.example.com/paid"}))
        r = subprocess.run([sys.executable, TOOL, "--from-issue", issue, "--issue-url", ISSUE, "--root", t.root,
                            "--today", "2026-10-25"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)
        p = os.path.join(t.root, "matrix", "rows", "example-pay.json")
        self.assertEqual(json.load(open(p))["program_end"], "2027-04-25")
        facts, notices = os.path.join(t.root, "f.json"), os.path.join(t.root, "n.jsonl")
        json.dump({"example-pay": {"latest": None, "latest_commit": None, "default_branch_commit": None}}, open(facts, "w"))
        tool = os.path.join(ROOT, "tools", "matrix_freshness.py")
        for day in ("2027-03-24", "2027-03-25", "2027-04-01"):
            subprocess.run([sys.executable, tool, "--today", day, "--root", t.root, "--facts", facts, "--notices", notices],
                           capture_output=True)
        lines = open(notices).read().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["program_end"], "2027-04-25")
        self.assertEqual(json.load(open(p))["program_notice"], "2027-03-25")


if __name__ == "__main__":
    unittest.main()
