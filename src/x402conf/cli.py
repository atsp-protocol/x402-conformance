"""Command line.

    x402conf live <facilitator-base-url> ... [--evidence DIR] [--fail-on-error]   S0-S4, GET /supported only
    x402conf resource <paid-url> ... [--fail-on-error]                            P1-P5, one unpaid GET per URL
    x402conf offline                                                F1-F9 against the reference and faulty doubles
    x402conf devnet [--faults] [--evidence DIR] ...                  F1-F6 over real /verify and /settle on Solana devnet
    x402conf report [--dir DIR] [--sarif FILE] [--junit FILE] [--fail-on-error]   SARIF 2.1.0 and JUnit XML

Exit codes: 0 done (and, with --fail-on-error, no error-severity check failed); 1 an error-severity check failed
(offline always; live, resource and report only with --fail-on-error); 2 usage or configuration error, or report found
no results JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from typing import Any
from xml.sax.saxutils import quoteattr

from . import __version__
from . import harness as H
from . import mock as M

DOCS = "https://github.com/atsp-protocol/x402-conformance/blob/main/docs/"


def collect(d: str) -> list[dict[str, Any]]:
    """One row per check from live.json, resource-server.json and offline.json in d, the files the Action writes.

    Offline rows cover the reference double only, plus one row saying whether every fault-injected double was caught:
    a fault-injected double failing its target check is the expected result, not a finding."""
    rows: list[dict[str, Any]] = []

    def load(name: str) -> Any:
        p = os.path.join(d, name)
        if not os.path.exists(p):
            return None
        with open(p) as f:
            return json.load(f)

    def row(target: str, check: str, ok: bool, severity: str, detail: Any, source: str) -> None:
        rows.append({"id": check.split()[0], "target": target, "check": check, "pass": bool(ok),
                     "severity": severity, "detail": detail, "source": source})

    for name in ("live.json", "resource-402.json"):
        for r in (load(name) or {}).get("results", []):
            checks = r.get("checks", [])
            if r.get("error") and not checks:  # results written before 1.3.0 carried the error without an S0 check
                row(r["target"], H.S0, False, "error", r["error"], name)
            for c in checks:
                row(r["target"], c["check"], c["pass"], c.get("severity", "error"), c.get("detail"), name)
    rsv = load("resource-server.json")
    if rsv is not None:
        if rsv.get("error"):
            row(rsv.get("resource", "resource server"), "RX the probe ran to completion", False, "error",
                {"error": rsv["error"]}, "resource-server.json")
        for c in rsv.get("results", []):
            detail = c.get("detail")
            if c.get("status") == "unsupported":
                detail = {"status": "unsupported", "detail": detail}
            row(rsv["resource"], c["check"], c["pass"], "error", detail, "resource-server.json")
    off = load("offline.json")
    if off is not None:
        res = off["results"]
        for c in res["reference"]:
            row("reference double", c["check"], c["pass"], c.get("severity", "error"), c.get("detail"), "offline.json")
        missed = [k for k, v in res.items() if k != "reference" and all(c["pass"] for c in v)]
        row("fault-injected doubles", "FX every fault-injected double is caught by at least one check", not missed,
            "error", {"uncaught": missed}, "offline.json")
    return rows


def anchor(check_id: str) -> str:
    return DOCS + "FIXES.md#" + check_id.lower()


def sarif(rows: list[dict[str, Any]], results_dir: str) -> dict[str, Any]:
    """SARIF 2.1.0 for GitHub code scanning: one rule per check id, one result per failed check.

    A result points at the results file it came from, because a failed x402 check is a property of a running service,
    not of a line of source code."""
    rules: dict[str, dict[str, Any]] = {}
    for r in rows:
        rules.setdefault(r["id"], {
            "id": r["id"], "name": "x402" + r["id"],
            "shortDescription": {"text": r["check"][len(r["id"]):].strip() or r["id"]},
            "helpUri": anchor(r["id"]),
            "help": {"text": f"What failed and how to fix it: {anchor(r['id'])}"},
            "properties": {"tags": ["x402", "payments", "security"]},
        })
    ids = sorted(rules)
    results = []
    for r in rows:
        if r["pass"]:
            continue
        key = hashlib.sha256(f"{r['target']}|{r['id']}".encode()).hexdigest()
        detail = json.dumps(r["detail"], sort_keys=True)[:500]
        results.append({
            "ruleId": r["id"], "ruleIndex": ids.index(r["id"]),
            "level": {"error": "error", "warning": "warning"}.get(r["severity"], "note"),
            "message": {"text": f"{r['target']}: {r['check']} failed. Detail: {detail}. Fix: {anchor(r['id'])}"},
            "locations": [{"physicalLocation": {"artifactLocation": {
                "uri": os.path.join(results_dir, r["source"]).replace(os.sep, "/")}}}],
            "partialFingerprints": {"x402ConformanceCheck/v1": key},
        })
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json", "version": "2.1.0",
        "runs": [{"tool": {"driver": {"name": "x402-conformance", "version": __version__,
                                      "informationUri": "https://github.com/atsp-protocol/x402-conformance",
                                      "rules": [rules[i] for i in ids]}},
                  "results": results}],
    }


def junit(rows: list[dict[str, Any]]) -> str:
    """JUnit XML: one test suite per target, one test case per check. Warning and info failures are reported as skipped."""
    suites: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        suites.setdefault(r["target"], []).append(r)
    fails = sum(1 for r in rows if not r["pass"] and r["severity"] == "error")
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<testsuites name="x402-conformance" tests="{len(rows)}" failures="{fails}">']
    for target, rs in suites.items():
        nf = sum(1 for r in rs if not r["pass"] and r["severity"] == "error")
        ns = sum(1 for r in rs if not r["pass"] and r["severity"] != "error")
        out.append(f'  <testsuite name={quoteattr(target)} tests="{len(rs)}" failures="{nf}" skipped="{ns}">')
        for r in rs:
            case = f'    <testcase classname={quoteattr("x402." + r["id"])} name={quoteattr(r["check"])}'
            if r["pass"]:
                out.append(case + "/>")
                continue
            msg = quoteattr(f"{r['id']} failed; how to fix it: {anchor(r['id'])}")
            body = json.dumps(r["detail"], sort_keys=True)[:2000]
            body = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            tag = "failure" if r["severity"] == "error" else "skipped"
            out += [case + ">", f"      <{tag} message={msg}>{body}</{tag}>", "    </testcase>"]
        out.append("  </testsuite>")
    out.append("</testsuites>")
    return "\n".join(out) + "\n"


def report(a: argparse.Namespace) -> int:
    rows = collect(a.dir)
    if not rows:
        print(f"no results JSON found in {a.dir}", file=sys.stderr)
        return 2
    if a.sarif:
        with open(a.sarif, "w") as f:
            json.dump(sarif(rows, a.dir), f, indent=1)
            f.write("\n")
    if a.junit:
        with open(a.junit, "w") as f:
            f.write(junit(rows))
    bad = [r for r in rows if not r["pass"] and r["severity"] == "error"]
    print(json.dumps({"checks": len(rows), "failed": len(bad), "failed_ids": sorted({r["id"] for r in bad})}))
    return 1 if bad and a.fail_on_error else 0


def failed_errors(runs: list[dict[str, Any]]) -> bool:
    return any(not c["pass"] and c.get("severity", "error") == "error" for r in runs for c in r.get("checks", []))


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="x402conf", description="Experimental conformance and safety checks for x402.",
                                 epilog="Exit codes: 0 done; 1 an error-severity check failed (offline always; live, "
                                        "resource and report with --fail-on-error); 2 usage or configuration error. "
                                        "Docs: https://github.com/atsp-protocol/x402-conformance")
    ap.add_argument("--version", action="version", version=f"x402conf {__version__}")
    sub = ap.add_subparsers(dest="mode", required=True, metavar="{live,resource,offline,report,devnet}")
    fe = "exit 1 when an error-severity check fails (default: exit 0 and read the pass fields)"
    lv = sub.add_parser("live", help="S0-S4 over a facilitator's GET /supported; never signs, pays or POSTs",
                        description="S0-S4 over GET /supported. Optional credentials come from the environment only: "
                                    f"{H.AUTH_ENV} is sent as the Authorization header to the host named in "
                                    f"{H.AUTH_HOST_ENV} and to no other host, and is never printed.")
    lv.add_argument("targets", nargs="+", metavar="FACILITATOR_URL")
    lv.add_argument("--evidence", help="directory for raw bodies, run.json and SHA256SUMS")
    lv.add_argument("--fail-on-error", action="store_true", help=fe)
    rs = sub.add_parser("resource", help="P1-P5 over one unpaid GET of a paid URL: the 402 answer and its PaymentRequired",
                        description="P1-P5: one unpaid GET per URL, any network, V1 or V2. Never pays or POSTs.")
    rs.add_argument("targets", nargs="+", metavar="PAID_URL")
    rs.add_argument("--fail-on-error", action="store_true", help=fe)
    sub.add_parser("offline", help="F1-F9 against the built-in reference and fault-injected facilitator doubles",
                   description="Self-test of the suite: F1-F9 against in-process doubles. Exits 1 unless the reference "
                               "passes and every fault-injected double is caught. It does not test your code.")
    rp = sub.add_parser("report", help="convert results JSON in a directory to SARIF 2.1.0 and JUnit XML",
                        description="Convert live.json, resource-402.json, resource-server.json and offline.json to "
                                    "SARIF or JUnit")
    rp.add_argument("--dir", default="x402-conformance", help="directory holding the results JSON files")
    rp.add_argument("--sarif", help="write SARIF 2.1.0 here (for GitHub code scanning)")
    rp.add_argument("--junit", help="write JUnit XML here (for test-report viewers)")
    rp.add_argument("--fail-on-error", action="store_true", help=fe)
    sub.add_parser("devnet", help="F1-F6 over real /verify and /settle on Solana devnet (self-hosted reference)",
                   add_help=False)
    return ap


def action_summary(env: dict[str, str] | None = None) -> int:
    """The GitHub Action's last step: job summary, `result` output and exit status. Fail-closed: a run the caller asked
    for that left no results file (a crash, a build failure, a taken port) is a failure, never a silent pass."""
    e = dict(os.environ if env is None else env)
    d = e.get("X402C_DIR", "x402-conformance")
    want = {name: e.get(var) == "true" for name, var in (("live.json", "X402C_WANT_LIVE"),
                                                          ("resource-402.json", "X402C_WANT_402"),
                                                          ("resource-server.json", "X402C_WANT_PROBE"),
                                                          ("offline.json", "X402C_WANT_OFFLINE"))}
    bad: list[str] = []
    for name, wanted in want.items():
        if wanted and not os.path.exists(os.path.join(d, name)):
            bad.append(f"{name}: the requested run produced no results (it crashed or could not start); see the step log")
    rows = collect(d) if os.path.isdir(d) else []
    unsupported = False
    for r in rows:
        if r["pass"] or r["severity"] != "error":
            continue
        if isinstance(r["detail"], dict) and r["detail"].get("status") == "unsupported":
            unsupported = True
            bad.append(f"{r['target']}: unsupported, the probe can grade only Solana devnet or Base Sepolia exact routes")
        elif r["id"] == "RX" and isinstance(r["detail"], dict):
            bad.append(f"{r['target']}: the probe did not complete: {r['detail'].get('error')}")
        else:
            bad.append(f"{r['target']}: {r['check']}")
    rsv = os.path.join(d, "resource-server.json")
    if want["resource-server.json"] and os.path.exists(rsv):
        with open(rsv) as f:
            doc = json.load(f)
        n = len(doc.get("results", []))
        if not doc.get("error") and not unsupported and n < 11 and all(c["pass"] for c in doc.get("results", [])):
            bad.append(f"{doc.get('resource')}: the probe stopped after {n} checks")
    if not any(want.values()):
        bad.append("nothing to check: set facilitators, resources, resource-url or offline")
    result = "pass" if not bad else ("unsupported" if unsupported and len(bad) == 1 else "fail")
    out = [f"## x402 Conformance: {result}", "", "| target | check | result |", "|---|---|---|"]
    for r in rows:
        mark = "pass" if r["pass"] else ("FAIL" if r["severity"] == "error" else r["severity"])
        target = "suite self-test (" + r["target"] + ")" if r["source"] == "offline.json" else r["target"]
        out.append(f"| {target} | {r['check']} | {mark} |")
    out += [""] + [f"- {b}" for b in bad if b.endswith("see the step log") or b.startswith("nothing")]
    out += ["", "How to fix a failed check: " + DOCS + "FIXES.md", "",
            "Checks map to spec text; they are not a certification of x402 conformance. "
            "Docs: https://github.com/atsp-protocol/x402-conformance"]
    if e.get("GITHUB_STEP_SUMMARY"):
        with open(e["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write("\n".join(out) + "\n")
    if e.get("GITHUB_OUTPUT"):
        with open(e["GITHUB_OUTPUT"], "a") as f:
            f.write(f"result={result}\n")
    for b in bad:
        print(f"::error title=x402 Conformance::{b}")
    return 1 if bad and e.get("X402C_FAIL", "true") == "true" else 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["--"]:  # `pipx run ... x402conf -- --version` passes the separator through
        args = args[1:]
    if args[:1] == ["devnet"]:
        from .devnet import runner

        return runner.main(args[1:])
    a = parser().parse_args(args)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if a.mode == "report":
        return report(a)
    if a.mode == "resource":
        rruns = [H.run_resource(t) for t in a.targets]
        print(json.dumps({"tool": f"x402-conformance {__version__}", "run_at": stamp, "mode": "resource-GET-only",
                          "results": rruns}, indent=1, sort_keys=True))
        return 1 if a.fail_on_error and failed_errors(rruns) else 0
    if a.mode == "live":
        try:
            runs = [H.run_live(t) for t in a.targets]
        except H.UsageError as e:
            print(f"x402conf live: {e}", file=sys.stderr)
            return 2
        sums = []
        for r in runs:
            raw = r.pop("raw", None)
            if raw is not None:
                r["body_sha256"] = hashlib.sha256(raw).hexdigest()
                if a.evidence:
                    os.makedirs(a.evidence, exist_ok=True)
                    name = "supported-" + r["target"].split("//", 1)[-1].replace("/", "_") + ".json"
                    with open(os.path.join(a.evidence, name), "wb") as fb:
                        fb.write(raw)
                    sums.append(f"{r['body_sha256']}  {name}")
        out = {"tool": f"x402-conformance {__version__}", "run_at": stamp, "mode": "live-GET-only", "results": runs}
        text = json.dumps(out, indent=1, sort_keys=True)
        if a.evidence:
            os.makedirs(a.evidence, exist_ok=True)
            with open(os.path.join(a.evidence, "run.json"), "w") as f:
                f.write(text + "\n")
            sums.append(hashlib.sha256((text + "\n").encode()).hexdigest() + "  run.json")
            with open(os.path.join(a.evidence, "SHA256SUMS"), "w") as f:
                f.write("\n".join(sorted(sums, key=lambda s: s.split("  ")[1])) + "\n")
        print(text)
        return 1 if a.fail_on_error and failed_errors(runs) else 0
    res = {k: H.check_safety(f(), M.vectors()) for k, f in M.FAULTS.items()}
    res.update({k: H.check_safety(M.Reference(), M.vectors(), guard=g) for k, g in H.GUARD_FAULTS.items()})
    print(json.dumps({"tool": f"x402-conformance {__version__}", "run_at": stamp, "mode": "offline", "results": res},
                     indent=1))
    ref_ok = all(r["pass"] for r in res["reference"])
    caught = all(any(not r["pass"] for r in v) for k, v in res.items() if k != "reference")
    return 0 if ref_ok and caught else 1


if __name__ == "__main__":
    sys.exit(main())
