"""XC-56: the cross-SDK parity oracle.

    PYTHONPATH=src python3 -m unittest -v tests.test_parity.Report       the report, offline and fast
    PYTHONPATH=src python3 -m unittest -v tests.test_parity.NoNetwork    every harness, with loopback recorders
    PYTHONPATH=src python3 -m unittest -v tests.test_parity.FaultsCaught each fault-injected harness is a divergence

Report checks tools/parity_report.py on small hand-made runs: a complete run validates, and each way a run can be
incomplete, off the pin, online or tampered with is refused. NoNetwork and FaultsCaught run the real harnesses
against the pinned SDK libraries.
"""
import copy
import functools
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from parity_report import (  # noqa: E402
    anchor_problems,
    coverage_problems,
    divergences,
    evidence_problems,
    run_problems,
    vector_problems,
    write_evidence,
)

SDKS = ("ts", "python", "go")

PIN = "6b6ee91fee027b540faabcb25774e73851006c3b"
CHECKS = [{"id": "F1", "anchor": {"spec_file": "specs/x402-specification-v2.md"}}, {"id": "R24", "anchor": None}]
DOC = {"schema": "x402conf.parity-vectors/1", "vectors": [
    {"id": "v-array", "target": "verify", "tags": ["malformed", "F15"], "anchor": "F1", "profile": "normative",
     "input": {"payload": [1, 2]}, "expect": {"isValid": False, "invalidReason": ["invalid_payload"], "threw": False}},
    {"id": "v-header", "target": "paid-route", "tags": ["status-mapping"], "anchor": "R24", "profile": "security-profile",
     "input": {"header": "%%%"}, "expect": {"status": [400, 402], "content_type": "application/json", "threw": False}},
]}


def result(vector: str, sdk: str, **kw: object) -> dict:
    base = {"vector": vector, "sdk": sdk, "status": None, "content_type": None, "isValid": None,
            "invalidReason": None, "threw": False, "error": None}
    return {**base, **kw}


def good_run() -> dict:
    res = []
    for sdk in ("ts", "python"):
        res.append(result("v-array", sdk, isValid=False, invalidReason="invalid_payload"))
        res.append(result("v-header", sdk, status=402, content_type="application/json; charset=utf-8"))
    return {"schema": "x402conf.parity-run/1", "pin": PIN, "offline": True, "fault": None,
            "sdks": {"ts": {"version": "2.28.0"}, "python": {"version": "2.25.0"}},
            "network": {"outbound_connections": 0, "signer_writes": 0, "signer_reads": 3}, "results": res}


class Report(unittest.TestCase):
    def test_a_complete_offline_run_at_the_pin_validates(self) -> None:
        self.assertEqual(run_problems(good_run(), DOC, PIN), [])
        self.assertEqual(divergences(good_run(), DOC), [])

    def test_each_incomplete_or_off_pin_run_is_refused(self) -> None:
        cases = {
            "pin": lambda r: r.update(pin="0" * 40),
            "not offline": lambda r: r.update(offline=False),
            "outbound connections": lambda r: r["network"].update(outbound_connections=1),
            "asked to write": lambda r: r["network"].update(signer_writes=1),
            "expected exactly one": lambda r: r["results"].pop(),
            "threw is not a boolean": lambda r: r["results"][0].update(threw="no"),
            "not a vector or SDK": lambda r: r["results"].append(result("v-other", "ts")),
        }
        for want, spoil in cases.items():
            r = copy.deepcopy(good_run())
            spoil(r)
            got = run_problems(r, DOC, PIN)
            self.assertTrue(any(want in p for p in got), (want, got))

    def test_a_version_off_the_pin_is_refused(self) -> None:
        pins = {"sdks": {"ts": {"version": "2.28.0"}, "python": {"version": "2.24.0"}}}
        self.assertTrue(any("python" in p and "2.24.0" in p for p in run_problems(good_run(), DOC, PIN, pins)))

    def test_a_divergence_from_the_expected_outcome_names_the_vector_and_anchor(self) -> None:
        r = good_run()
        r["results"][0].update(isValid=True, invalidReason=None)
        got = [d for d in divergences(r, DOC) if d["kind"] == "expected"]
        self.assertTrue(got)
        self.assertEqual({(d["vector"], d["anchor"], d["sdk"]) for d in got}, {("v-array", "F1", "ts")})

    def test_sdks_that_disagree_with_each_other_are_a_cross_sdk_divergence(self) -> None:
        r = good_run()
        r["results"][1].update(status=500)
        cross = [d for d in divergences(r, DOC) if d["kind"] == "cross-sdk"]
        self.assertEqual([(d["vector"], d["field"]) for d in cross], [("v-header", "status")])
        self.assertEqual(cross[0]["observed"], {"ts": 500, "python": 402})

    def test_coverage_and_anchors(self) -> None:
        self.assertEqual(vector_problems(DOC), [])
        self.assertEqual(coverage_problems(DOC, ["malformed", "F15", "status-mapping"]), [])
        self.assertEqual(coverage_problems(DOC, ["wildcard-network"]), ["no vector is tagged wildcard-network"])
        self.assertEqual(anchor_problems(DOC, CHECKS), [])
        bad = copy.deepcopy(DOC)
        bad["vectors"][0]["anchor"] = "R24"  # a check with no spec anchor, on a vector not labelled security-profile
        self.assertEqual(len(anchor_problems(bad, CHECKS)), 1)

    def test_evidence_round_trips_and_a_changed_byte_is_caught(self) -> None:
        d = tempfile.mkdtemp()
        out = write_evidence(good_run(), DOC, d)
        self.assertEqual(os.path.basename(out), PIN)
        self.assertEqual(evidence_problems(d, DOC), [])
        p = os.path.join(out, "run.json")
        with open(p, encoding="utf-8") as f:
            doc = json.load(f)
        doc["results"][0]["isValid"] = True
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps(doc, indent=1, sort_keys=True) + "\n")
        self.assertTrue(any("hash does not match" in x for x in evidence_problems(d, DOC)))


def vectors() -> dict:
    with open(os.path.join(ROOT, "docs", "parity", "vectors.json"), encoding="utf-8") as f:
        return json.load(f)


@functools.cache
def real_run(fault: str = "", probe: bool = False) -> str:
    """One x402conf parity run against the three pinned libraries; the path of its run file."""
    out = os.path.join(tempfile.mkdtemp(), "run.json")
    with open(os.path.join(ROOT, "docs", "parity", "pin"), encoding="utf-8") as f:
        pin = f.read().strip()
    cmd = [sys.executable, "-m", "x402conf", "parity", "--sdk", ",".join(SDKS), "--upstream-pin", pin, "--offline",
           "--out", out] + (["--fault", fault] if fault else []) + (["--probe-outbound"] if probe else [])
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src"))
    p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=900)
    if p.returncode:
        raise AssertionError(f"x402conf parity exited {p.returncode}: {p.stderr[-1500:]}")
    return out


def load_run(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def outcomes(run: dict) -> dict:
    return {(r["vector"], r["sdk"]): {k: r[k] for k in ("status", "content_type", "isValid", "invalidReason", "threw")}
            for r in run["results"]}


class NoNetwork(unittest.TestCase):
    """Each harness drives only library entry points, and nothing leaves the box."""

    def test_a_run_opens_no_connection_off_loopback_and_asks_the_signer_for_no_write(self) -> None:
        run = load_run(real_run())
        self.assertEqual(sorted(run["sdks"]), sorted(SDKS))
        for sdk, meta in run["sdks"].items():
            self.assertEqual(meta["outbound_attempts"], 0, sdk)
            self.assertEqual(meta["signer_writes"], 0, sdk)
        self.assertEqual(run_problems(run, vectors(), run["pin"]), [])

    def test_the_only_service_contacted_is_the_loopback_double_and_never_for_verify_or_settle(self) -> None:
        calls = load_run(real_run())["network"]["facilitator_double_calls"]
        self.assertTrue(set(calls) <= {"/supported"}, calls)

    def test_each_guard_counts_and_refuses_a_probe_off_loopback(self) -> None:
        run = load_run(real_run(probe=True))
        for sdk, meta in run["sdks"].items():
            self.assertEqual(meta["outbound_attempts"], 1, sdk)
        self.assertTrue(any("outbound connections recorded" in p for p in run_problems(run, vectors(), run["pin"])))


# The vectors each fault's path covers.
FAULT_PATHS = {
    "status": lambda v: v["target"] == "paid-route",
    "swallow-reason": lambda v: v["target"] == "verify",
    "wildcard-network": lambda v: bool({"wildcard-network", "unregistered-network"} & set(v["tags"])),
}


class FaultsCaught(unittest.TestCase):
    """A fault on one path is reported as a divergence, with its vector id and anchor, for every SDK."""

    def path(self, fault: str) -> set:
        return {v["id"] for v in vectors()["vectors"] if FAULT_PATHS[fault](v)}

    def test_each_fault_is_reported_for_every_sdk_with_vector_and_anchor(self) -> None:
        # Only divergences the control run does not have count: the stock libraries already diverge on some of these
        # vectors, and a fault that changed nothing must not pass. The Python library already matches the eip155
        # family from one registration, so its wildcard fault changes nothing; the next test asserts exactly that.
        doc = vectors()
        key = functools.partial(json.dumps, sort_keys=True)
        base = {key(d) for d in divergences(load_run(real_run()), doc)}
        for fault in FAULT_PATHS:
            ds = [d for d in divergences(load_run(real_run(fault)), doc)
                  if d["vector"] in self.path(fault) and key(d) not in base]
            for sdk in SDKS:
                if fault == "wildcard-network" and sdk == "python":
                    continue
                mine = [d for d in ds if d.get("sdk") == sdk or (d["kind"] == "cross-sdk" and sdk in d["observed"])]
                self.assertTrue(mine, (fault, sdk))
                self.assertTrue(all(d["vector"] and d["anchor"] for d in mine), (fault, sdk))

    def test_status_and_swallow_reason_change_every_sdk_on_their_path_only(self) -> None:
        base = outcomes(load_run(real_run()))
        for fault in ("status", "swallow-reason"):
            got, path = outcomes(load_run(real_run(fault))), self.path(fault)
            for sdk in SDKS:
                changed = {v for (v, s), o in got.items() if s == sdk and o != base[(v, s)]}
                self.assertTrue(changed, (fault, sdk))
                self.assertTrue(changed <= path, (fault, sdk, changed - path))

    def test_wildcard_registration_changes_ts_and_go_and_python_already_matches_the_family(self) -> None:
        # Registering two eip155 networks makes the TypeScript and Go libraries derive eip155:*. The Python library
        # derives it from a single registration (public: x402-foundation/x402#3936), so its fault run equals its
        # control run, and its control already lets an unregistered eip155 testnet past routing.
        base, got = outcomes(load_run(real_run())), outcomes(load_run(real_run("wildcard-network")))
        path = self.path("wildcard-network")
        for sdk in ("ts", "go"):
            changed = {v for (v, s), o in got.items() if s == sdk and o != base[(v, s)]}
            self.assertIn("verify-unregistered-network", changed, sdk)
            self.assertTrue(changed <= path, (sdk, changed - path))
        self.assertEqual({k: o for k, o in got.items() if k[1] == "python"},
                         {k: o for k, o in base.items() if k[1] == "python"})
        py = base[("verify-unregistered-network", "python")]
        self.assertFalse(py["threw"])
        self.assertNotIn(py["invalidReason"], ("invalid_network", "unsupported_scheme"))


if __name__ == "__main__":
    unittest.main()
