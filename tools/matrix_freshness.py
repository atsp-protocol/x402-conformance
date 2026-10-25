#!/usr/bin/env python3
"""Freshness for listed projects (XC-96): run weekly by .github/workflows/matrix-freshness.yml.

    python3 tools/matrix_freshness.py --today YYYY-MM-DD [--root DIR] [--facts FILE] [--notices FILE]

For each matrix/rows/<slug>.json whose repo is on github.com it reads, through the GitHub API only (`gh api`, no
request to any x402 endpoint): the latest release (or the newest tag when there is none), its commit, and the
default-branch commit. It records them in the row's `release` (checked_at, latest, default_branch_commit,
behind_since), which tools/matrix_rows.py turns into the release-alignment column and the badge (current, behind,
stale after 30 days).

It also reads the project's public README through the API (a plain read, no referrer, nothing embedded) and records
readme_badge: true when it links the row or the badge, false when it does not, which flags the row.

Two tiers (XC-98), a backstop for the notify hook:
  - tier 1: when the latest release is not the version tested and the row is in the free program with a testnet
    endpoint, a request {slug, repo, ref, version} is written as a JSON line to --requests FILE; the workflow sends
    each as a repository_dispatch to the run queue, which runs the external checks.
  - tier 2: when the project runs the vendor workflow (docs/templates/x402-conformance.yml, saved in its repo as
    .github/workflows/x402-conformance.yml) with attest: true, the newest successful run's artifact
    `x402-conformance-attestation-<slug>` is downloaded, its signature checked with `gh attestation verify` and the
    result goes through tools/attestation.py (the same refusals as the run queue). Nothing is run.

Free run program: a row whose program started five months ago or more and has no program_notice gets one (today),
and its slug, contact, issue and program_end are written as a JSON line to --notices FILE; the workflow opens the
renewal heads-up issue from it. After program_end the row stays listed with its last result and goes stale
(tools/matrix_rows.py); nothing is deleted.

--facts FILE replaces the API with a JSON object {slug: {latest, latest_commit, default_branch_commit, attest, readme}}
(used by the tests; attest is {file, gh_json}). The tool writes the rows and leaves the commit and the pull request
to the workflow.
"""
from __future__ import annotations

import datetime
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from matrix_rows import add_months  # noqa: E402

ROWS = "matrix/rows"
GH_REPO = re.compile(r"^https://github\.com/([A-Za-z0-9-]{1,39})/([A-Za-z0-9._-]{1,100})/?$")
MAX_ZIP = 5 * 1024 * 1024
PAGES = "https://atsp-protocol.github.io/x402-conformance"
ATT = "x402-conformance-attestation.json"


def gh(path: str, raw: bool = False) -> object:
    p = subprocess.run(["gh", "api", "-H", "Accept: application/vnd.github+json", path], capture_output=True)
    if p.returncode:
        return None
    return p.stdout if raw else json.loads(p.stdout or b"null")


def facts_from_api(row: dict[str, object]) -> dict[str, object] | None:
    m = GH_REPO.match(str(row.get("repo") or ""))
    if not m:
        return None
    base = f"repos/{m.group(1)}/{m.group(2)}"
    repo = gh(base)
    if not isinstance(repo, dict):
        return None
    rel = gh(f"{base}/releases/latest")
    latest = rel.get("tag_name") if isinstance(rel, dict) else None
    if not latest:
        tags = gh(f"{base}/tags?per_page=1")
        latest = tags[0]["name"] if isinstance(tags, list) and tags else None
    tc = gh(f"{base}/commits/{latest}") if latest else None
    head = gh(f"{base}/commits/{repo.get('default_branch')}")
    readme = subprocess.run(["gh", "api", "-H", "Accept: application/vnd.github.raw", f"{base}/readme"], capture_output=True)
    runs = gh(f"{base}/actions/workflows/x402-conformance.yml/runs?status=success&event=release&per_page=1")
    attest = None
    if isinstance(runs, dict) and runs.get("workflow_runs"):
        r0 = runs["workflow_runs"][0]
        arts = gh(f"{base}/actions/runs/{r0['id']}/artifacts")
        want = f"x402-conformance-attestation-{row['slug']}"
        art = next((a for a in (arts or {}).get("artifacts", []) if a.get("name") == want and not a.get("expired")), None)  # type: ignore[union-attr]
        if art and int(art.get("size_in_bytes", 0)) <= MAX_ZIP:
            blob = gh(f"{base}/actions/artifacts/{art['id']}/zip", raw=True)
            d = tempfile.mkdtemp()
            if isinstance(blob, bytes) and unpack(blob, d):
                f = os.path.join(d, ATT)
                v = subprocess.run(["gh", "attestation", "verify", f, "--repo", f"{m.group(1)}/{m.group(2)}",
                                    "--format", "json"], capture_output=True)
                with open(os.path.join(d, "verify.json"), "wb") as g:
                    g.write(v.stdout if v.returncode == 0 else b"[]")
                attest = {"file": f, "gh_json": os.path.join(d, "verify.json")}
    return {"latest": latest, "latest_commit": tc.get("sha") if isinstance(tc, dict) else None,
            "default_branch_commit": head.get("sha") if isinstance(head, dict) else None, "attest": attest,
            "readme": readme.stdout.decode("utf-8", "replace") if readme.returncode == 0 else None}


def release(prev: object, version: str, latest: str | None, head: str | None, today: str) -> dict[str, object]:
    """The row's release record: behind_since keeps the first day the version tested fell behind the latest release."""
    behind = bool(latest) and str(latest).lower().lstrip("v") != str(version).lower().lstrip("v")
    since = prev.get("behind_since") if isinstance(prev, dict) else None
    return {"checked_at": today, "latest": latest, "default_branch_commit": head[:40] if head else None,
            "behind_since": (since or today) if behind else None}


def readme_badge(readme: object, slug: str) -> bool | None:
    """Whether the public README links the project's row or badge (a plain read of the README; nothing is embedded)."""
    if not isinstance(readme, str):
        return None
    return f"{PAGES}/matrix/#{slug}" in readme or f"{PAGES}/badge/{slug}.svg" in readme


def unpack(blob: bytes, dest: str) -> bool:
    """Unzip an attestation artifact: the one flat file only, no path outside dest, bounded size."""
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        return False
    total = 0
    for info in z.infolist():
        name = info.filename.split("/")[-1]
        total += info.file_size
        if info.is_dir() or not name or name.startswith(".") or total > MAX_ZIP:
            continue
        if name != ATT:
            continue
        with open(os.path.join(dest, name), "wb") as f:
            f.write(z.read(info))
    return os.path.isfile(os.path.join(dest, ATT))


def ingest(row: dict[str, object], facts: dict[str, object], root: str, today: str) -> str:
    """Tier 2: verify the attestation of the project's newest release run of the full suite. Nothing is run."""
    a = facts.get("attest")
    if not isinstance(a, dict) or not a.get("file"):
        return "no attested full-suite run"
    p = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "attestation.py"), "verify", "--file", str(a["file"]),
                        "--gh-json", str(a.get("gh_json") or "-"), "--slug", str(row["slug"]), "--now", today,
                        "--root", root, "--apply"], capture_output=True, text=True)
    if p.returncode:
        return "attestation refused: " + p.stdout.strip().replace("\n", "; ")
    fresh = json.load(open(os.path.join(root, ROWS, f"{row['slug']}.json"), encoding="utf-8"))
    for k in ("attestation", "tier", "version"):
        row[k] = fresh[k]
    return "attestation verified"


def rerun(row: dict[str, object], latest: object, today: str) -> dict[str, object] | None:
    """Tier 1: a new release of a row in the free program asks the run queue for an external rerun."""
    if not latest or str(latest).lower().lstrip("v") == str(row["version"]).lower().lstrip("v"):
        return None
    if not ((row.get("consent") or {}).get("hook") and row.get("testnet_endpoint")  # type: ignore[union-attr]
            and row.get("program_end") and today <= str(row["program_end"])):
        return None
    m = GH_REPO.match(str(row.get("repo") or ""))
    return {"slug": row["slug"], "repo": f"{m.group(1)}/{m.group(2)}" if m else "", "ref": str(latest),
            "version": str(latest).lstrip("v")} if m else None


def main(argv: list[str]) -> int:
    keys = ("--root", "--today", "--facts", "--notices", "--requests")
    opt = {k: argv[argv.index(k) + 1] for k in keys if k in argv and argv.index(k) + 1 < len(argv)}
    root = os.path.abspath(opt.get("--root", ROOT))
    today = opt.get("--today") or datetime.date.today().isoformat()
    datetime.date.fromisoformat(today)
    given = json.load(open(opt["--facts"], encoding="utf-8")) if "--facts" in opt else None
    d = os.path.join(root, ROWS)
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not name.endswith(".json"):
            continue
        p = os.path.join(d, name)
        row = json.load(open(p, encoding="utf-8"))
        facts = given.get(row["slug"]) if given is not None else facts_from_api(row)
        if not isinstance(facts, dict):
            print(f"{row['slug']}: no GitHub repository to check")
            continue
        note = ingest(row, facts, root, today)
        req = rerun(row, facts.get("latest"), today)
        if req and opt.get("--requests"):
            with open(opt["--requests"], "a", encoding="utf-8") as f:
                f.write(json.dumps(req) + "\n")
            note += f"; external rerun of {req['ref']} requested"
        row["release"] = release(row.get("release"), str(row["version"]), facts.get("latest"),  # type: ignore[arg-type]
                                 facts.get("default_branch_commit"), today)  # type: ignore[arg-type]
        row["release"]["readme_badge"] = readme_badge(facts.get("readme"), str(row["slug"]))
        start = row.get("program_start")
        if start and not row.get("program_notice") and today >= add_months(str(start), 5):
            row["program_notice"] = today
            if opt.get("--notices"):
                with open(opt["--notices"], "a", encoding="utf-8") as f:
                    f.write(json.dumps({"slug": row["slug"], "contact": row["contact"], "issue": row["source_issue"],
                                        "program_end": row.get("program_end")}) + "\n")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(row, f, indent=1, ensure_ascii=False)
            f.write("\n")
        flag = {True: "README shows the badge", False: "README badge missing (flagged)", None: "README not read"}
        print(f"{row['slug']}: latest {row['release']['latest']}, tested {row['version']}; {note}; "
              f"{flag[row['release']['readme_badge']]}")
    return subprocess.run([sys.executable, os.path.join(ROOT, "tools", "matrix_rows.py"), "--write", "--root", root]).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
