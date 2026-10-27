"""tools/run_queue.py (XC-97, XC-98): the free run queue accepts a rerun request only for a listed row in the free
program with a public testnet endpoint, from that row's own issue and contact, for the row's own repository; it keeps
one entry per slug, never reruns a ref, honours the caps, refuses any cap that allows spend or no pinned suite, runs
only the row's endpoint (never its code), turns a tier-1 run into the row, and admits tier-2 attestations to verify."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "tools", "run_queue.py")
ISSUE = "https://github.com/atsp-protocol/x402-conformance/issues/7"
NOW = "2026-10-25T19:00:00Z"


class RunQueue(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        shutil.copytree(os.path.join(ROOT, "matrix"), os.path.join(self.root, "matrix"))
        shutil.copytree(os.path.join(ROOT, "evidence", "impl-matrix"), os.path.join(self.root, "evidence", "impl-matrix"))
        shutil.copytree(os.path.join(ROOT, "docs"), os.path.join(self.root, "docs"))
        self.queue = os.path.join(self.root, "queue-state")
        self.pin("v1.6.0")
        self.row({})

    def pin(self, tag: str | None) -> None:
        p = os.path.join(self.root, "matrix", "queue", "suite.json")
        d = json.load(open(p))
        d.update({"tag": tag, "commit": "69bc4a7adf05983795904639ef12c431742ff850" if tag else None,
                  "version": tag.lstrip("v") if tag else None})
        json.dump(d, open(p, "w"))

    def row(self, over: dict) -> None:
        r = {"schema": "x402-conformance.matrix-row/1", "slug": "example-pay", "project": "Example Pay", "type": "sdk",
             "repo": "https://github.com/example/example-pay", "site": None, "languages": ["TypeScript"],
             "chains": ["EVM"], "networks": ["eip155:84532"], "environments": ["testnet"],
             "testnet_endpoint": "https://sandbox.example.com/paid",
             "version": "1.4.0", "contact": "@example",
             "consent": {"listing": True, "data_license": True, "testnet_only": True, "badge": True, "hook": True},
             "source_issue": ISSUE, "evidence": None, "tier": None, "attestation": None,
             "program_start": "2026-10-25", "program_end": "2027-04-25"}
        r.update(over)
        json.dump(r, open(os.path.join(self.root, "matrix", "rows", "example-pay.json"), "w"))

    def tool(self, *args: str) -> tuple[int, str]:
        p = subprocess.run([sys.executable, TOOL, *args, "--root", self.root], capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr

    def comment(self, text: str, author: str = "example", issue: str = ISSUE, now: str = NOW) -> tuple[int, str]:
        f = os.path.join(self.root, "c.md")
        open(f, "w").write(text)
        return self.tool("enqueue", "--queue", self.queue, "--now", now, "--comment", f, "--issue-url", issue,
                         "--author", author, "--issue-author", "someone")

    def entry(self) -> dict:
        p = os.path.join(self.queue, "matrix", "queue", "example-pay.json")
        return json.load(open(p)) if os.path.isfile(p) else {}

    def test_a_valid_request_is_queued_once_per_slug(self) -> None:
        self.assertEqual(self.comment("/x402-conformance run slug=example-pay ref=" + "v1.5.0" + " version=1.5.0")[0], 0)
        self.assertEqual(self.entry()["status"], "queued")
        self.assertEqual(self.comment("/x402-conformance run slug=example-pay ref=" + "v1.5.1" + " version=1.5.1")[0], 0)
        self.assertEqual((self.entry()["ref"], self.entry()["version"]), ("v1.5.1", "1.5.1"))
        # a commit, not a release
        self.assertEqual(self.comment("/x402-conformance run slug=example-pay ref=" + "a" * 40)[0], 1)
        self.assertEqual(os.listdir(os.path.join(self.queue, "matrix", "queue")), ["example-pay.json"])

    def test_requests_that_are_refused(self) -> None:
        ok = "/x402-conformance run slug=example-pay ref=" + "v1.5.0"
        for args in ((ok, "intruder", ISSUE), (ok, "example", ISSUE[:-1] + "8"), ("hello", "example", ISSUE),
                     (ok + " repo=other/repo", "example", ISSUE),
                     ("/x402-conformance run slug=example-pay ref=../../x", "example", ISSUE),
                     ("/x402-conformance run slug=nope ref=" + "v1.5.0", "example", ISSUE)):
            rc, out = self.comment(*args)
            self.assertEqual(rc, 1, f"{args}: {out}")
            self.assertEqual(self.entry(), {})
        self.row({"consent": {"listing": True, "data_license": True, "testnet_only": True, "badge": True, "hook": False}})
        self.assertEqual(self.comment(ok)[0], 1)
        self.row({"testnet_endpoint": None})
        rc, out = self.comment(ok)
        self.assertEqual(rc, 1)
        self.assertIn("public testnet endpoint", out)

    def test_no_reruns_after_the_program_ends(self) -> None:
        rc, out = self.comment("/x402-conformance run slug=example-pay ref=v2.0.0", now="2027-04-26T00:00:00Z")
        self.assertEqual(rc, 1, out)
        self.assertIn("ended on 2027-04-25", out)
        self.assertIn("free and unlimited", out)
        self.assertEqual(self.comment("/x402-conformance run slug=example-pay ref=v2.0.0", now="2027-04-25T23:00:00Z")[0], 0)

    def test_initial_free_run_is_queued_once(self) -> None:
        out = os.path.join(self.root, "out")
        self.tool("next", "--queue", self.queue, "--now", NOW, "--github-output", out)
        got = dict(line.split("=", 1) for line in open(out).read().splitlines())
        self.assertEqual((got["slug"], got["ref"], got["version"]), ("example-pay", "", "1.4.0"))
        self.assertEqual(self.entry()["source"], "initial")
        self.tool("finish", "--queue", self.queue, "--slug", "example-pay", "--now", NOW, "--result", "ok", "--run-id", "42")
        self.assertIn("nothing to run", self.tool("next", "--queue", self.queue, "--now", "2026-10-27T00:00:00Z")[1])
        self.assertEqual(self.entry()["status"], "sealed")

    def test_only_a_maintainer_publishes_a_sealed_run(self) -> None:
        self.tool("next", "--queue", self.queue, "--now", NOW)
        self.tool("finish", "--queue", self.queue, "--slug", "example-pay", "--now", NOW, "--result", "ok", "--run-id", "42")
        f = os.path.join(self.root, "p.md")
        open(f, "w").write("/x402-conformance publish slug=example-pay run=42")
        self.assertEqual(self.tool("release", "--queue", self.queue, "--comment", f, "--author", "example")[0], 1)
        open(f, "w").write("/x402-conformance publish slug=example-pay run=41")
        self.assertEqual(self.tool("release", "--queue", self.queue, "--comment", f, "--author", "mgillr")[0], 1)
        open(f, "w").write("/x402-conformance publish slug=example-pay run=42")
        out = os.path.join(self.root, "o")
        self.assertEqual(self.tool("release", "--queue", self.queue, "--comment", f, "--author", "mgillr",
                                   "--github-output", out)[0], 0)
        self.assertIn("run_id=42", open(out).read())
        self.assertEqual(self.entry()["status"], "published")

    def test_dispatch_payload(self) -> None:
        f = os.path.join(self.root, "d.json")
        json.dump({"slug": "example-pay", "repo": "example/example-pay", "ref": "v1.5.0", "version": "1.5.0"}, open(f, "w"))
        rc, out = self.tool("enqueue", "--queue", self.queue, "--now", NOW, "--dispatch", f)
        self.assertEqual(rc, 0, out)
        json.dump({"slug": "example-pay", "repo": "evil/repo", "ref": "v1.5.0"}, open(f, "w"))
        self.assertEqual(self.tool("enqueue", "--queue", self.queue, "--now", NOW, "--dispatch", f)[0], 1)

    def test_next_runs_the_rows_own_repo_within_caps_and_never_reruns_a_ref(self) -> None:
        self.comment("/x402-conformance run slug=example-pay ref=" + "v1.5.0" + " version=1.5.0")
        out = os.path.join(self.root, "out")
        self.assertEqual(self.tool("next", "--queue", self.queue, "--now", NOW, "--github-output", out)[0], 0)
        got = dict(line.split("=", 1) for line in open(out).read().splitlines())
        self.assertEqual((got["slug"], got["repo"], got["endpoint"], got["suite"], got["interval"]),
                         ("example-pay", "example/example-pay", "https://sandbox.example.com/paid", "v1.6.0", "5"))
        self.assertNotIn("start", got)
        self.assertEqual(got["head"], "false")  # no HEAD without the operator's permission on the form (XC-110)
        rpath = os.path.join(self.root, "matrix", "rows", "example-pay.json")
        row = json.load(open(rpath))
        row["consent"]["unpaid_head"] = True
        json.dump(row, open(rpath, "w"))
        q = json.load(open(os.path.join(self.queue, "matrix", "queue", "example-pay.json")))
        q["status"] = "queued"
        json.dump(q, open(os.path.join(self.queue, "matrix", "queue", "example-pay.json"), "w"))
        open(out, "w").close()
        self.assertEqual(self.tool("next", "--queue", self.queue, "--now", NOW, "--github-output", out)[0], 0)
        got = dict(line.split("=", 1) for line in open(out).read().splitlines())
        self.assertEqual((got["head"], got["consent"]), ("true", row["source_issue"]))
        self.tool("finish", "--queue", self.queue, "--slug", "example-pay", "--now", NOW, "--result", "ok")
        rc, text = self.comment("/x402-conformance run slug=example-pay ref=" + "v1.5.0")
        self.assertIn("already run", text)
        # a new ref within the per-slug gap waits
        self.comment("/x402-conformance run slug=example-pay ref=" + "v1.6.0", now="2026-10-25T20:00:00Z")
        self.assertIn("nothing to run", self.tool("next", "--queue", self.queue, "--now", "2026-10-25T21:00:00Z")[1])
        self.assertIn("example-pay", self.tool("next", "--queue", self.queue, "--now", "2026-10-26T02:00:00Z")[1])

    def test_caps_that_allow_spend_stop_the_runner(self) -> None:
        caps = os.path.join(self.root, "matrix", "queue", "caps.json")
        c = json.load(open(caps))
        self.assertEqual((c["max_testnet_spend_per_run"], c["max_testnet_spend_per_day"], c["min_probe_interval_s"]), (0, 0, 5))
        c["max_testnet_spend_per_run"] = 1
        json.dump(c, open(caps, "w"))
        self.comment("/x402-conformance run slug=example-pay ref=" + "v1.5.0")
        self.assertIn("nothing picked", self.tool("next", "--queue", self.queue, "--now", NOW)[1])

    def test_no_suite_pinned_runs_nothing(self) -> None:
        self.pin(None)
        self.comment("/x402-conformance run slug=example-pay ref=v1.5.0")
        self.assertIn("no suite release pinned", self.tool("next", "--queue", self.queue, "--now", NOW)[1])

    def test_publish_turns_the_external_run_into_a_tier_1_row(self) -> None:
        bundle = os.path.join(self.root, "bundle")
        os.makedirs(bundle)
        shutil.copy2(os.path.join(ROOT, "tests", "tier1_run.json"), os.path.join(bundle, "run.json"))
        rc, out = self.tool("publish", "--bundle", bundle, "--slug", "example-pay", "--ref", "v1.5.0", "--version", "1.5.0")
        self.assertEqual(rc, 0, out)
        row = json.load(open(os.path.join(self.root, "matrix", "rows", "example-pay.json")))
        self.assertEqual((row["version"], row["evidence"], row["tier"]),
                         ("1.5.0", "evidence/impl-matrix/example-pay", "external-verified"))
        svg = open(os.path.join(self.root, "docs", "site", "badge", "example-pay.svg")).read()
        self.assertIn("External-verified \u00b7 x402-conformance v1.6.0 \u00b7 Optitransfer", svg)
        self.assertIn("8/9 checks \u00b7 2026-10-20", svg)
        md = open(os.path.join(self.root, "docs", "MATRIX.md")).read()
        self.assertIn("| External-verified | testnet | 1.5.0 |", md)
        self.assertIn("| 8/9 | 1 | 9 exercised / 2 NA / 68 needs self-hosted | v1.6.0 |", md)

    def test_attest_requests_follow_the_same_rules(self) -> None:
        f = os.path.join(self.root, "a.md")
        out = os.path.join(self.root, "ao")

        def ask(text: str, author: str = "example") -> tuple[int, str]:
            open(f, "w").write(text)
            return self.tool("attest", "--queue", self.queue, "--now", NOW, "--comment", f, "--issue-url", ISSUE,
                             "--author", author, "--issue-author", "someone", "--github-output", out)
        good = "/x402-conformance attest slug=example-pay repo=example/example-pay ref=v1.5.0 run=123"
        self.assertEqual(ask(good, "intruder")[0], 1)
        self.assertEqual(ask(good.replace("example/example-pay", "evil/repo"))[0], 1)
        self.assertEqual(ask(good.replace(" run=123", ""))[0], 1)
        self.assertEqual(ask(good.replace("ref=v1.5.0", "ref=" + "b" * 40))[0], 1)
        rc, text = ask(good)
        self.assertEqual(rc, 0, text)
        got = dict(line.split("=", 1) for line in open(out).read().splitlines() if line)
        self.assertEqual((got["repo"], got["ref"], got["run"]), ("example/example-pay", "v1.5.0", "123"))
        rc, text = ask(good)
        self.assertEqual(rc, 1)
        self.assertIn("already verified", text)


if __name__ == "__main__":
    unittest.main()
