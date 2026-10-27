"""XC-125: tools/vv.py runs in shards and the shard receipts merge into one verdict that fails closed.

    PYTHONPATH=src python3 -m unittest -v tests.test_vv_shard

Partition: --shard I/N gives every contract task to exactly one shard. Merge and FailsClosed: a complete set of
passing shard receipts merges into one receipt in the existing schema, and each way a set can be incomplete,
inconsistent or failed makes the merge exit 1. Equivalence: sharded and merged, a contract gives the same per-task
states as one run. Workflow: ci.yml runs the shards as a matrix and the job named vv merges them.
"""
import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import vv  # noqa: E402

HEAD = "a" * 40


def run_main(*args: str) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        rc = vv.main(["vv", *args])
    return rc, out.getvalue()


def chash(contract: dict) -> str:
    import hashlib
    return hashlib.sha256(vv.canon(contract).encode()).hexdigest()


# A small contract of real, cheap verifiers on files every checkout has. T3 is claimed and fails.
SYNTH = {"tasks": [
    {"id": f"T{k}", "title": f"task {k}", "scope": {"allow": ["*"]} if k == 0 else {"allow": []},
     "criteria": [
         {"id": f"T{k}-AC01", "statement": "README exists", "verifier": {"type": "file_exists", "path": "README.md"}},
         {"id": f"T{k}-AC02", "statement": "LICENSE is Apache 2.0",
          "verifier": {"type": "grep", "file": "LICENSE", "pattern": r"Apache License", "must": "present"}},
         *([{"id": f"T{k}-AC03", "statement": "a pattern that is not there",
             "verifier": {"type": "grep", "file": "LICENSE", "pattern": "no-such-text-xc125", "must": "present"}}]
           if k == 3 else []),
     ]} for k in range(7)]}


class Partition(unittest.TestCase):
    def test_every_contract_task_is_in_exactly_one_shard_for_n_1_to_8(self) -> None:
        ids = [t["id"] for t in vv.CONTRACT["tasks"]]
        for n in range(1, 9):
            parts = [[t["id"] for t in vv.partition(vv.CONTRACT["tasks"], i, n)] for i in range(n)]
            flat = [x for p in parts for x in p]
            self.assertEqual(sorted(flat), sorted(ids), n)
            self.assertEqual(len(flat), len(set(flat)), n)
            again = [[t["id"] for t in vv.partition(vv.CONTRACT["tasks"], i, n)] for i in range(n)]
            self.assertEqual(parts, again, n)

    def test_a_malformed_or_out_of_range_shard_is_refused(self) -> None:
        for bad in ("", "1", "a/b", "4/4", "5/4", "0/0", "-1/3", "1/2/3", " 0/2"):
            with self.assertRaises(ValueError, msg=bad):
                vv.parse_shard(bad)
            self.assertEqual(run_main("verify", "--shard", bad)[0], 2, bad)
        self.assertEqual(vv.parse_shard("3/4"), (3, 4))

    def test_a_shard_with_named_tasks_is_refused(self) -> None:
        rc, out = run_main("verify", "--shard", "0/2", "XC-00")
        self.assertEqual(rc, 2)
        self.assertIn("does not take task ids", out)


def shard_receipt(contract: dict, i: int, n: int, **over: object) -> dict:
    tasks = vv.partition(contract["tasks"], i, n)
    report = [{"task": t["id"], "title": t["title"], "state": "met (unclaimed)", "seconds": 0.1,
               "criteria": [{"id": c["id"], "mandatory": True, "pass": True, "detail": "ok", "statement": "",
                             "pending": False} for c in t["criteria"]]} for t in tasks]
    rc = {"v": "x402conf.vv-receipt/1", "t": "2026-10-27T00:00:00Z", "head": HEAD, "mode": "strict", "pending": [],
          "contract_sha256": chash(contract), "signature": "signed: test", "ok": True, "claimed_failed": [],
          "out_of_scope": [], "unknown_claims": [],
          "tasks": [{"task": r["task"], "state": r["state"], "pass": len(r["criteria"]), "of": len(r["criteria"]),
                     "seconds": 0.1} for r in report],
          "shard": f"{i}/{n}", "assigned": [t["id"] for t in tasks]}
    rc.update(over)
    return {"receipt": vv.seal(rc), "report": report}


def write_set(docs: list[dict]) -> list[str]:
    d = tempfile.mkdtemp()
    paths = []
    for k, doc in enumerate(docs):
        p = os.path.join(d, f"vv-{k}.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        paths.append(p)
    return paths


class Merge(unittest.TestCase):
    def test_a_complete_set_of_passing_shards_merges_in_contract_order(self) -> None:
        receipt, report, problems = vv.merge_receipts(write_set([shard_receipt(SYNTH, i, 3) for i in range(3)]), SYNTH)
        self.assertEqual(problems, [])
        self.assertTrue(receipt["ok"])
        self.assertEqual([t["task"] for t in receipt["tasks"]], [t["id"] for t in SYNTH["tasks"]])
        self.assertEqual([r["task"] for r in report], [t["id"] for t in SYNTH["tasks"]])
        self.assertEqual([s["shard"] for s in receipt["shards"]], ["0/3", "1/3", "2/3"])

    def test_the_merged_receipt_keeps_the_receipt_schema_and_is_sealed(self) -> None:
        receipt, _, _ = vv.merge_receipts(write_set([shard_receipt(SYNTH, i, 2) for i in range(2)]), SYNTH)
        for key in ("v", "t", "head", "mode", "pending", "contract_sha256", "signature", "ok", "claimed_failed",
                    "out_of_scope", "unknown_claims", "tasks", "sha256"):
            self.assertIn(key, receipt)
        self.assertEqual(receipt["v"], "x402conf.vv-receipt/1")
        body = {k: v for k, v in receipt.items() if k != "sha256"}
        self.assertEqual(chash(body), receipt["sha256"])

    def test_merge_from_the_command_line_exits_0_and_writes_the_receipt(self) -> None:
        paths = write_set([shard_receipt(vv.CONTRACT, i, 2) for i in range(2)])
        out = tempfile.mkdtemp()
        rc, text = run_main("merge", os.path.dirname(paths[0]), "--receipts", out)
        self.assertEqual(rc, 0, text)
        self.assertEqual(len([f for f in os.listdir(out) if f.endswith("-merged.json")]), 1)


class FailsClosed(unittest.TestCase):
    def merged(self, docs: list[dict]) -> tuple[dict, list[str]]:
        receipt, _, problems = vv.merge_receipts(write_set(docs), SYNTH)
        self.assertFalse(receipt["ok"])
        return receipt, problems

    def good(self, n: int = 3) -> list[dict]:
        return [shard_receipt(SYNTH, i, n) for i in range(n)]

    def test_a_missing_shard_fails(self) -> None:
        self.assertIn("shard 1/3 is missing", self.merged([d for k, d in enumerate(self.good()) if k != 1])[1])

    def test_a_duplicated_shard_fails(self) -> None:
        docs = self.good()
        self.assertIn("shard 0/3 appears more than once", self.merged(docs + [copy.deepcopy(docs[0])])[1])

    def test_a_different_head_fails(self) -> None:
        docs = self.good()
        docs[2] = shard_receipt(SYNTH, 2, 3, head="b" * 40)
        self.assertIn("the shards disagree on head", self.merged(docs)[1])

    def test_a_different_contract_hash_fails(self) -> None:
        docs = self.good()
        docs[1] = shard_receipt(SYNTH, 1, 3, contract_sha256="0" * 64)
        self.assertIn("the shards disagree on contract_sha256", self.merged(docs)[1])

    def test_a_different_mode_fails(self) -> None:
        docs = self.good()
        docs[0] = shard_receipt(SYNTH, 0, 3, mode="pre-merge")
        self.assertIn("the shards disagree on mode", self.merged(docs)[1])

    def test_a_different_signature_state_fails(self) -> None:
        docs = self.good()
        docs[0] = shard_receipt(SYNTH, 0, 3, signature="unsigned: awaiting owner signature")
        self.assertIn("the shards disagree on signature", self.merged(docs)[1])

    def test_a_shard_that_did_not_verify_its_partition_fails(self) -> None:
        docs = self.good()
        dropped = shard_receipt(SYNTH, 1, 3)
        dropped["receipt"]["tasks"] = dropped["receipt"]["tasks"][:-1]
        dropped["receipt"]["assigned"] = dropped["receipt"]["assigned"][:-1]
        docs[1] = {"receipt": vv.seal(dropped["receipt"]), "report": dropped["report"][:-1]}
        self.assertIn("shard 1/3 did not verify exactly its partition", self.merged(docs)[1])

    def test_a_failed_shard_fails(self) -> None:
        docs = self.good()
        docs[2] = shard_receipt(SYNTH, 2, 3, ok=False)
        self.assertIn("shard 2/3 failed", self.merged(docs)[1])

    def test_a_receipt_edited_after_it_was_sealed_fails(self) -> None:
        docs = self.good()
        docs[0]["receipt"]["ok"] = True
        docs[0]["receipt"]["claimed_failed"] = ["T0"]
        self.assertTrue(any("sha256 does not match" in p for p in self.merged(docs)[1]))

    def test_merge_from_the_command_line_exits_1_on_a_missing_shard(self) -> None:
        paths = write_set([shard_receipt(vv.CONTRACT, 0, 2)])
        self.assertEqual(run_main("merge", os.path.dirname(paths[0]), "--receipts", tempfile.mkdtemp())[0], 1)


class Equivalence(unittest.TestCase):
    """The same per-task states and pass counts, sharded and merged or in one run, with real verifiers."""

    def states(self, report: list[dict]) -> list[tuple]:
        return [(r["task"], r["state"], sum(c["pass"] for c in r["criteria"]), len(r["criteria"])) for r in report]

    def run_json(self, *args: str) -> dict:
        rc, out = run_main("verify", *args, "--json")
        return json.loads(out[out.index("{"):])

    def test_sharded_and_merged_equals_one_run_for_n_1_2_3_and_5(self) -> None:
        with mock.patch.object(vv, "CONTRACT", SYNTH), mock.patch.object(vv, "load_claims", lambda: ["T3"]), \
                mock.patch.object(vv, "signature", lambda: (0, {"status": "signed: test"})):
            single = self.run_json()
            self.assertEqual([r["task"] for r in single["report"]], [t["id"] for t in SYNTH["tasks"]])
            self.assertIn(("T3", "FAILED", 2, 3), self.states(single["report"]))
            for n in (1, 2, 3, 5):
                d = tempfile.mkdtemp()
                for i in range(n):
                    run_main("verify", "--shard", f"{i}/{n}", "--receipts", d)
                paths = sorted(os.path.join(d, f) for f in os.listdir(d))
                receipt, report, problems = vv.merge_receipts(paths, SYNTH)
                self.assertEqual(self.states(report), self.states(single["report"]), n)
                self.assertEqual([(t["task"], t["state"], t["pass"], t["of"]) for t in receipt["tasks"]],
                                 [(t["task"], t["state"], t["pass"], t["of"]) for t in single["receipt"]["tasks"]], n)
                self.assertEqual(receipt["claimed_failed"], single["receipt"]["claimed_failed"], n)
                self.assertFalse(receipt["ok"], n)  # T3 is claimed and fails, so its shard fails
                self.assertEqual(problems, [f"shard {[k for k in range(n) if 3 % n == k][0]}/{n} failed"], n)

    def test_without_a_failing_claim_both_pass(self) -> None:
        with mock.patch.object(vv, "CONTRACT", SYNTH), mock.patch.object(vv, "load_claims", lambda: []), \
                mock.patch.object(vv, "signature", lambda: (0, {"status": "signed: test"})):
            single = self.run_json()
            self.assertTrue(single["receipt"]["ok"])
            d = tempfile.mkdtemp()
            for i in range(3):
                run_main("verify", "--shard", f"{i}/3", "--receipts", d)
            receipt, report, problems = vv.merge_receipts(sorted(os.path.join(d, f) for f in os.listdir(d)), SYNTH)
            self.assertEqual(problems, [])
            self.assertTrue(receipt["ok"])
            self.assertEqual(self.states(report), self.states(single["report"]))


class Workflow(unittest.TestCase):
    def setUp(self) -> None:
        import yaml  # the test job installs pyyaml
        with open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8") as f:
            self.jobs = yaml.safe_load(f)["jobs"]

    def runs(self, job: str) -> str:
        return "\n".join(str(s.get("run") or "") for s in self.jobs[job]["steps"])

    def test_vv_shard_is_a_matrix_of_at_least_three_whose_size_is_the_shard_n(self) -> None:
        shards = self.jobs["vv-shard"]["strategy"]["matrix"]["shard"]
        self.assertGreaterEqual(len(shards), 3)
        self.assertEqual(sorted(shards), list(range(len(shards))))
        self.assertIn(f"--shard ${{{{ matrix.shard }}}}/{len(shards)}", self.runs("vv-shard"))
        self.assertFalse(self.jobs["vv-shard"]["strategy"].get("fail-fast", True))

    def test_each_shard_has_20_minutes_at_most_and_no_job_more_than_30(self) -> None:
        self.assertLessEqual(self.jobs["vv-shard"]["timeout-minutes"], 20)
        for name, job in self.jobs.items():
            self.assertLessEqual(job.get("timeout-minutes", 0), 30, name)

    def test_the_job_named_vv_needs_the_shards_merges_them_and_uploads_the_receipt(self) -> None:
        vvjob = self.jobs["vv"]
        needs = vvjob["needs"] if isinstance(vvjob["needs"], list) else [vvjob["needs"]]
        self.assertIn("vv-shard", needs)
        self.assertIn("tools/vv.py merge", self.runs("vv"))
        uses = [str(s.get("uses") or "") for s in vvjob["steps"]]
        self.assertTrue(any(u.startswith("actions/download-artifact@") for u in uses))
        self.assertTrue(any(u.startswith("actions/upload-artifact@") for u in uses))


if __name__ == "__main__":
    unittest.main()
