#!/usr/bin/env python3
"""Turn a run's evidence bundle into one committed matrix row (XC-94).

    python3 tools/row_from_evidence.py BUNDLE_DIR --row NAME --consent URL [--root DIR]

BUNDLE_DIR is what the Action's evidence mode uploads (run.json as the tool wrote it, README.md, SHA256SUMS), or a
directory with a run.json from the CLI. --consent is the issue or pull request where the project agreed to be listed.
The tool checks the bundle, copies it to evidence/impl-matrix/NAME/, records the consent in its README, rewrites
SHA256SUMS and regenerates the matrix and badges with tools/compat_matrix.py --write. It refuses, and writes nothing:

  - a SHA256SUMS line that does not match its file
  - a run graded on a mainnet network
  - a facilitator that is not on loopback
  - a payment against a live (non-loopback) endpoint: any R check, which pays through the facilitator double
  - no consent URL, or one that is not an issue or pull request on github.com
  - a run.json that is not a probe run (results, each with a check and a status) or an external GET-only run
    (x402conf resource, the tier-1 run of the run queue, XC-98)
  - a row name that is not lower case letters, digits, '.', '_' or '-', or a row that exists without --update
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROWS = "evidence/impl-matrix"
ROW_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
CONSENT = re.compile(r"^https://github\.com/[\w.-]+/[\w.-]+/(issues|pull)/\d+(#[\w-]+)?$")
LOOPBACK = ("127.0.0.1", "localhost", "::1")
MAINNET = frozenset({"solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp", "eip155:1", "eip155:8453", "eip155:137", "eip155:42161",
                     "eip155:10", "eip155:43114", "eip155:56", "eip155:1329", "eip155:143", "eip155:196", "eip155:480"})


def sha256(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def networks(doc: object) -> set[str]:
    out: set[str] = set()
    if isinstance(doc, dict):
        for k, v in doc.items():
            out |= {v} if k in ("network", "graded_on") and isinstance(v, str) else networks(v)
    elif isinstance(doc, list):
        for v in doc:
            out |= networks(v)
    return out


def host(url: str) -> str:
    return urllib.parse.urlsplit(url).hostname or ""


def problems(bundle: str, row: str, consent: str) -> list[str]:
    out: list[str] = []
    if not ROW_NAME.match(row):
        out.append(f"row name {row!r}: use lower case letters, digits, '.', '_' or '-'")
    if not consent or not CONSENT.match(consent):
        out.append("no consent: --consent must be the github.com issue or pull request where the project agreed to be listed")
    run = os.path.join(bundle, "run.json")
    if not os.path.isfile(run):
        return out + [f"{bundle}: no run.json"]
    sums = os.path.join(bundle, "SHA256SUMS")
    if os.path.isfile(sums):
        for line in open(sums, encoding="utf-8"):
            m = re.match(r"^([0-9a-f]{64})\s+\*?(\S+)\s*$", line.strip())
            if not m:
                continue
            p = os.path.join(bundle, m.group(2))
            if not os.path.isfile(p) or sha256(p) != m.group(1):
                out.append(f"{m.group(2)} does not match its hash in SHA256SUMS")
    try:
        doc = json.load(open(run, encoding="utf-8"))
    except ValueError:
        return out + ["run.json is not JSON"]
    results = doc.get("results") if isinstance(doc, dict) else None
    probe = isinstance(results, list) and bool(results) and all(
        isinstance(r, dict) and isinstance(r.get("check"), str) and ("status" in r or "pass" in r) for r in results)
    external = isinstance(doc, dict) and doc.get("mode") in ("resource-GET-only", "resource-unpaid")
    get_only = (external and isinstance(results, list)
                and bool(results) and all(isinstance(r, dict) and isinstance(r.get("checks"), list) and r["checks"]
                                          and all(isinstance(c, dict) and isinstance(c.get("check"), str) and "pass" in c
                                                  for c in r["checks"]) for r in results))
    if not (probe or get_only):
        out.append("run.json is not a probe run: it needs results, each with a check and a status (the Action's "
                   "resource-server.json or x402conf-svm probe --out), or the run queue's external unpaid run "
                   "(x402conf resource)")
    main = sorted(networks(doc) & MAINNET)
    if main:
        out.append(f"the run was graded on a mainnet network ({', '.join(main)})")
    fac = str(doc.get("facilitator_double") or "")
    if fac and host(fac) not in LOOPBACK:
        out.append(f"the facilitator {fac} is not on loopback")
    target = str(doc.get("resource") or doc.get("target") or "")
    paid = [str(r.get("check", "")).split(" ")[0] for r in doc.get("results", [])
            if isinstance(r, dict) and re.match(r"^R\d", str(r.get("check", "")))]
    if target and host(target) not in LOOPBACK and paid:
        out.append(f"a payment against a live endpoint ({target}): {len(paid)} paid check(s); live runs are GET-only")
    return out


def main(argv: list[str]) -> int:
    if not argv or argv[0].startswith("-"):
        print(__doc__)
        return 2
    bundle = argv[0]
    opt = {k: argv[argv.index(k) + 1] for k in ("--row", "--consent", "--root") if k in argv and argv.index(k) + 1 < len(argv)}
    root = os.path.abspath(opt.get("--root", ROOT))
    row, consent = opt.get("--row", ""), opt.get("--consent", "")
    bad = problems(bundle, row, consent)
    dest = os.path.join(root, ROWS, row)
    if not bad and os.path.exists(dest) and "--update" not in argv:
        bad.append(f"{ROWS}/{row} exists: pass --update to refresh it")
    if bad:
        for b in bad:
            print(f"row_from_evidence: {b}")
        print("row_from_evidence: refused, nothing written")
        return 1
    os.makedirs(dest, exist_ok=True)
    shutil.copyfile(os.path.join(bundle, "run.json"), os.path.join(dest, "run.json"))
    readme = os.path.join(bundle, "README.md")
    text = open(readme, encoding="utf-8").read().rstrip("\n") if os.path.isfile(readme) else f"# {row}"
    text += f"\n\nListed with the project's consent: {consent}\n"
    with open(os.path.join(dest, "README.md"), "w", encoding="utf-8") as f:
        f.write(text)
    with open(os.path.join(dest, "SHA256SUMS"), "w", encoding="utf-8") as f:
        f.write("".join(f"{sha256(os.path.join(dest, n))}  {n}\n" for n in ("README.md", "run.json")))
    rc = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "compat_matrix.py"), "--write", "--root", root]).returncode
    print(f"row_from_evidence: {ROWS}/{row} written; commit it with docs/MATRIX.md, docs/compat-matrix.json and the badge")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
