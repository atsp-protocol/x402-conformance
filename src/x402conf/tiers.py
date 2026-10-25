"""The two tiers of the matrix (XC-98) and the signed attestation of a self-hosted full run.

Tier 1, External-verified: the subset of the catalogue that runs from outside the project's stack against its public
testnet endpoint with no spend. The x402-conformance run queue runs it on each new release (the notify hook or the
weekly release check). That is `x402conf resource --well-known --malformed-header --unpaid-head`: P1 to P7, P9 and P10
from unpaid GETs, R24 from five unpaid GETs with a malformed PAYMENT-SIGNATURE, and R16a from one unpaid HEAD, which is
sent only when the row's operator allowed it (XC-110); without that permission R16a needs the self-hosted run.
Paid checks against a live endpoint are never run by the queue while its spend caps are zero; with the rest of the
catalogue they need the self-hosted run.

Tier 2, Full suite (self-hosted): runs only in the project's own CI through the reusable Action, on each release. With
`attest: true` the Action writes x402-conformance-attestation.json (this module's attestation()): the suite's
repository, ref and version, the project's repository, ref and commit, one entry per catalogue check with its status
and, for a check that does not apply, the reason, and the time. It is signed with GitHub artifact attestations
(Sigstore, the job's OIDC identity) and submitted to the queue, which verifies it and never runs anything
(tools/attestation.py).
"""
from __future__ import annotations

import datetime
import json
import os
import re
from typing import Any, Final

from . import __version__
from . import spec as S

ATTESTATION_FORMAT: Final = "x402-conformance.attestation/1"
ATTESTATION_FILE: Final = "x402-conformance-attestation.json"
TIER1: Final = "external-verified"
TIER2: Final = "full-suite-self-hosted"
TIER_LABEL: Final = {TIER1: "External-verified", TIER2: "Full suite (self-hosted)"}
# What the queue runs from outside, unpaid, paced >= 5 s apart: one GET of the paid URL and one of /.well-known/x402
# (P1-P7, P9, P10), five GETs with a malformed PAYMENT-SIGNATURE (R24) and, with the operator's permission, one HEAD
# (R16a). At most eight requests a run.
EXTERNAL: Final = frozenset({"P1", "P2", "P3", "P4", "P5", "P6", "P7", "P9", "P10", "R16a", "R24"})
# External checks that send something other than a GET, and so run only with the operator's permission.
NEEDS_PERMISSION: Final = {"R16a": "the operator did not allow an unpaid HEAD; the self-hosted run covers it"}
MAX_EXTERNAL_REQUESTS: Final = 8
STATUSES: Final = ("pass", "fail", "warn", "not_applicable", "not_run")
REASON: Final = re.compile(r"^[^<>`|\n\r]{3,200}$")
# An external check the run emits nothing for when the endpoint offers nothing to grade.
EXTERNAL_NA: Final = {"P9": "the 402 carries no bazaar extension", "P10": "the origin serves no /.well-known/x402"}
SELF_TEST: Final = "offline.json"  # the suite's own self-test against its doubles; it checks the suite, not the project


def catalogue() -> list[str]:
    return list(S.CATALOG)


def denominator(results: dict[str, dict[str, Any]], tier: str) -> dict[str, int]:
    """Counts for one row: passed, failed, applicable (= exercised), not applicable, and the checks that need the
    self-hosted run. In tier 1 every catalogue check outside EXTERNAL needs the self-hosted run (which of them apply is
    settled by that run), and so does an external check the run did not reach (R16a without the operator's
    permission); in tier 2 nothing does."""
    ids = catalogue()
    scope = [i for i in ids if i in EXTERNAL] if tier == TIER1 else ids
    st = {i: str((results.get(i) or {}).get("status") or "not_run") for i in scope}
    passed = sum(1 for s in st.values() if s in ("pass", "warn"))
    failed = sum(1 for s in st.values() if s == "fail")
    na = sum(1 for s in st.values() if s == "not_applicable")
    not_run = sum(1 for s in st.values() if s == "not_run")
    return {"passed": passed, "failed": failed, "applicable": passed + failed, "exercised": passed + failed,
            "not_applicable": na, "not_run": not_run,
            "needs_self_hosted": (len(ids) - len(scope) + not_run) if tier == TIER1 else 0, "catalogue": len(ids)}


def results_from_dir(d: str, declared_na: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    """One entry per catalogue check from the Action's results files in d. The suite's offline self-test is left out
    (it grades the suite's doubles, not the project). A check the run did not reach is not_run, unless the project
    declared it not applicable with a reason."""
    from .cli import collect  # the Action's own reader of its results files
    out: dict[str, dict[str, Any]] = {}
    for r in collect(d) if os.path.isdir(d) else []:
        if r.get("source") == SELF_TEST or r["id"] not in S.CATALOG:
            continue
        if r.get("status") == "not_applicable":
            e: dict[str, Any] = {"status": "not_applicable", "reason": _reason(r.get("detail")) or "reported by the probe"}
        elif r["pass"]:
            e = {"status": "pass"}
        else:
            e = {"status": "fail" if r["severity"] == "error" else "warn"}
        prev = out.get(r["id"])
        if prev is None or prev["status"] in ("pass", "not_applicable", "warn") and e["status"] == "fail":
            out[r["id"]] = e
    for cid in catalogue():
        if cid in out:
            continue
        why = (declared_na or {}).get(cid)
        out[cid] = ({"status": "not_applicable", "reason": why, "declared": True} if why
                    else {"status": "not_run", "reason": "not requested in this workflow"})
    return {cid: out[cid] for cid in catalogue()}


def results_from_run(path: str) -> dict[str, dict[str, Any]]:
    """Per-check results of one committed run.json (a resource-402.json, resource-server.json or live.json written by
    the suite), read the way the Action reads its results files."""
    import shutil
    import tempfile
    doc = json.load(open(path, encoding="utf-8"))
    name = ("resource-server.json" if isinstance(doc, dict) and "resource" in doc and "results" in doc
            and not any(isinstance(r, dict) and "checks" in r for r in doc.get("results", [])) else "resource-402.json")
    d = tempfile.mkdtemp()
    try:
        shutil.copyfile(path, os.path.join(d, name))
        return results_from_dir(d)
    finally:
        shutil.rmtree(d, True)


def tier1_results(results: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Tier 1: the external checks only. P9 and P10 have nothing to grade when the endpoint offers no bazaar extension
    or no manifest, and are not applicable then, with that reason."""
    out = {}
    for cid in catalogue():
        if cid not in EXTERNAL:
            continue
        e = dict(results.get(cid) or {"status": "not_run"})
        if e["status"] == "not_run" and cid in EXTERNAL_NA:
            e = {"status": "not_applicable", "reason": EXTERNAL_NA[cid]}
        elif e["status"] == "not_run" and cid in NEEDS_PERMISSION:
            e = {"status": "not_run", "reason": NEEDS_PERMISSION[cid]}
        out[cid] = e
    return out


def _reason(detail: Any) -> str:
    text = detail if isinstance(detail, str) else (detail or {}).get("reason") if isinstance(detail, dict) else ""
    text = re.sub(r"[<>`|\r\n]+", " ", str(text or "")).strip()[:200]
    return text if len(text) >= 3 else ""


def parse_declared(text: str) -> tuple[dict[str, str], list[str]]:
    """The Action's not-applicable input: 'U1: no upto scheme; X1: no MCP tools' (one check id and a reason each)."""
    out, bad = {}, []
    for part in [p.strip() for p in re.split(r"[;\n]", text or "") if p.strip()]:
        m = re.match(r"^([A-Z][0-9]{1,2}[a-z]?)\s*[:=]\s*(.+)$", part)
        if not m or m.group(1) not in S.CATALOG:
            bad.append(f"not-applicable: {part!r} is not '<check id>: <reason>' for a catalogue check")
        elif not REASON.match(m.group(2).strip()):
            bad.append(f"not-applicable: the reason for {m.group(1)} must be 3 to 200 characters, no markup")
        else:
            out[m.group(1)] = m.group(2).strip()
    return out, bad


def attestation(d: str, env: dict[str, str], declared_na: dict[str, str]) -> dict[str, Any]:
    """The document the Action signs. Everything in it is public: no endpoint secrets, no keys, no request bodies."""
    results = results_from_dir(d, declared_na)
    return {
        "schema": ATTESTATION_FORMAT,
        "row": env.get("X402C_ROW", ""),
        "suite": {"repository": env.get("X402C_SUITE_REPOSITORY") or "atsp-protocol/x402-conformance",
                  "ref": env.get("X402C_SUITE_REF", ""), "version": __version__},
        "vendor": {"repository": env.get("GITHUB_REPOSITORY", ""), "ref": env.get("GITHUB_REF_NAME", ""),
                   "ref_type": env.get("GITHUB_REF_TYPE", ""), "commit": env.get("GITHUB_SHA", ""),
                   "workflow_ref": env.get("GITHUB_WORKFLOW_REF", ""), "run_id": env.get("GITHUB_RUN_ID", ""),
                   "run_attempt": env.get("GITHUB_RUN_ATTEMPT", "")},
        "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "results": results,
        "summary": denominator(results, TIER2),
    }


def action_attestation(env: dict[str, str] | None = None) -> int:
    """The Action's attest step: write the attestation next to the results, for actions/attest-build-provenance."""
    e = dict(os.environ if env is None else env)
    d = e.get("X402C_DIR", "x402-conformance")
    declared, bad = parse_declared(e.get("X402C_NOT_APPLICABLE", ""))
    if not re.match(r"^[a-z0-9][a-z0-9._-]{0,79}$", e.get("X402C_ROW", "")):
        bad.append("attest: true needs row: <your row's slug>")
    for b in bad:
        print(f"::error title=x402 Conformance::{b}")
    if bad:
        return 1
    doc = attestation(d, e, declared)
    out = os.path.join(d, "attestation")
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, ATTESTATION_FILE)
    with open(path, "w") as f:
        json.dump(doc, f, indent=1, sort_keys=True)
        f.write("\n")
    s = doc["summary"]
    print(f"x402 Conformance: attestation for {doc['row']}: {s['passed']}/{s['applicable']} applicable checks passed, "
          f"{s['not_applicable']} not applicable, {s['not_run']} not run")
    if e.get("GITHUB_OUTPUT"):
        with open(e["GITHUB_OUTPUT"], "a") as f:
            f.write(f"attestation={path}\n")
    return 0
