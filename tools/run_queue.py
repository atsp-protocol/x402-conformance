#!/usr/bin/env python3
"""The free-run queue (XC-97, two tiers in XC-98): reruns for listed projects that installed the notify hook.

    python3 tools/run_queue.py enqueue --queue DIR --now ISO (--comment FILE --issue-url URL --author LOGIN
                                       --issue-author LOGIN | --dispatch FILE) [--root DIR]
    python3 tools/run_queue.py next    --queue DIR --now ISO [--root DIR] [--github-output FILE]
    python3 tools/run_queue.py publish --bundle DIR --slug SLUG --ref REF --version V [--root DIR]
    python3 tools/run_queue.py finish  --queue DIR --slug SLUG --now ISO --result ok|failed|refused [--run-id ID]
    python3 tools/run_queue.py release --queue DIR --comment FILE --author LOGIN [--github-output FILE]
    python3 tools/run_queue.py attest  --queue DIR --now ISO (--comment FILE --issue-url URL --author LOGIN
                                       --issue-author LOGIN | --dispatch FILE) [--root DIR] [--github-output FILE]

Two tiers (XC-98). The queue only ever runs tier 1, External-verified: the checks that work from outside the
project's stack (src/x402conf/tiers.py EXTERNAL), against the row's public testnet endpoint: unpaid requests (GETs,
and one HEAD for R16a only with the operator's permission on the form, consent.unpaid_head) paced at least
min_probe_interval_s apart, with the pinned suite release (matrix/queue/suite.json). It never checks out or
runs the project's code. Tier 2, Full suite (self-hosted), runs only in the project's own CI with the Action and
`attest: true`; `attest` takes the request `/x402-conformance attest slug=<slug> repo=<owner/repo> ref=<tag>
run=<run id>` (same rules as a run request) and hands it to the verify job, which downloads the signed attestation
from that run and checks it with tools/attestation.py. Nothing is run for tier 2.

Terms (the free run program): one free initial run once the row is listed, then queued reruns on new releases only
(never on every commit) for six months from consent (program_start to program_end in the row). After program_end
the queue refuses reruns; the row stays listed with its last result and goes stale. Self-runs with the Action stay
free and unlimited. Full results go to the project privately first: the runner seals the evidence to the maintainer's
key (age), the queue entry becomes 'sealed', and only after the maintainer has sent the full results privately does
a maintainer's `/x402-conformance publish slug=<slug> run=<run id>` comment release it (release, then publish).

A request comes from the project's notify hook (docs/templates/x402-conformance-notify.yml): a comment
`/x402-conformance run slug=<slug> ref=<tag> version=<v>` on its own "Add or update my row" issue, or a
repository_dispatch with the same fields (the weekly release check sends one too). enqueue accepts it only when
matrix/rows/<slug>.json exists, the project ticked the free program (consent.hook) and gave a public testnet
endpoint, the comment is on that row's own issue by the row's contact or the issue's author, and the repo (if given)
is the row's repo. The row's endpoint is always the one checked; nothing in the request can point the runner
elsewhere. The queue keeps one file per slug, matrix/queue/<slug>.json,
so a newer request replaces a waiting one, and a ref already run is not run again.

next picks the oldest waiting entry inside matrix/queue/caps.json: runs per day, hours between runs of one slug, and
no spend (max_testnet_spend_per_run must be 0: the runner sends unpaid requests only, so nothing is paid, signed on chain
or sent to a hosted facilitator or mainnet), and a pinned suite release. publish turns the run's evidence bundle
into the row through tools/row_from_evidence.py (the same refusals as every row) and regenerates the matrix; the
workflow then opens a pull request for review. Nothing merges automatically.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROWS = "matrix/rows"
CAPS = "matrix/queue/caps.json"
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
REF = re.compile(r"^(?!.*\.\.)[A-Za-z0-9][A-Za-z0-9._/+-]{0,99}$")
VERSION = re.compile(r"^[A-Za-z0-9._+-]{1,64}$")
LOGIN = re.compile(r"^[A-Za-z0-9-]{1,39}$")
COMMAND = re.compile(r"^/x402-conformance run((?: +[a-z]+=\S+)+) *$", re.M)
ATTEST = re.compile(r"^/x402-conformance attest((?: +[a-z]+=\S+)+) *$", re.M)
PIN = "matrix/queue/suite.json"
PUBLISH = re.compile(r"^/x402-conformance publish((?: +[a-z]+=\S+)+) *$", re.M)
SHA_ONLY = re.compile(r"^[0-9a-f]{7,40}$")


def ts(v: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(v.replace("Z", "+00:00"))


def load(path: str) -> dict[str, object] | None:
    return json.load(open(path, encoding="utf-8")) if os.path.isfile(path) else None


def save(path: str, doc: object) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
        f.write("\n")


def request(opt: dict[str, str], kind: str = "run") -> tuple[dict[str, str], list[str]]:
    if "--dispatch" in opt:
        raw = load(opt["--dispatch"]) or {}
        if str(raw.get("kind") or "run") != kind:
            return {}, [f"not a {kind} request"]
        fields = {k: str(raw.get(k, "")) for k in ("slug", "repo", "ref", "version", "run") if raw.get(k) is not None}
        return fields, []
    body = open(opt["--comment"], encoding="utf-8").read()
    m = (COMMAND if kind == "run" else ATTEST).search(body)
    if not m:
        return {}, [f"not a {kind} request: the comment needs a line /x402-conformance {kind} slug=... ref=..."]
    return dict(kv.split("=", 1) for kv in m.group(1).split()), []


def admit(opt: dict[str, str], root: str, kind: str) -> tuple[dict[str, str], dict[str, object], list[str]]:
    """The rules every request meets, run or attest."""
    req, bad = request(opt, kind)
    if bad:
        return req, {}, bad
    slug, ref = req.get("slug", ""), req.get("ref", "")
    if not SLUG.match(slug):
        return req, {}, ["slug missing or malformed"]
    if not REF.match(ref):
        return req, {}, ["ref missing or malformed: the release tag"]
    if SHA_ONLY.match(ref):
        return req, {}, ["reruns are for new releases only: ref must be the release tag, not a commit"]
    row = load(os.path.join(root, ROWS, f"{slug}.json"))
    if not row:
        return req, {}, [f"no listed row {slug}: add it with the Add or update my row form first"]
    consent = row.get("consent") or {}
    if not (isinstance(consent, dict) and consent.get("hook") and row.get("testnet_endpoint")):
        return req, {}, [f"{slug} is not in the free program: tick the notify hook and give a public testnet endpoint "
                         "in its row"]
    end = row.get("program_end")
    if not end or opt["--now"][:10] > str(end):
        return req, {}, [f"the free run program for {slug} ended on {end}: the row stays listed with its last result; "
                         "runs with the Action stay free and unlimited"]
    if req.get("repo") and f"https://github.com/{req['repo'].strip('/')}" != str(row.get("repo") or "").rstrip("/"):
        return req, {}, [f"repo {req['repo']} is not the repo of row {slug}"]
    if kind == "attest" and not (req.get("repo") and str(req.get("run", "")).isdigit()):
        return req, {}, ["an attest request needs repo=<owner/repo> and run=<the workflow run id>"]
    if "--comment" in opt:
        if opt.get("--issue-url") != row.get("source_issue"):
            return req, {}, [f"a {kind} request for {slug} must be a comment on its own issue, {row.get('source_issue')}"]
        allowed = {str(row.get("contact", "")).lstrip("@").lower(), opt.get("--issue-author", "").lower()} - {""}
        if opt.get("--author", "").lower() not in allowed:
            return req, {}, [f"only {', '.join(sorted(allowed))} can ask for a {kind} of {slug}"]
    return req, row, []


def enqueue(opt: dict[str, str], root: str) -> list[str]:
    req, row, bad = admit(opt, root, "run")
    if bad:
        return bad
    slug, ref = req["slug"], req["ref"]
    version = req.get("version", "")
    version = version if VERSION.match(version) else ref[:12]
    qpath = os.path.join(opt["--queue"], "matrix", "queue", f"{slug}.json")
    q = load(qpath) or {"slug": slug, "status": "new", "last_ref": None, "last_run_at": None}
    if q.get("last_ref") == ref and q.get("status") in ("sealed", "published", "running"):
        print(f"{slug}: {ref} already run or running; nothing queued")
        return []
    q.update({"status": "queued", "ref": ref, "version": version, "requested_at": opt["--now"],
              "source": "dispatch" if "--dispatch" in opt else "comment"})
    save(qpath, q)
    print(f"{slug}: queued {ref} ({version})")
    return []


def attest(opt: dict[str, str], root: str) -> dict[str, object] | None:
    """A tier-2 attestation to verify (not run). One verification per slug and release tag."""
    req, row, bad = admit(opt, root, "attest")
    for b in bad:
        print(f"run-queue: {b}")
    if bad:
        return None
    qpath = os.path.join(opt["--queue"], "matrix", "queue", f"{req['slug']}.json")
    q = load(qpath) or {"slug": req["slug"], "status": "new", "last_ref": None, "last_run_at": None}
    if q.get("attested_ref") == req["ref"] and q.get("attested_run") == req["run"]:
        print(f"{req['slug']}: the attestation of {req['ref']} (run {req['run']}) was already verified")
        return None
    q.update({"attested_ref": req["ref"], "attested_run": req["run"], "attest_requested_at": opt["--now"]})
    save(qpath, q)
    return {"slug": req["slug"], "repo": str(row["repo"]).removeprefix("https://github.com/"), "ref": req["ref"],
            "run": req["run"], "consent": row["source_issue"]}


def pick(opt: dict[str, str], root: str) -> dict[str, object] | None:
    caps = load(os.path.join(root, CAPS)) or {}
    if caps.get("max_testnet_spend_per_run", 1) != 0 or caps.get("max_testnet_spend_per_day", 1) != 0:
        print("caps allow spend: this runner only runs with zero spend; nothing picked")
        return None
    suite = load(os.path.join(root, PIN)) or {}
    if not suite.get("tag"):
        print("no suite release pinned (matrix/queue/suite.json): nothing picked")
        return None
    now = ts(opt["--now"])
    qdir = os.path.join(opt["--queue"], "matrix", "queue")
    entries = [load(os.path.join(qdir, n)) for n in sorted(os.listdir(qdir))] if os.path.isdir(qdir) else []
    entries = [e for e in entries if isinstance(e, dict) and "slug" in e]
    known = {e["slug"] for e in entries}
    rdir = os.path.join(root, ROWS)
    for n in sorted(os.listdir(rdir)) if os.path.isdir(rdir) else []:
        row = load(os.path.join(rdir, n)) if n.endswith(".json") else None
        if (row and row.get("slug") not in known and row.get("testnet_endpoint")
                and (row.get("consent") or {}).get("hook")  # type: ignore[union-attr]
                and not row.get("evidence") and row.get("program_end") and opt["--now"][:10] <= str(row["program_end"])):
            e = {"slug": row["slug"], "status": "queued", "ref": "", "version": row["version"], "source": "initial",
                 "requested_at": opt["--now"], "last_ref": None, "last_run_at": None}
            save(os.path.join(qdir, f"{row['slug']}.json"), e)
            entries.append(e)
    today = [e for e in entries if e.get("last_run_at") and ts(str(e["last_run_at"])).date() == now.date()]
    if len(today) >= int(caps.get("max_runs_per_day", 0)):  # type: ignore[call-overload]
        print("daily cap reached; nothing picked")
        return None
    gap = datetime.timedelta(hours=float(caps.get("min_hours_between_runs_per_slug", 24)))  # type: ignore[arg-type]
    ready = [e for e in entries if e.get("status") == "queued"
             and (not e.get("last_run_at") or now - ts(str(e["last_run_at"])) >= gap)]
    for e in sorted(ready, key=lambda e: str(e.get("requested_at"))):
        row = load(os.path.join(root, ROWS, f"{e['slug']}.json"))
        if (not row or not (row.get("consent") or {}).get("hook") or not row.get("testnet_endpoint")  # type: ignore[union-attr]
                or not row.get("program_end") or opt["--now"][:10] > str(row["program_end"])):
            e["status"] = "refused"
            save(os.path.join(qdir, f"{e['slug']}.json"), e)
            continue
        e["status"] = "running"
        save(os.path.join(qdir, f"{e['slug']}.json"), e)
        return {"slug": e["slug"], "repo": str(row["repo"]).removeprefix("https://github.com/"), "ref": e["ref"],
                "version": e["version"], "endpoint": row["testnet_endpoint"], "suite": suite["tag"],
                "interval": max(5, int(caps.get("min_probe_interval_s", 5))),  # type: ignore[call-overload]
                "consent": row["source_issue"],
                # R16a's unpaid HEAD is not a GET: sent only when the operator allowed it on the form (XC-110)
                "head": "true" if (row.get("consent") or {}).get("unpaid_head") is True else "false"}  # type: ignore[union-attr]
    return None


def publish(opt: dict[str, str], root: str) -> int:
    slug, ref, version = opt["--slug"], opt["--ref"], opt.get("--version", "")
    if not (SLUG.match(slug) and (ref == "" or REF.match(ref))):
        print("bad slug or ref")
        return 1
    rpath = os.path.join(root, ROWS, f"{slug}.json")
    row = load(rpath)
    if not row:
        print(f"no row {slug}")
        return 1
    p = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "row_from_evidence.py"), opt["--bundle"], "--row", slug,
                        "--consent", str(row["source_issue"]), "--root", root, "--update"], capture_output=True, text=True)
    print(p.stdout.strip())
    if p.returncode:
        return 1
    row["evidence"] = f"evidence/impl-matrix/{slug}"
    if row.get("tier") != "full-suite-self-hosted":  # a verified tier-2 attestation stays the row's tier and version
        row["tier"] = "external-verified"
        row["version"] = version if VERSION.match(version) else (ref[:12] or row["version"])
    save(rpath, row)
    return subprocess.run([sys.executable, os.path.join(ROOT, "tools", "matrix_rows.py"), "--write", "--root", root]).returncode


def finish(opt: dict[str, str]) -> int:
    qpath = os.path.join(opt["--queue"], "matrix", "queue", f"{opt['--slug']}.json")
    q = load(qpath)
    if not q:
        return 1
    q.update({"status": "sealed" if opt["--result"] == "ok" else opt["--result"], "last_run_at": opt["--now"],
              "last_ref": q.get("ref"), "run_id": opt.get("--run-id")})
    save(qpath, q)
    return 0


def release(opt: dict[str, str], root: str) -> dict[str, object] | None:
    """A maintainer's publish comment, after the full results reached the project privately."""
    caps = load(os.path.join(root, CAPS)) or {}
    if opt.get("--author", "").lower() not in [str(m).lower() for m in caps.get("maintainers", [])]:  # type: ignore[union-attr]
        print("run-queue: only a maintainer can publish a run")
        return None
    m = PUBLISH.search(open(opt["--comment"], encoding="utf-8").read())
    req = dict(kv.split("=", 1) for kv in m.group(1).split()) if m else {}
    slug, run_id = req.get("slug", ""), req.get("run", "")
    q = load(os.path.join(opt["--queue"], "matrix", "queue", f"{slug}.json")) if SLUG.match(slug) else None
    if not q or q.get("status") != "sealed" or str(q.get("run_id")) != run_id or not run_id.isdigit():
        print("run-queue: no sealed run with that slug and run id")
        return None
    q["status"] = "published"
    save(os.path.join(opt["--queue"], "matrix", "queue", f"{slug}.json"), q)
    return {"slug": slug, "run_id": run_id, "ref": q.get("ref") or "", "version": q.get("version") or ""}


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    keys = ("--queue", "--now", "--comment", "--issue-url", "--author", "--issue-author", "--dispatch", "--root",
            "--github-output", "--bundle", "--slug", "--ref", "--version", "--result", "--run-id")
    opt = {k: argv[argv.index(k) + 1] for k in keys if k in argv and argv.index(k) + 1 < len(argv)}
    root = os.path.abspath(opt.get("--root", ROOT))
    if argv[0] == "enqueue":
        bad = enqueue(opt, root)
        for b in bad:
            print(f"run-queue: {b}")
        return 1 if bad else 0
    if argv[0] == "next":
        e = pick(opt, root)
        if opt.get("--github-output"):
            with open(opt["--github-output"], "a", encoding="utf-8") as f:
                for k, v in (e or {"slug": ""}).items():
                    f.write(f"{k}={v}\n")
        print(json.dumps(e) if e else "queue: nothing to run")
        return 0
    if argv[0] == "release":
        r = release(opt, root)
        if opt.get("--github-output"):
            with open(opt["--github-output"], "a", encoding="utf-8") as f:
                for k, v in (r or {"slug": ""}).items():
                    f.write(f"{k}={v}\n")
        return 0 if r else 1
    if argv[0] == "attest":
        a = attest(opt, root)
        if opt.get("--github-output"):
            with open(opt["--github-output"], "a", encoding="utf-8") as f:
                for k, v in (a or {"slug": ""}).items():
                    f.write(f"{k}={v}\n")
        return 0 if a else 1
    if argv[0] == "publish":
        return publish(opt, root)
    if argv[0] == "finish":
        return finish(opt)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
