#!/usr/bin/env python3
"""The mutation matrix: for every check in the catalogue, which faulty builds it is proven to catch.

    python3 tools/mutation_matrix.py --write [--root DIR]    build docs/site/mutation-matrix.json
    python3 tools/mutation_matrix.py --check [--root DIR]    fail when the committed file is stale, or a check catches no
                                                             faulty build
    python3 tools/mutation_matrix.py [--root DIR]            print the matrix as text

Each `faulty` reference in spec.CATALOG is resolved the way the credibility test in tests/test_offline.py resolves it:
  fault:<name>   a facilitator double in mock.FAULTS, run through harness.check_safety: caught when the check fails
  guard:<name>   a resource-server guard in harness.GUARD_FAULTS, the same way
  py:<test>      a Python test that proves the catch, run here: caught when it passes
  ts:<title>     a TypeScript test that proves the catch: caught when a test with that title exists under ts/test/. The
                 TypeScript tests run in CI's ts job, not here, so the matrix records the test that proves it.
The file carries no timestamp, so two builds of the same tree are byte-identical and --check can compare them.
"""
from __future__ import annotations

import hashlib
import importlib
import io
import json
import os
import sys
import unittest
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join("docs", "site", "mutation-matrix.json")
SCHEMA = "x402-conformance.mutation-matrix/1"


def _load(root: str) -> Any:
    for p in (root, os.path.join(root, "src")):
        if p not in sys.path:
            sys.path.insert(0, p)
    for m in ("x402conf.spec", "x402conf.harness", "x402conf.mock"):
        importlib.import_module(m)
    return importlib.import_module("x402conf.spec")


def _fails(results: list[dict[str, Any]]) -> set[str]:
    return {r["check"].split()[0] for r in results if not r["pass"]}


def ts_titles(root: str) -> str:
    d = os.path.join(root, "ts", "test")
    out = []
    for n in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if n.endswith(".ts"):
            with open(os.path.join(d, n), encoding="utf-8") as f:
                out.append(f.read())
    return "".join(out)


def resolve(cid: str, ref: str, root: str, ts: str) -> dict[str, Any]:
    """One faulty reference: whether the check is proven to catch it, and how."""
    H = importlib.import_module("x402conf.harness")
    M = importlib.import_module("x402conf.mock")
    kind, _, name = str(ref).partition(":")
    row: dict[str, Any] = {"ref": ref, "kind": kind}
    if kind == "fault":
        if name not in M.FAULTS:
            return {**row, "caught": False, "how": f"no double named {name} in mock.FAULTS"}
        caught = cid in _fails(H.check_safety(M.FAULTS[name](), M.vectors()))
        return {**row, "caught": caught,
                "how": f"the {name} double, through check_safety: {cid} {'fails' if caught else 'passes'}"}
    if kind == "guard":
        if name not in H.GUARD_FAULTS:
            return {**row, "caught": False, "how": f"no guard named {name} in harness.GUARD_FAULTS"}
        caught = cid in _fails(H.check_safety(M.Reference(), M.vectors(), guard=H.GUARD_FAULTS[name]))
        return {**row, "caught": caught,
                "how": f"the {name} guard, through check_safety: {cid} {'fails' if caught else 'passes'}"}
    if kind == "py":
        suite = unittest.TestLoader().loadTestsFromName(name)
        res = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
        caught = res.testsRun == 1 and res.wasSuccessful() and not res.skipped
        return {**row, "caught": caught, "how": f"{name}: {'passed' if caught else 'did not pass'} ({res.testsRun} run)"}
    if kind == "ts":
        caught = name in ts
        return {**row, "caught": caught,
                "how": f"a TypeScript test titled {name!r} {'exists' if caught else 'is missing'} under ts/test/ "
                       "(run by the ts CI job)"}
    return {**row, "caught": False, "how": f"unknown reference kind {kind!r}"}


def build(catalog: dict[str, dict[str, Any]], root: str, spec_sha: str) -> dict[str, Any]:
    ts = ts_titles(root)
    checks: dict[str, Any] = {}
    for cid in sorted(catalog):
        e = catalog[cid]
        faults = [resolve(cid, ref, root, ts) for ref in e.get("faulty", [])]
        checks[cid] = {"profile": e.get("profile"), "faults": faults, "caught": sum(1 for f in faults if f["caught"])}
    return {"schema": SCHEMA, "generated_from": spec_sha, "checks": checks}


def spec_sha256(root: str) -> str:
    with open(os.path.join(root, "src", "x402conf", "spec.py"), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def problems(matrix: dict[str, Any], committed: dict[str, Any] | None) -> list[str]:
    out = []
    for cid, c in matrix["checks"].items():
        if c["caught"] == 0:
            out.append(f"{cid} catches no faulty build: " + ("; ".join(f["how"] for f in c["faults"]) or "no faulty reference"))
    if committed is None:
        out.append(f"{OUT} is missing: run python3 tools/mutation_matrix.py --write and commit it")
    elif committed != matrix:
        out.append(f"{OUT} is stale: run python3 tools/mutation_matrix.py --write and commit it")
    return out


def dump(matrix: dict[str, Any]) -> str:
    return json.dumps(matrix, indent=1, sort_keys=True) + "\n"


def main(argv: list[str]) -> int:
    root = ROOT
    if "--root" in argv:
        root = os.path.abspath(argv[argv.index("--root") + 1])
    S = _load(root)
    matrix = build(S.CATALOG, root, spec_sha256(root))
    path = os.path.join(root, OUT)
    if "--write" in argv:
        with open(path, "w", encoding="utf-8") as f:
            f.write(dump(matrix))
        print(f"wrote {OUT}: {len(matrix['checks'])} checks")
        return 0
    committed = None
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            committed = json.load(f)
    if "--check" in argv:
        found = problems(matrix, committed)
        for p in found:
            print(f"mutation matrix: {p}")
        n = sum(c["caught"] for c in matrix["checks"].values())
        print(f"mutation matrix: {len(matrix['checks'])} checks, {n} caught faults, {len(found)} problem(s)")
        return 1 if found else 0
    for cid, c in matrix["checks"].items():
        print(f"{cid:5} {c['profile']:17} {c['caught']}/{len(c['faults'])} " + ", ".join(f["ref"] for f in c["faults"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
