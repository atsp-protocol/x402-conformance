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
    costs, costs_sha = vv.load_costs()  # the split the checkout uses (XC-126), as a real shard records it
    rc.update({"partition": "cost" if costs else "position", "costs_sha256": costs_sha})
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


# XC-126: the split by measured cost. COSTS_FILE is patched to a temporary file (or a missing one) so each test sets
# the checkout's vv/costs.json itself.
def costs_file(seconds: dict | None) -> str:
    d = tempfile.mkdtemp()
    p = os.path.join(d, "costs.json")
    if seconds is not None:
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps({"v": "x402conf.vv-costs/1", "source_runs": ["1"], "seconds": seconds}, indent=1) + "\n")
    return p


UNEVEN = {"T0": 1.0, "T1": 2.0, "T2": 3.0, "T3": 40.0, "T4": 5.0, "T5": 6.0}  # T6 has no cost: the median, 4.0


class CostPartition(unittest.TestCase):
    def test_every_task_is_in_exactly_one_shard_in_contract_order_for_n_1_to_8(self) -> None:
        costs, _ = vv.load_costs()
        self.assertTrue(costs, "the committed vv/costs.json")
        ids = [t["id"] for t in vv.CONTRACT["tasks"]]
        for n in range(1, 9):
            parts = [[t["id"] for t in vv.partition(vv.CONTRACT["tasks"], i, n, costs)] for i in range(n)]
            flat = [x for p in parts for x in p]
            self.assertEqual(sorted(flat), sorted(ids), n)
            self.assertEqual(len(flat), len(set(flat)), n)
            for p in parts:
                self.assertEqual(p, [x for x in ids if x in p], n)  # contract order inside a shard
            self.assertEqual(parts, [[t["id"] for t in vv.partition(vv.CONTRACT["tasks"], i, n, costs)]
                                     for i in range(n)], n)

    def test_the_largest_shard_is_at_most_the_mean_plus_the_largest_task(self) -> None:
        costs, _ = vv.load_costs()
        tasks = vv.CONTRACT["tasks"]
        median = sorted(costs.values())[len(costs) // 2]
        cost = {t["id"]: costs.get(t["id"], median) for t in tasks}
        for n in range(2, 9):
            totals = [sum(cost[t["id"]] for t in vv.partition(tasks, i, n, costs)) for i in range(n)]
            self.assertLessEqual(max(totals), sum(totals) / n + max(cost.values()) + 1e-9, n)

    def test_a_task_with_no_cost_counts_as_the_median(self) -> None:
        with_median = dict(UNEVEN, T6=4.0)
        for n in (2, 3, 4):
            self.assertEqual([[t["id"] for t in vv.partition(SYNTH["tasks"], i, n, UNEVEN)] for i in range(n)],
                             [[t["id"] for t in vv.partition(SYNTH["tasks"], i, n, with_median)] for i in range(n)], n)

    def test_the_heaviest_task_goes_first_and_the_rest_fill_the_lighter_shards(self) -> None:
        parts = [[t["id"] for t in vv.partition(SYNTH["tasks"], i, 2, UNEVEN)] for i in range(2)]
        self.assertEqual(parts, [["T3"], ["T0", "T1", "T2", "T4", "T5", "T6"]])  # 40 against 1+2+3+5+6+4 = 21

    def test_the_default_reads_the_checkouts_cost_file(self) -> None:
        with mock.patch.object(vv, "COSTS_FILE", costs_file(UNEVEN)):
            self.assertEqual([t["id"] for t in vv.partition(SYNTH["tasks"], 0, 2)], ["T3"])


class CostFallback(unittest.TestCase):
    def test_without_vv_costs_json_the_split_is_task_k_in_shard_k_mod_n(self) -> None:
        with mock.patch.object(vv, "COSTS_FILE", costs_file(None)):
            self.assertEqual(vv.load_costs(), (None, None))
            for n in range(1, 9):
                for i in range(n):
                    self.assertEqual([t["id"] for t in vv.partition(vv.CONTRACT["tasks"], i, n)],
                                     [t["id"] for k, t in enumerate(vv.CONTRACT["tasks"]) if k % n == i], (i, n))


class Costs(unittest.TestCase):
    def receipts(self, rows: list[list[tuple[str, float]]]) -> str:
        d = tempfile.mkdtemp()
        for k, tasks in enumerate(rows):
            doc = {"receipt": {"tasks": [{"task": t, "seconds": s} for t, s in tasks]}, "report": []}
            with open(os.path.join(d, f"vv-{k}.json"), "w", encoding="utf-8") as f:
                json.dump(doc, f)
        return d

    def test_the_cost_is_the_median_seconds_per_task_rounded_to_a_tenth(self) -> None:
        d = self.receipts([[("A", 10.0), ("B", 1.0)], [("A", 60.0), ("B", 100.0)], [("A", 20.0), ("B", 3.0)],
                           [("B", 8.04)]])
        doc = vv.costs_from_receipts(sorted(os.path.join(d, f) for f in os.listdir(d)), ["9", "8"])
        # A: 10, 20, 60 -> 20 (the mean would be 30); B: 1, 3, 8.04, 100 -> (3 + 8.04) / 2 = 5.52 -> 5.5 (mean 28)
        self.assertEqual(doc["seconds"], {"A": 20.0, "B": 5.5})
        self.assertEqual(doc["source_runs"], ["8", "9"])

    def test_the_same_receipts_write_the_same_bytes_and_name_the_runs(self) -> None:
        d = self.receipts([[("A", 1.0)], [("A", 3.0), ("B", 2.0)]])
        outs = []
        for _ in range(2):
            out = os.path.join(tempfile.mkdtemp(), "costs.json")
            self.assertEqual(run_main("costs", d, "--run", "42", "--run", "7", "--out", out)[0], 0)
            with open(out, "rb") as f:
                outs.append(f.read())
        self.assertEqual(outs[0], outs[1])
        self.assertEqual(json.loads(outs[0])["source_runs"], ["42", "7"])
        self.assertEqual(sorted(json.loads(outs[0])), ["seconds", "source_runs", "v"])  # no timestamp

    def test_a_receipt_without_per_task_seconds_is_refused(self) -> None:
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "vv-0.json"), "w", encoding="utf-8") as f:
            json.dump({"receipt": {"tasks": [{"task": "A", "state": "open"}]}, "report": []}, f)
        rc, out = run_main("costs", d, "--out", os.path.join(d, "costs.json"))
        self.assertEqual(rc, 2)
        self.assertIn("no per-task seconds", out)
        self.assertFalse(os.path.exists(os.path.join(d, "costs.json")))

    def test_predict_reads_the_shard_count_from_ci_yml(self) -> None:
        rc, out = run_main("costs", "--predict")
        self.assertEqual(rc, 0)
        got = json.loads(out)
        self.assertEqual(got["shards"], vv.ci_shard_count())
        self.assertEqual(got["max_shard_minutes"], max(got["shard_minutes"]))


class CostFailsClosed(unittest.TestCase):
    def setUp(self) -> None:
        self.patch = mock.patch.object(vv, "COSTS_FILE", costs_file(UNEVEN))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def merge(self, docs: list[dict]) -> list[str]:
        return vv.merge_receipts(write_set(docs), SYNTH)[2]

    def test_a_complete_cost_split_set_merges(self) -> None:
        self.assertEqual(self.merge([shard_receipt(SYNTH, i, 3) for i in range(3)]), [])

    def test_shards_that_disagree_on_the_split_fail(self) -> None:
        docs = [shard_receipt(SYNTH, i, 3) for i in range(3)]
        docs[1] = shard_receipt(SYNTH, 1, 3, partition="position")
        self.assertIn("the shards disagree on partition", self.merge(docs))

    def test_shards_that_disagree_on_the_costs_hash_fail(self) -> None:
        docs = [shard_receipt(SYNTH, i, 3) for i in range(3)]
        docs[2] = shard_receipt(SYNTH, 2, 3, costs_sha256="0" * 64)
        self.assertIn("the shards disagree on costs_sha256", self.merge(docs))

    def test_a_costs_hash_that_is_not_the_checkouts_file_fails(self) -> None:
        docs = [shard_receipt(SYNTH, i, 3, costs_sha256="0" * 64) for i in range(3)]
        self.assertIn("the shards split by a different vv/costs.json from the one checked out here", self.merge(docs))

    def test_a_shard_whose_tasks_are_not_its_cost_partition_fails(self) -> None:
        docs = [shard_receipt(SYNTH, i, 2) for i in range(2)]
        pos = [t["id"] for k, t in enumerate(SYNTH["tasks"]) if k % 2 == 0]  # the position split's shard 0
        docs[0] = shard_receipt(SYNTH, 0, 2, assigned=pos)
        self.assertIn("shard 0/2 did not verify exactly its partition", self.merge(docs))


class CostEquivalence(unittest.TestCase):
    def test_sharded_by_cost_and_merged_equals_one_run_for_n_2_3_and_6(self) -> None:
        eq = Equivalence()
        with mock.patch.object(vv, "CONTRACT", SYNTH), mock.patch.object(vv, "load_claims", lambda: ["T3"]), \
                mock.patch.object(vv, "signature", lambda: (0, {"status": "signed: test"})), \
                mock.patch.object(vv, "COSTS_FILE", costs_file(UNEVEN)):
            single = eq.run_json()
            for n in (2, 3, 6):
                d = tempfile.mkdtemp()
                for i in range(n):
                    run_main("verify", "--shard", f"{i}/{n}", "--receipts", d)
                paths = sorted(os.path.join(d, f) for f in os.listdir(d))
                docs = []
                for p in paths:
                    with open(p, encoding="utf-8") as f:
                        docs.append(json.load(f))
                self.assertEqual({doc["receipt"]["partition"] for doc in docs}, {"cost"}, n)
                receipt, report, problems = vv.merge_receipts(paths, SYNTH)
                self.assertEqual(eq.states(report), eq.states(single["report"]), n)
                self.assertEqual(receipt["claimed_failed"], ["T3"], n)
                t3 = [i for i in range(n) if "T3" in [t["id"] for t in vv.partition(SYNTH["tasks"], i, n)]][0]
                self.assertEqual(problems, [f"shard {t3}/{n} failed"], n)  # T3 is claimed and fails
