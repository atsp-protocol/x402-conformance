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

When the project runs the vendor workflow (docs/templates/x402-conformance.yml, saved in its repo as
.github/workflows/x402-conformance.yml), the newest successful run's evidence artifact
`x402-conformance-evidence-<slug>` is downloaded and goes through tools/row_from_evidence.py with the row's consent
issue, so the same refusals apply (testnet or devnet only, facilitator on loopback, nothing paid live). The version
tested becomes the release tag when the run's commit is that tag's commit, else the short commit.

Free run program: a row whose program started five months ago or more and has no program_notice gets one (today),
and its slug, contact, issue and program_end are written as a JSON line to --notices FILE; the workflow opens the
renewal heads-up issue from it. After program_end the row stays listed with its last result and goes stale
(tools/matrix_rows.py); nothing is deleted.

--facts FILE replaces the API with a JSON object {slug: {latest, latest_commit, default_branch_commit, run, readme}} (used by
the tests). The tool writes the rows and leaves the commit and the pull request to the workflow.
"""
from __future__ import annotations

import datetime
import io
import json
import os
import re
import shutil
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
    runs = gh(f"{base}/actions/workflows/x402-conformance.yml/runs?status=success&per_page=1")
    run = None
    if isinstance(runs, dict) and runs.get("workflow_runs"):
        r0 = runs["workflow_runs"][0]
        arts = gh(f"{base}/actions/runs/{r0['id']}/artifacts")
        want = f"x402-conformance-evidence-{row['slug']}"
        art = next((a for a in (arts or {}).get("artifacts", []) if a.get("name") == want and not a.get("expired")), None)  # type: ignore[union-attr]
        if art and int(art.get("size_in_bytes", 0)) <= MAX_ZIP:
            run = {"head_sha": r0.get("head_sha"), "created_at": r0.get("created_at"),
                   "zip": gh(f"{base}/actions/artifacts/{art['id']}/zip", raw=True)}
    return {"latest": latest, "latest_commit": tc.get("sha") if isinstance(tc, dict) else None,
            "default_branch_commit": head.get("sha") if isinstance(head, dict) else None, "run": run,
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
    """Unzip an evidence artifact: flat files only, no path outside dest, bounded size."""
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
        if name not in ("run.json", "README.md", "SHA256SUMS"):
            continue
        with open(os.path.join(dest, name), "wb") as f:
            f.write(z.read(info))
    return os.path.isfile(os.path.join(dest, "run.json"))


def ingest(row: dict[str, object], facts: dict[str, object], root: str) -> str:
    run = facts.get("run")
    if not isinstance(run, dict) or not run.get("zip"):
        return "no vendor run"
    bundle = tempfile.mkdtemp()
    try:
        blob = run["zip"] if isinstance(run["zip"], bytes) else open(str(run["zip"]), "rb").read()
        if not unpack(blob, bundle):
            return "vendor artifact has no run.json"
        p = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "row_from_evidence.py"), bundle,
                            "--row", str(row["slug"]), "--consent", str(row["source_issue"]), "--root", root, "--update"],
                           capture_output=True, text=True)
        if p.returncode:
            return "vendor evidence refused: " + p.stdout.strip().replace("\n", "; ")
    finally:
        shutil.rmtree(bundle, True)
    sha = str(run.get("head_sha") or "")
    row["evidence"] = f"evidence/impl-matrix/{row['slug']}"
    if facts.get("latest") and sha and sha == facts.get("latest_commit"):
        row["version"] = str(facts["latest"]).lstrip("v")
    elif sha:
        row["version"] = sha[:12]
    return "vendor evidence updated"


def main(argv: list[str]) -> int:
    keys = ("--root", "--today", "--facts", "--notices")
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
        note = ingest(row, facts, root)
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
