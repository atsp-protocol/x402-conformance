"""Regenerate the check table in docs/COVERAGE.md from CATALOG in src/x402conf/spec.py.

The page keeps its hand-written sections (networks, transports, stacks, facilitators, Lean models, what is not covered);
only the block between the two marker comments is generated: the check count by family and profile and one row per check
with its profile, basis, where it runs and how many controls and faulty builds it has.

Usage: python3 tools/build_coverage.py                 rewrites the generated block
       python3 tools/build_coverage.py --check         exits 1 if the block differs from what it would write
       python3 tools/build_coverage.py --root DIR ...  works on another checkout (the tests use a copy)

tests/test_coverage_doc.py runs the check in CI and shows that it fails on a stale page."""

from __future__ import annotations

import importlib
import os
import re
import sys

BEGIN = "<!-- generated from src/x402conf/spec.py by tools/build_coverage.py; edit RUNS there, not this block -->"
END = "<!-- end generated -->"

FAMILY = {
    "S": "Facilitator, `GET /supported` (S0 to S4 live; S5 offline)",
    "P": "Any paid URL's 402 answer, one unpaid GET",
    "W": "Sign-in-with-x on a paid route, behind the facilitator double",
    "F": "Facilitator safety, against doubles offline and on devnet",
    "D": "A facilitator's discovery API (Bazaar), GET only",
    "G": "An A2A agent's paid skill, against the HTTP route it mirrors",
    "R": "Resource server behind the facilitator double",
    "C": "Client, through a recording proxy",
    "U": "The upto scheme on a paid route, behind the scheme double",
    "B": "The batch-settlement scheme on a paid route and its redemption runs, behind the scheme double",
    "X": "Paid MCP tools, over the MCP transport (JSON-RPC over Streamable HTTP)",
}
# Where each check runs: the CLIs, the Action, the library exports and the harness (reviewed 2026-10-23).
RUNS: dict[str, str] = {}
for _i in ("S0", "S1", "S2", "S3", "S4"):
    RUNS[_i] = "`x402conf live`, Action `facilitators`"
RUNS["S5"] = "`x402conf offline` (needs `supported()` on the facilitator)"
RUNS["D1"] = "library only: `checkDiscovery` from `x402-conformance-svm` (GET only)"
RUNS["G1"] = "library only: `checkA2aMirrorsHttp` from `x402-conformance-svm`"
for _i in ("P1", "P2", "P3", "P4", "P5", "P6", "P7"):
    RUNS[_i] = ("`x402conf resource`, `x402conf-svm resource`, Action `resources`, pytest `check_payment_required`, "
                "MCP `x402_check_payment_required`")
for _i in ("F1", "F2", "F3", "F4", "F5", "F6"):
    RUNS[_i] = "`x402conf offline`, `x402conf devnet` (real `/verify` and `/settle` on Solana devnet)"
for _i in ("F7", "F8", "F9", "F10", "F11", "F12", "F13", "F14"):
    RUNS[_i] = "`x402conf offline`"
for _i in ("R0", "R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10"):
    RUNS[_i] = "`x402conf-svm probe`, Action `resource-url`, `runConformance`, pytest `probe`, MCP `x402_probe_resource_server`"
for _i in ("R11", "R11a", "R11b", "R11c", "R11d", "R11e", "R11f"):
    RUNS[_i] = "`x402conf-svm probe` with the binding flags, Action `binding-*`"
RUNS["R14"] = "`x402conf-svm probe --crash`, Action `crash`"
for _i in ("W1", "W2", "W3"):
    RUNS[_i] = "library only: `probeSiwx` from `x402-conformance-svm`"
for _i in ("R20", "R20a", "R20b"):
    RUNS[_i] = "`x402conf-svm probe --retry`, Action `retry`; `checkClientRetry` for clients"
LIB = {"R12": "probeParallel", "R13": "probeReplicas", "R15": "probeDelivery", "R16": "probeHead", "R16a": "probeUnpaidHead",
       "R17": "probeCacheLeak", "R18": "probePending", "R19": "probeFlows", "R21": "probePreempt",
       "R22": "probeStatus", "R23": "probeAbort", "R24": "probeMalformedHeader", "C1": "checkClientHandles402",
       "C2": "checkClientOfferPolicy", "C3": "checkClientKeepsV2", "X1": "checkMcpPaymentRequired",
       "X2": "probeMcpTransport"}
for _i, _fn in LIB.items():
    RUNS[_i] = f"library only: `{_fn}` from `x402-conformance-svm`"
for _i in ("U1", "U2", "U3"):
    RUNS[_i] = "library only: `probeUpto` from `x402-conformance-svm`"
for _i in ("B1", "B2", "B3"):
    RUNS[_i] = "library only: `probeBatch` from `x402-conformance-svm`"
for _i in ("R16a", "R24"):
    RUNS[_i] = f"`x402conf-svm live` (unpaid, paced), and `{LIB[_i]}` from `x402-conformance-svm`"
RUNS["X1"] = "`x402conf-svm mcp` (one unpaid tools/call, paced), and `checkMcpPaymentRequired` from `x402-conformance-svm`"
RUNS["P9"] = "`x402conf resource`, when the 402 carries the bazaar extension"
RUNS["P10"] = "`x402conf resource --well-known`"


def key(i: str) -> tuple[str, int, str]:
    m = re.match(r"([A-Z]+)(\d+)([a-z]?)", i)
    assert m, i
    return (m.group(1), int(m.group(2)), m.group(3))


def cell(s: str) -> str:
    return s.replace("|", "\\|")


def render(root: str) -> str:
    sys.path.insert(0, os.path.join(root, "src"))
    spec = importlib.import_module("x402conf.spec")
    cat = spec.CATALOG
    ids = sorted(cat, key=key)
    rows = []
    for i in ids:
        e = cat[i]
        where = RUNS.get(i, "")
        assert where, f"no run location for {i}: add it to RUNS in tools/build_coverage.py"
        rows.append(f"| {i} | {e['profile']} | {cell(e['basis'])} | {where} | {len(e.get('controls', []))} | "
                    f"{len(e.get('faulty', []))} |")
    fam: dict[str, list[str]] = {}
    for i in ids:
        fam.setdefault(key(i)[0], []).append(i)
    family_lines = "\n".join(f"- **{f}**: {FAMILY[f]}: {', '.join(fam[f])} ({len(fam[f])} checks)"
                             for f in ("S", "P", "F", "D", "R", "G", "C", "W", "U", "B", "X") if f in fam)
    by_profile = {p: [i for i in ids if cat[i]["profile"] == p] for p in ("normative", "security-profile", "resilience")}
    return f"""{BEGIN}

## Checks: {len(ids)} in the catalogue

{family_lines}

By profile: {len(by_profile['normative'])} normative (the spec says MUST), {len(by_profile['security-profile'])} security
profile (a hardening rule the spec leaves open), {len(by_profile['resilience'])} resilience (behaviour under failure).
Every check has at least one control that passes and one faulty build it catches, and CI runs every one of them
(`tests/test_offline.py`, `ts/test/`).

| check | profile | basis | where it runs | controls | faulty builds |
|---|---|---|---|---|---|
{chr(10).join(rows)}

{END}"""


def splice(page: str, block: str) -> str:
    a, b = page.find(BEGIN), page.find(END)
    if a < 0 or b < a:
        raise SystemExit("docs/COVERAGE.md has no generated block: it needs the begin and end marker comments")
    return page[:a] + block + page[b + len(END):]


def main(argv: list[str]) -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if "--root" in argv:
        root = os.path.abspath(argv[argv.index("--root") + 1])
    out = os.path.join(root, "docs", "COVERAGE.md")
    with open(out, encoding="utf-8") as f:
        page = f.read()
    new = splice(page, render(root))
    rows = new.count("\n| ") - new.count("\n|---")
    if "--check" in argv:
        if new != page:
            print("docs/COVERAGE.md is out of date: run python3 tools/build_coverage.py")
            return 1
        print(f"docs/COVERAGE.md is current: {len(importlib.import_module('x402conf.spec').CATALOG)} checks in the block")
        return 0
    with open(out, "w", encoding="utf-8") as f:
        f.write(new)
    print(f"wrote the generated block of docs/COVERAGE.md ({rows} table rows on the page)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
