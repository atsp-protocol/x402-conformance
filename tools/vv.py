#!/usr/bin/env python3
"""Proofline V&V: verify every acceptance criterion in proofline.json against this repository and emit receipts.

    python3 tools/vv.py verify [TASK ...] [--receipts DIR] [--json] [--pre-merge]
    python3 tools/vv.py hygiene        secret and attribution scan of the tracked tree

Implements the proofline/1 verifier types this contract uses: command (expect_exit, min_tests, max_skipped),
metric (JSON key, op, value), grep (file, pattern, must present|absent), file_exists, scope and pushed.

Exit status. 1 if a task listed as done in vv/claims.json fails any mandatory criterion, if any tracked file lies
outside every task's scope, or if a proofline.json.sig is present but does not verify. Otherwise 0. A task that is
not claimed is reported as open and does not fail the run. Unsigned contracts are reported as
"unsigned: awaiting owner signature".

Pre-merge mode. A pull request is checked on a merge commit that cannot be on origin/main yet, so in pre-merge mode
(--pre-merge, or GITHUB_EVENT_NAME=pull_request) a "pushed" criterion that is not met yet is reported as
"pending (pre-merge)" and does not fail the run. Every other criterion still does. The run on main after the merge is
strict, and the receipt records which mode produced it."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import operator
import os
import re
import subprocess
import sys
import time
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACT: dict[str, Any] = json.load(open(os.path.join(ROOT, "proofline.json")))
PRE_MERGE = False  # set by main() from --pre-merge or GITHUB_EVENT_NAME=pull_request
PENDING = "pending (pre-merge)"
OPS = {">=": operator.ge, "<=": operator.le, "==": operator.eq, ">": operator.gt, "<": operator.lt}


def canon(v: Any) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sh(cmd: str, timeout: int) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout + p.stderr
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout
    return [f for f in out.splitlines() if f]


def glob_match(path: str, pat: str) -> bool:
    if pat.endswith("/**"):
        return path.startswith(pat[:-3] + "/")
    return fnmatch.fnmatchcase(path, pat)


def in_scope(path: str, allow: list[str]) -> bool:
    return any(glob_match(path, p) for p in allow)


def check(v: dict[str, Any], task: dict[str, Any]) -> tuple[bool, str]:
    t = v["type"]
    if t == "command":
        rc, out = sh(v["cmd"], int(v.get("timeout_s", 600)))
        ok = rc == int(v.get("expect_exit", 0))
        m = re.search(r"Ran (\d+) tests?", out)
        n = int(m.group(1)) if m else None
        sk = int(re.search(r"skipped=(\d+)", out).group(1)) if re.search(r"skipped=(\d+)", out) else 0
        if "min_tests" in v:
            ok = ok and n is not None and n >= int(v["min_tests"])
        if "max_skipped" in v:
            ok = ok and sk <= int(v["max_skipped"])
        return ok, f"exit {rc}" + (f", {n} tests, {sk} skipped" if n is not None else "") + ("" if ok else f": {out[-300:]}")
    if t == "metric":
        rc, out = sh(v["cmd"], int(v.get("timeout_s", 600)))
        try:
            val = json.loads(out.strip().splitlines()[-1])[v["key"]]
        except Exception:  # noqa: BLE001
            return False, f"no JSON key {v['key']} (exit {rc}): {out[-200:]}"
        ok = OPS[v["op"]](val, v["value"])
        return ok, f"{v['key']}={val} {v['op']} {v['value']}"
    if t == "grep":
        p = os.path.join(ROOT, v["file"])
        if not os.path.isfile(p):
            return False, f"{v['file']} missing"
        hit = re.search(v["pattern"], open(p, encoding="utf-8", errors="replace").read(), re.M) is not None
        ok = hit if v.get("must", "present") == "present" else not hit
        return ok, f"pattern {'found' if hit else 'not found'} in {v['file']}"
    if t == "file_exists":
        return os.path.exists(os.path.join(ROOT, v["path"])), v["path"]
    if t == "scope":
        # Every tracked file must be owned by some task's scope; a file no task owns is out of scope for all of them.
        allow_all = [p for x in CONTRACT["tasks"] for p in x.get("scope", {}).get("allow", [])]
        stray = [f for f in tracked() if not in_scope(f, allow_all)]
        mine = [f for f in tracked() if in_scope(f, task.get("scope", {}).get("allow", []))]
        return not stray, f"{len(mine)} files in this task's scope; out of scope: {stray[:5] or 'none'}"
    if t == "pushed":
        rc, out = sh("git branch -r --contains HEAD", 60)
        ok = rc == 0 and "origin/main" in out
        if not ok and PRE_MERGE:
            return True, f"{PENDING}: HEAD is not on origin/main yet; the strict run on main after the merge decides"
        return ok, "HEAD is on origin/main" if ok else "HEAD is not on origin/main yet"
    return False, f"unknown verifier type {t}"


def signature() -> tuple[int, dict[str, Any]]:
    try:
        p = subprocess.run(["node", "tools/verify-sig.mjs"], cwd=ROOT, capture_output=True, text=True, timeout=60)
        return p.returncode, json.loads(p.stdout.strip() or "{}")
    except Exception as e:  # noqa: BLE001
        return 1, {"status": f"invalid: verifier did not run ({e!r})"}


HYGIENE = [
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "private key"),
    (r"\b(ghp|gho|ghs|github_pat)_[A-Za-z0-9_]{20,}", "GitHub token"),
    (r"\bxprv[1-9A-HJ-NP-Za-km-z]{50,}", "extended private key"),
    (r"\b(sk|xai)-[A-Za-z0-9]{24,}", "API key"),
    (r"AKIA[0-9A-Z]{16}", "AWS key"),
    (r"(?i)\b(mnemonic|seed phrase)\s*[:=]", "mnemonic"),
    (r"(?i)co-authored-by|generated (by|with) (an? )?(ai|llm|assistant)", "attribution"),
    (r"(?:/home/|/Users/)[A-Za-z0-9._-]+/", "absolute home path"),
]
HYGIENE_SKIP = {"tools/vv.py", "CODE_OF_CONDUCT.md", "LICENSE"}


def hygiene() -> list[dict[str, Any]]:
    hits = []
    for f in tracked():
        if f in HYGIENE_SKIP or f.startswith("evidence/"):
            continue
        try:
            txt = open(os.path.join(ROOT, f), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for pat, what in HYGIENE:
            for m in re.finditer(pat, txt):
                hits.append({"file": f, "line": txt.count("\n", 0, m.start()) + 1, "kind": what})
    log = subprocess.run(["git", "log", "--format=%an <%ae>%n%B"], cwd=ROOT, capture_output=True, text=True).stdout
    for pat, what in HYGIENE[6:7]:
        if re.search(pat, log):
            hits.append({"file": "(git log)", "line": 0, "kind": what})
    # The owner commits as mgillr; signing commits made on the owner's machine carry the owner's legal name.
    owner = {"mgillr", "Ryan Gillespie"}
    names = subprocess.run(["git", "log", "--format=%an"], cwd=ROOT, capture_output=True, text=True).stdout
    authors = {a.strip() for a in names.splitlines() if a.strip()}
    if authors - owner:
        hits.append({"file": "(git log)", "line": 0, "kind": f"authors other than the owner: {sorted(authors - owner)}"})
    return hits


def main(argv: list[str]) -> int:
    if argv[1:2] == ["hygiene"]:
        h = hygiene()
        print(json.dumps({"hits": len(h), "detail": h[:50]}))
        return 0 if not h else 1
    if argv[1:2] != ["verify"]:
        print(__doc__)
        return 2
    global PRE_MERGE
    PRE_MERGE = "--pre-merge" in argv or os.environ.get("GITHUB_EVENT_NAME") == "pull_request"
    mode = "pre-merge" if PRE_MERGE else "strict"
    as_json = "--json" in argv
    rdir = None
    if "--receipts" in argv:
        rdir = argv[argv.index("--receipts") + 1]
    want = [a for a in argv[2:] if not a.startswith("--") and a != rdir]
    contract = CONTRACT
    chash = hashlib.sha256(canon(contract).encode()).hexdigest()
    claims = json.load(open(os.path.join(ROOT, "vv", "claims.json"))).get("done", [])
    sig_rc, sig = signature()
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    tasks = [t for t in contract["tasks"] if not want or t["id"] in want]
    report, failed = [], []
    for t in tasks:
        rows = []
        for c in t["criteria"]:
            ok, detail = check(c["verifier"], t)
            rows.append({"id": c["id"], "mandatory": c.get("mandatory", True), "pass": ok, "detail": detail,
                         "statement": c["statement"], "pending": detail.startswith(PENDING)})
        passed = all(r["pass"] for r in rows if r["mandatory"])
        state = ("done" if passed else "FAILED") if t["id"] in claims else ("met (unclaimed)" if passed else "open")
        if t["id"] in claims and not passed:
            failed.append(t["id"])
        report.append({"task": t["id"], "title": t["title"], "state": state, "criteria": rows})
    allow_all = [p for t in contract["tasks"] for p in t.get("scope", {}).get("allow", [])]
    out_of_scope = [f for f in tracked() if not in_scope(f, allow_all)]
    unknown_claims = [c for c in claims if c not in {t["id"] for t in contract["tasks"]}]
    ok = not failed and not out_of_scope and not unknown_claims and sig_rc in (0, 3)
    pending = [c["id"] for r in report for c in r["criteria"] if c["pending"]]
    receipt = {"v": "x402conf.vv-receipt/1", "t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "head": head,
               "mode": mode, "pending": pending,
               "contract_sha256": chash, "signature": sig.get("status"), "ok": ok, "claimed_failed": failed,
               "out_of_scope": out_of_scope, "unknown_claims": unknown_claims,
               "tasks": [{"task": r["task"], "state": r["state"],
                          "pass": sum(c["pass"] for c in r["criteria"]), "of": len(r["criteria"])} for r in report]}
    receipt["sha256"] = hashlib.sha256(canon(receipt).encode()).hexdigest()
    if rdir:
        os.makedirs(rdir, exist_ok=True)
        with open(os.path.join(rdir, f"vv-{receipt['t'].replace(':', '')}-{head[:12]}.json"), "w") as f:
            json.dump({"receipt": receipt, "report": report}, f, indent=1)
    if as_json:
        print(json.dumps({"receipt": receipt, "report": report}, indent=1))
    else:
        print(f"contract {chash[:16]}  {sig.get('status')}  mode={mode}")
        for r in report:
            n = sum(c["pass"] for c in r["criteria"])
            print(f"{r['task']:7} {r['state']:16} {n}/{len(r['criteria'])}  {r['title']}")
            claimed = r["state"] in ("done", "FAILED")
            for c in r["criteria"]:
                if c["pending"]:
                    print(f"         pending {c['id']}: {c['detail'][:160]}")
                if not c["pass"]:
                    tag = "FAIL" if claimed and c["mandatory"] else "todo"
                    print(f"         {tag} {c['id']}: {c['detail'][:160]}")
        if out_of_scope:
            print("OUT OF SCOPE (no task owns these files):", ", ".join(out_of_scope))
        if unknown_claims:
            print("UNKNOWN CLAIMS:", ", ".join(unknown_claims))
        print(f"receipt {receipt['sha256'][:16]}  {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
