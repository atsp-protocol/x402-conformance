#!/usr/bin/env python3
"""Proofline V&V: verify every acceptance criterion in proofline.json against this repository and emit receipts.

    python3 tools/vv.py verify [TASK ...] [--receipts DIR] [--json] [--pre-merge]
    python3 tools/vv.py verify --shard I/N [--receipts DIR] [--json] [--pre-merge]
    python3 tools/vv.py merge DIR [--receipts DIR] [--json]
    python3 tools/vv.py costs DIR [--run ID ...] [--out FILE]
    python3 tools/vv.py costs --predict
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
strict, and the receipt records which mode produced it.

Shards (XC-125). --shard I/N verifies only the tasks whose position in proofline.json is I modulo N, and the receipt
records the shard, the task ids it was assigned and each task's seconds. CI runs N shards in parallel jobs, each with
its own checkout, and `vv.py merge DIR` combines their receipts into one receipt in the same schema, with the tasks
in contract order and the shard receipts it merged. The merge fails closed: it exits 1, with ok false, when a shard
is missing or duplicated, when the shards disagree on head, contract hash, mode, signature state, out-of-scope files
or unknown claims, when a shard's tasks are not exactly its partition, when a receipt's hash does not match its
content, or when any shard failed. Every criterion still runs, in exactly one shard.

Cost split (XC-126). When vv/costs.json is present, --shard I/N does not split by position: it takes the tasks
longest first (by measured seconds, then contract position) and gives each to the shard with the smallest total so
far, ties to the lowest index; a task with no cost counts as the median known cost, and each shard runs its tasks in
contract order. Without the file the split is the position rule above. Each shard receipt records the split it used
and the sha256 of vv/costs.json, and the merge recomputes every shard's tasks from the checkout's file and fails
closed when the shards disagree on either, or when a shard's hash is not the checkout's file. `vv.py costs DIR`
writes vv/costs.json from the shard or merged receipts under DIR: the median seconds per task, rounded to 0.1, and
the CI run ids given with --run, with no timestamp, so the same receipts give the same bytes. `vv.py costs --predict`
prints the largest shard's predicted minutes for the vv-shard matrix size in ci.yml. The cost file only decides which
shard runs a task; every task is still verified on every run."""

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
COSTS_FILE = os.path.join(ROOT, "vv", "costs.json")
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


def load_claims() -> list[str]:
    with open(os.path.join(ROOT, "vv", "claims.json"), encoding="utf-8") as f:
        done: list[str] = json.load(f).get("done", [])
    return done


def parse_shard(text: str) -> tuple[int, int]:
    """'I/N' with 0 <= I < N; anything else is refused."""
    m = re.fullmatch(r"(\d+)/(\d+)", text or "")
    if not m:
        raise ValueError(f"--shard takes I/N, such as 0/4, not {text!r}")
    i, n = int(m.group(1)), int(m.group(2))
    if n < 1 or i >= n:
        raise ValueError(f"--shard {text}: I must be 0 to N-1 and N at least 1")
    return i, n


def load_costs(path: str | None = None) -> tuple[dict[str, float] | None, str | None]:
    """The per-task seconds in vv/costs.json and the sha256 of its bytes, or (None, None) without the file."""
    path = path or COSTS_FILE
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except FileNotFoundError:
        return None, None
    seconds = json.loads(raw).get("seconds") or {}
    return {str(k): float(v) for k, v in seconds.items()}, hashlib.sha256(raw).hexdigest()


def partition(tasks: list[dict[str, Any]], i: int, n: int,
              costs: dict[str, float] | None | bool = True) -> list[dict[str, Any]]:
    """The tasks shard I of N verifies. With costs (the default reads vv/costs.json): longest first to the lightest
    shard, ties to the lowest index, a task with no cost at the median known cost. Without: position I modulo N."""
    if costs is True:
        costs = load_costs()[0]
    if not costs:
        return [t for k, t in enumerate(tasks) if k % n == i]
    known = sorted(costs.values())
    median = known[len(known) // 2] if len(known) % 2 else (known[len(known) // 2 - 1] + known[len(known) // 2]) / 2
    cost = [costs.get(t["id"], median) for t in tasks]
    order = sorted(range(len(tasks)), key=lambda k: (-cost[k], k))
    totals = [0.0] * n
    shard_of = [0] * len(tasks)
    for k in order:
        j = min(range(n), key=lambda x: (totals[x], x))
        totals[j] += cost[k]
        shard_of[k] = j
    return [t for k, t in enumerate(tasks) if shard_of[k] == i]


def costs_from_receipts(paths: list[str], runs: list[str]) -> dict[str, Any]:
    """vv/costs.json from receipts: the median seconds per task over the receipts that list it."""
    seen: dict[str, list[float]] = {}
    for p in paths:
        with open(p, encoding="utf-8") as f:
            doc = json.load(f)
        tasks = (doc.get("receipt") or doc).get("tasks")
        if not isinstance(tasks, list) or not tasks or any(not isinstance(t.get("seconds"), int | float) for t in tasks):
            raise ValueError(f"{os.path.basename(p)}: no per-task seconds in the receipt")
        for t in tasks:
            seen.setdefault(str(t["task"]), []).append(float(t["seconds"]))
    if not seen:
        raise ValueError("no receipts")
    med = {}
    for task, v in seen.items():
        v = sorted(v)
        m = v[len(v) // 2] if len(v) % 2 else (v[len(v) // 2 - 1] + v[len(v) // 2]) / 2
        med[task] = round(m, 1)
    return {"v": "x402conf.vv-costs/1", "source_runs": sorted(set(runs)), "seconds": dict(sorted(med.items()))}


def ci_shard_count() -> int:
    """N from the vv-shard job's --shard ${{ matrix.shard }}/N in ci.yml."""
    with open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8") as f:
        m = re.search(r"--shard \$\{\{ matrix\.shard \}\}/(\d+)", f.read())
    if not m:
        raise ValueError("ci.yml has no --shard ${{ matrix.shard }}/N")
    return int(m.group(1))


def predict(costs: dict[str, float], n: int) -> dict[str, Any]:
    tasks = CONTRACT["tasks"]
    known = sorted(costs.values())
    median = known[len(known) // 2] if len(known) % 2 else (known[len(known) // 2 - 1] + known[len(known) // 2]) / 2
    per = [sum(costs.get(t["id"], median) for t in partition(tasks, i, n, costs)) / 60 for i in range(n)]
    return {"shards": n, "shard_minutes": [round(x, 1) for x in per], "max_shard_minutes": round(max(per), 1)}


def seal(receipt: dict[str, Any]) -> dict[str, Any]:
    receipt.pop("sha256", None)
    receipt["sha256"] = hashlib.sha256(canon(receipt).encode()).hexdigest()
    return receipt


def write_receipt(rdir: str | None, receipt: dict[str, Any], report: list[dict[str, Any]], tag: str = "") -> None:
    if rdir:
        os.makedirs(rdir, exist_ok=True)
        name = f"vv-{receipt['t'].replace(':', '')}-{receipt['head'][:12]}{tag}.json"
        with open(os.path.join(rdir, name), "w") as f:
            json.dump({"receipt": receipt, "report": report}, f, indent=1)


def print_summary(receipt: dict[str, Any], report: list[dict[str, Any]], extra: list[str] | None = None) -> None:
    head = f"contract {receipt['contract_sha256'][:16]}  {receipt.get('signature')}  mode={receipt['mode']}"
    print(head + (f"  shard={receipt['shard']}" if receipt.get("shard") else ""))
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
    if receipt["out_of_scope"]:
        print("OUT OF SCOPE (no task owns these files):", ", ".join(receipt["out_of_scope"]))
    if receipt["unknown_claims"]:
        print("UNKNOWN CLAIMS:", ", ".join(receipt["unknown_claims"]))
    for x in extra or []:
        print("MERGE:", x)
    print(f"receipt {receipt['sha256'][:16]}  {'PASS' if receipt['ok'] else 'FAIL'}")


def verify_run(want: list[str], shard: tuple[int, int] | None, rdir: str | None,
               as_json: bool) -> int:
    contract = CONTRACT
    chash = hashlib.sha256(canon(contract).encode()).hexdigest()
    claims = load_claims()
    sig_rc, sig = signature()
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    tasks = partition(contract["tasks"], *shard) if shard else [t for t in contract["tasks"] if not want or t["id"] in want]
    report, failed = [], []
    for t in tasks:
        rows = []
        start = time.monotonic()
        for c in t["criteria"]:
            ok, detail = check(c["verifier"], t)
            rows.append({"id": c["id"], "mandatory": c.get("mandatory", True), "pass": ok, "detail": detail,
                         "statement": c["statement"], "pending": detail.startswith(PENDING)})
        passed = all(r["pass"] for r in rows if r["mandatory"])
        state = ("done" if passed else "FAILED") if t["id"] in claims else ("met (unclaimed)" if passed else "open")
        if t["id"] in claims and not passed:
            failed.append(t["id"])
        report.append({"task": t["id"], "title": t["title"], "state": state, "criteria": rows,
                       "seconds": round(time.monotonic() - start, 1)})
    allow_all = [p for t in contract["tasks"] for p in t.get("scope", {}).get("allow", [])]
    out_of_scope = [f for f in tracked() if not in_scope(f, allow_all)]
    unknown_claims = [c for c in claims if c not in {t["id"] for t in contract["tasks"]}]
    ok = not failed and not out_of_scope and not unknown_claims and sig_rc in (0, 3)
    pending = [c["id"] for r in report for c in r["criteria"] if c["pending"]]
    receipt: dict[str, Any] = {
        "v": "x402conf.vv-receipt/1", "t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "head": head,
        "mode": "pre-merge" if PRE_MERGE else "strict", "pending": pending, "contract_sha256": chash,
        "signature": sig.get("status"), "ok": ok, "claimed_failed": failed, "out_of_scope": out_of_scope,
        "unknown_claims": unknown_claims,
        "tasks": [{"task": r["task"], "state": r["state"], "pass": sum(c["pass"] for c in r["criteria"]),
                   "of": len(r["criteria"]), "seconds": r["seconds"]} for r in report]}
    if shard:
        receipt["shard"] = f"{shard[0]}/{shard[1]}"
        receipt["assigned"] = [t["id"] for t in tasks]
        costs, costs_sha = load_costs()
        receipt["partition"] = "cost" if costs else "position"
        receipt["costs_sha256"] = costs_sha
    seal(receipt)
    write_receipt(rdir, receipt, report, f"-shard{shard[0]}of{shard[1]}" if shard else "")
    if as_json:
        print(json.dumps({"receipt": receipt, "report": report}, indent=1))
    else:
        print_summary(receipt, report)
    return 0 if ok else 1


def merge_receipts(paths: list[str], contract: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """One receipt from N shard receipts, and every reason it cannot stand."""
    problems: list[str] = []
    shards: dict[int, dict[str, Any]] = {}
    n_seen: set[int] = set()
    for p in paths:
        try:
            with open(p, encoding="utf-8") as f:
                doc = json.load(f)
            rc, rep = doc["receipt"], doc["report"]
        except (OSError, ValueError, KeyError, TypeError) as e:
            problems.append(f"{os.path.basename(p)}: not a shard receipt ({e})")
            continue
        body = {k: v for k, v in rc.items() if k != "sha256"}
        if hashlib.sha256(canon(body).encode()).hexdigest() != rc.get("sha256"):
            problems.append(f"{os.path.basename(p)}: the receipt's sha256 does not match its content")
        try:
            i, n = parse_shard(str(rc.get("shard") or ""))
        except ValueError:
            problems.append(f"{os.path.basename(p)}: no shard I/N in the receipt")
            continue
        n_seen.add(n)
        if i in shards:
            problems.append(f"shard {i}/{n} appears more than once")
            continue
        shards[i] = {"receipt": rc, "report": rep}
    if len(n_seen) > 1:
        problems.append(f"the shards disagree on N: {sorted(n_seen)}")
    n = max(n_seen) if n_seen else 0
    if not n:
        problems.append("no shard receipts")
    for i in range(n):
        if i not in shards:
            problems.append(f"shard {i}/{n} is missing")
    receipts = [shards[i]["receipt"] for i in sorted(shards)]
    for field in ("head", "contract_sha256", "mode", "signature", "out_of_scope", "unknown_claims", "partition",
                  "costs_sha256"):
        values = {json.dumps(r.get(field), sort_keys=True) for r in receipts}
        if len(values) > 1:
            problems.append(f"the shards disagree on {field}")
    chash = hashlib.sha256(canon(contract).encode()).hexdigest()
    if receipts and receipts[0].get("contract_sha256") != chash:
        problems.append("the shards verified a different contract from the one checked out here")
    costs, costs_sha = load_costs()
    if receipts and (receipts[0].get("costs_sha256") != costs_sha
                     or receipts[0].get("partition") != ("cost" if costs else "position")):
        problems.append("the shards split by a different vv/costs.json from the one checked out here")
    for i, sh in sorted(shards.items()):
        want = [t["id"] for t in partition(contract["tasks"], i, n, costs)] if n else []
        got = [t["task"] for t in sh["receipt"].get("tasks", [])]
        if sh["receipt"].get("assigned") != want or got != want:
            problems.append(f"shard {i}/{n} did not verify exactly its partition")
        if not sh["receipt"].get("ok"):
            problems.append(f"shard {i}/{n} failed")
    order = {t["id"]: k for k, t in enumerate(contract["tasks"])}
    report = sorted((r for sh in shards.values() for r in sh["report"]), key=lambda r: order.get(r["task"], 1 << 30))
    tasks = sorted((t for r in receipts for t in r.get("tasks", [])), key=lambda t: order.get(t["task"], 1 << 30))
    first = receipts[0] if receipts else {}
    merged: dict[str, Any] = {
        "v": "x402conf.vv-receipt/1", "t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "head": first.get("head", ""), "mode": first.get("mode", ""),
        "pending": [c["id"] for r in report for c in r["criteria"] if c.get("pending")],
        "contract_sha256": first.get("contract_sha256", chash), "signature": first.get("signature"),
        "ok": not problems,
        "claimed_failed": [t["task"] for t in tasks if t["state"] == "FAILED"],
        "out_of_scope": first.get("out_of_scope", []), "unknown_claims": first.get("unknown_claims", []),
        "tasks": tasks, "shards": [{"shard": r["shard"], "sha256": r["sha256"]} for r in receipts],
        "merge_problems": problems}
    return seal(merged), report, problems


def costs_main(args: list[str]) -> int:
    if args == ["--predict"]:
        costs = load_costs()[0]
        if not costs:
            print("vv costs --predict: no vv/costs.json", file=sys.stderr)
            return 2
        try:
            n = ci_shard_count()
        except (OSError, ValueError) as e:
            print(f"vv costs --predict: {e}", file=sys.stderr)
            return 2
        print(json.dumps(predict(costs, n)))
        return 0
    runs: list[str] = []
    out = COSTS_FILE
    dirs: list[str] = []
    k = 0
    while k < len(args):
        if args[k] in ("--run", "--out"):
            if k + 1 >= len(args):
                print(f"vv costs: {args[k]} needs a value", file=sys.stderr)
                return 2
            if args[k] == "--run":
                runs.append(args[k + 1])
            else:
                out = args[k + 1]
            k += 2
            continue
        dirs.append(args[k])
        k += 1
    if len(dirs) != 1:
        print("vv costs: give one directory of receipts", file=sys.stderr)
        return 2
    paths = sorted(os.path.join(dp, f) for dp, _, fs in os.walk(dirs[0]) for f in fs
                   if f.startswith("vv-") and f.endswith(".json"))
    try:
        doc = costs_from_receipts(paths, runs)
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"vv costs: {e}", file=sys.stderr)
        return 2
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(json.dumps(doc, indent=1) + "\n")
    print(f"wrote {len(doc['seconds'])} task costs from {len(paths)} receipts to {out}")
    return 0


def main(argv: list[str]) -> int:
    if argv[1:2] == ["hygiene"]:
        h = hygiene()
        print(json.dumps({"hits": len(h), "detail": h[:50]}))
        return 0 if not h else 1
    if argv[1:2] == ["costs"]:
        return costs_main(argv[2:])
    if argv[1:2] not in (["verify"], ["merge"]):
        print(__doc__)
        return 2
    args = argv[2:]
    rdir = shard_arg = None
    rest: list[str] = []
    k = 0
    while k < len(args):
        a = args[k]
        if a in ("--receipts", "--shard"):
            if k + 1 >= len(args):
                print(f"vv: {a} needs a value", file=sys.stderr)
                return 2
            if a == "--receipts":
                rdir = args[k + 1]
            else:
                shard_arg = args[k + 1]
            k += 2
            continue
        rest.append(a)
        k += 1
    as_json = "--json" in rest
    if argv[1] == "merge":
        dirs = [a for a in rest if not a.startswith("--")]
        if len(dirs) != 1:
            print("vv merge: give one directory of shard receipts", file=sys.stderr)
            return 2
        paths = sorted(os.path.join(dp, f) for dp, _, fs in os.walk(dirs[0]) for f in fs
                       if f.startswith("vv-") and f.endswith(".json"))
        receipt, report, problems = merge_receipts(paths, CONTRACT)
        write_receipt(rdir, receipt, report, "-merged")
        if as_json:
            print(json.dumps({"receipt": receipt, "report": report}, indent=1))
        else:
            print_summary(receipt, report, problems)
        return 0 if receipt["ok"] else 1
    global PRE_MERGE
    PRE_MERGE = "--pre-merge" in rest or os.environ.get("GITHUB_EVENT_NAME") == "pull_request"
    want = [a for a in rest if not a.startswith("--")]
    shard = None
    if shard_arg is not None:
        if want:
            print("vv verify: --shard verifies a partition of the whole contract; it does not take task ids",
                  file=sys.stderr)
            return 2
        try:
            shard = parse_shard(shard_arg)
        except ValueError as e:
            print(f"vv verify: {e}", file=sys.stderr)
            return 2
    return verify_run(want, shard, rdir, as_json)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
