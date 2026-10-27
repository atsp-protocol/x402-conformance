#!/usr/bin/env python3
"""Project rows of the matrix, from the 'Add or update my row' issue form (XC-96).

    python3 tools/matrix_rows.py --from-issue FILE --issue-url URL [--root DIR] [--github-output FILE]
        parse an issue body written by .github/ISSUE_TEMPLATE/matrix-row.yml, validate it against
        matrix/schema/row.schema.json and the public-safe rules below, and write matrix/rows/<slug>.json and the
        regenerated docs/MATRIX.md. With evidence JSON in the issue, the run goes through tools/row_from_evidence.py
        first (the same refusals) and becomes evidence/impl-matrix/<slug>/. Exit 1, writing nothing, on any problem.
    python3 tools/matrix_rows.py --write [--root DIR]    regenerate the listed-projects table in docs/MATRIX.md
    python3 tools/matrix_rows.py --check [--root DIR]    exit 1 when a row file breaks the schema or the rules, the
                                                         table is stale or hand-edited, or docs/MATRIX.md's own text
                                                         (headers and prose, not project names) has score, rank or
                                                         certification wording

Public-safe rules, on top of the schema: all three consents ticked (listing, CC BY 4.0 for public results, testnet-only
probes), no email address anywhere, no secret-looking value (a 64-hex string, a key or a mnemonic), only https links,
and a contact that is a public handle. The table never shows a score or a rank: environment, passed/run and the
failed count come only from committed evidence, and every row links the form to add or update it.
"""
from __future__ import annotations

import datetime
import html
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from x402conf import tiers as T  # noqa: E402
from x402conf.discovery import Validator  # noqa: E402

SCHEMA = "matrix/schema/row.schema.json"
ROWS = "matrix/rows"
MD_OUT = "docs/MATRIX.md"
COMPAT = "docs/compat-matrix.json"
PAGE_DIR = "docs/site/matrix"
BADGES = "docs/site/badge"
STALE_DAYS = 30
PIN = "matrix/queue/suite.json"
PROGRAM_MONTHS = 6
NOTICE_MONTHS = 5
START, END = "<!-- matrix-rows:start -->", "<!-- matrix-rows:end -->"
REPO = "https://github.com/atsp-protocol/x402-conformance"
FORM = f"{REPO}/issues/new?template=matrix-row.yml"
PAGES = "https://atsp-protocol.github.io/x402-conformance"
TYPES = {"facilitator (self-hosted)": "facilitator-self-hosted", "facilitator (hosted)": "facilitator-hosted",
         "sdk": "sdk", "merchant / paid api": "merchant-paid-api", "client / wallet": "client-wallet", "mcp tool": "mcp-tool"}
LABELS = {
    "project": "Project name", "type": "Type", "repo": "Repository URL", "site": "Docs or site URL",
    "languages": "Languages", "chains": "Chain families", "networks": "Networks (CAIP-2 ids)",
    "environments": "Environments you offer", "testnet_endpoint": "Testnet endpoint URL (if any)",
    "version": "Version or commit", "evidence": "Full-suite run with an attestation (optional)",
    "contact": "Public contact handle", "consent": "Consent",
}
RUN_URL = re.compile(r"^https://github\.com/([\w.-]+/[\w.-]+)/actions/runs/([0-9]{1,20})/?$")
CONSENTS = {"listing": "list this project", "data_license": "CC BY 4.0", "testnet_only": "testnet-only probes",
            "badge": "Display the badge in our README with attribution to Optitransfer/x402-conformance"}
HOOK = ("Free run program", "Install the notify hook")
UNPAID_HEAD = "also allow one unpaid HEAD request per tier-1 run"  # R16a off loopback needs the operator's permission
WORDING = re.compile(r"(?i)\bcertified\b|\boverall score\b|\brank(ed|ing)?\b|\b[0-9]{1,3}\s*/\s*100\b|\bscore\s*:")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
SECRET = re.compile(r"(?i)\b[0-9a-f]{64}\b|-----BEGIN|\bmnemonic\b|\bseed phrase\b|\bprivate key\b|\bsk_live_")


def sections(body: str) -> dict[str, str]:
    """The issue form's rendering: '### <label>' then the answer; an empty answer is '_No response_'."""
    out: dict[str, str] = {}
    parts = re.split(r"^### +(.+?)\s*$", body.replace("\r\n", "\n"), flags=re.M)
    for i in range(1, len(parts) - 1, 2):
        v = parts[i + 1].strip()
        out[parts[i].strip()] = "" if v == "_No response_" else v
    return out


def items(v: str) -> list[str]:
    return [x.strip() for x in re.split(r"[,\n]", v) if x.strip()]


def slug(name: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", name.lower())).strip("-")[:63]


def own_text(md: str) -> str:
    """docs/MATRIX.md without the values that come from projects: table body rows are dropped (their cells are project
    names, links, handles, versions and generated counts) and table headers and prose are kept. The wording rule
    applies to this text, so a project called, say, agent-score is listed under its own name without tripping it."""
    out, prev_table = [], False
    for line in md.splitlines():
        is_table = line.lstrip().startswith("|")
        if is_table and prev_table and not re.match(r"^\s*\|[\s:|-]+\|\s*$", line):
            prev_table = True
            continue
        out.append(line)
        prev_table = is_table
    return "\n".join(out)


def wording(md: str) -> list[str]:
    return [f"{MD_OUT} has score, rank or certification wording in its own text: {m.group(0)!r}"
            for m in WORDING.finditer(own_text(md))]


def add_months(day: str, n: int) -> str:
    d = datetime.date.fromisoformat(day)
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    last = (datetime.date(y + (m == 12), m % 12 + 1, 1) - datetime.timedelta(days=1)).day
    return datetime.date(y, m, min(d.day, last)).isoformat()


def from_issue(body: str, issue_url: str, today: str = "") -> tuple[dict[str, object], str, list[str]]:
    """The row, the link to a full-suite run with an attestation (if any), and the problems found reading the form."""
    s = sections(body)
    bad: list[str] = []
    for key, label in LABELS.items():
        if label not in s and key not in ("evidence", "testnet_endpoint", "site", "start", "path"):
            bad.append(f"the form has no '{label}' section")
    ticked = {k: bool(re.search(r"^- \[[xX]\] .*" + re.escape(w), s.get(LABELS["consent"], ""), re.M | re.I))
              for k, w in CONSENTS.items()}
    for k, ok in ticked.items():
        if not ok:
            bad.append(f"consent not given: '{CONSENTS[k]}' must be ticked; nothing is listed without it")
    ticked["hook"] = bool(re.search(r"^- \[[xX]\] .*" + re.escape(HOOK[1]), s.get(HOOK[0], ""), re.M | re.I))
    ticked["unpaid_head"] = bool(re.search(r"^- \[[xX]\] .*" + re.escape(UNPAID_HEAD), s.get(HOOK[0], ""), re.M | re.I))
    endpoint = s.get(LABELS["testnet_endpoint"], "").strip()
    envs = items(s.get(LABELS["environments"], ""))
    if ticked["hook"] and not (endpoint and "testnet" in envs):
        bad.append("the free run program runs the external checks against your public testnet endpoint: give its URL "
                   "and offer testnet")
    t = s.get(LABELS["type"], "").strip().lower()
    evidence = s.get(LABELS["evidence"], "").strip()
    repo = s.get(LABELS["repo"], "").strip().rstrip("/")
    m = RUN_URL.match(evidence)
    if evidence and not (m and f"https://github.com/{m.group(1)}" == repo):
        bad.append("the full-suite run must be a link to a workflow run in your own repository, "
                   "https://github.com/<owner>/<repo>/actions/runs/<id>, that ran the Action with attest: true")
    row: dict[str, object] = {
        "schema": "x402-conformance.matrix-row/1",
        "slug": slug(s.get(LABELS["project"], "")),
        "project": s.get(LABELS["project"], "").strip(),
        "type": TYPES.get(t, t),
        "repo": s.get(LABELS["repo"], "").strip() or None,
        "site": s.get(LABELS["site"], "").strip() or None,
        "languages": items(s.get(LABELS["languages"], "")),
        "chains": items(s.get(LABELS["chains"], "")),
        "networks": items(s.get(LABELS["networks"], "")),
        "environments": items(s.get(LABELS["environments"], "")),
        "testnet_endpoint": s.get(LABELS["testnet_endpoint"], "").strip() or None,
        "version": s.get(LABELS["version"], "").strip(),
        "contact": s.get(LABELS["contact"], "").strip(),
        "consent": ticked,
        "source_issue": issue_url,
        "evidence": None, "tier": None, "attestation": None,
        "program_start": None, "program_end": None,
    }
    if ticked["hook"]:
        day = today or datetime.date.today().isoformat()
        row["program_start"], row["program_end"] = day, add_months(day, PROGRAM_MONTHS)
    return row, evidence, bad


def problems(row: object, root: str) -> list[str]:
    schema = json.load(open(os.path.join(root, SCHEMA), encoding="utf-8"))
    bad = Validator(schema).validate(row)
    text = json.dumps(row)
    if EMAIL.search(text):
        bad.append("an email address: use a public handle; the matrix never shows emails")
    if SECRET.search(text):
        bad.append("something that looks like a secret (a 64-hex value, a key or a mnemonic): remove it")
    if isinstance(row, dict):
        if row.get("environments") and "mainnet-only" in row["environments"] and len(row["environments"]) > 1:
            bad.append("environments: mainnet-only cannot be combined with testnet or devnet")
        if row.get("tier") == T.TIER2 and not row.get("attestation"):
            bad.append("tier 2 (Full suite (self-hosted)) needs a verified attestation in matrix/attestations/")
        if row.get("tier") == T.TIER1 and not row.get("evidence"):
            bad.append("tier 1 (External-verified) needs the run queue's evidence")
    return bad


def load_rows(root: str) -> tuple[list[dict[str, object]], list[str]]:
    d = os.path.join(root, ROWS)
    out, bad = [], []
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not name.endswith(".json"):
            continue
        try:
            r = json.load(open(os.path.join(d, name), encoding="utf-8"))
        except ValueError:
            bad.append(f"{ROWS}/{name}: not JSON")
            continue
        bad += [f"{ROWS}/{name}: {p}" for p in problems(r, root)]
        if isinstance(r, dict) and r.get("slug") != name[:-5]:
            bad.append(f"{ROWS}/{name}: slug {r.get('slug')!r} does not match the file name")
        out.append(r)
    return out, bad


def environment(r: dict[str, object], run: dict[str, object] | None) -> str:
    if run:
        return str(run.get("environment") or "devnet")
    envs = r.get("environments") or []
    if r.get("type") == "facilitator-hosted":
        return "out-of-reach"
    if envs == ["mainnet-only"]:
        return "live-not-run"
    return "testnet" if "testnet" in envs else "devnet"


def compat_rows(root: str) -> dict[str, dict[str, object]]:
    p = os.path.join(root, COMPAT)
    return {str(r["row"]): r for r in json.load(open(p, encoding="utf-8"))["rows"]} if os.path.isfile(p) else {}


def run_of(r: dict[str, object], compat: dict[str, dict[str, object]]) -> dict[str, object] | None:
    ev = str(r.get("evidence") or "")
    return compat.get(ev.rsplit("/", 1)[-1]) if ev else None


def norm(v: object) -> str:
    return str(v or "").strip().lower().lstrip("v")


def days(a: str, b: str) -> int:
    return (datetime.date.fromisoformat(b[:10]) - datetime.date.fromisoformat(a[:10])).days


def alignment(version: str, last_run: str | None, release: object, program_end: object = None) -> tuple[str, bool]:
    """Release alignment, and whether the row is stale. It is computed only from what is committed (the run date and
    the release check tools/matrix_freshness.py records), never from today's date, so the output is reproducible.
    current: the version tested is the latest release. behind (vX tested, vY latest): it is not. stale: no run within
    STALE_DAYS of the last release check, or behind for STALE_DAYS or more."""
    if not last_run:
        return "not run yet", False
    if not isinstance(release, dict) or not release.get("checked_at"):
        return "not checked yet", False
    checked = str(release["checked_at"])
    if program_end and checked > str(program_end) and last_run[:10] <= str(program_end):
        return f"stale (free run program ended {program_end})", True
    latest = release.get("latest")
    behind = bool(latest) and norm(latest) != norm(version)
    since = str(release.get("behind_since") or checked)
    if days(last_run, checked) > STALE_DAYS or (behind and days(since, checked) >= STALE_DAYS):
        return (f"stale (v{norm(version)} tested, v{norm(latest)} latest)" if behind else "stale"), True
    if behind:
        return f"behind (v{norm(version)} tested, v{norm(latest)} latest)", False
    return ("current" if latest else "current (no release published; default branch tested)"), False


def pin(root: str) -> dict[str, object]:
    p = os.path.join(root, PIN)
    return json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else {}


def tag_of(version: object) -> str:
    v = norm(version)
    return f"v{v}" if v else "untagged"


def badge_text(tier: str, suite_tag: str, passed: object, applicable: object, day: object,
               stale: bool, rerun: bool) -> tuple[str, str]:
    """The two halves of a row's badge. Left: the tier, the suite tag and Optitransfer. Right: checks passed out of
    applicable checks and the date, or grey 'stale' / 'rerun on current suite'."""
    left = f"{T.TIER_LABEL[tier]} \u00b7 x402-conformance {suite_tag} \u00b7 Optitransfer"
    right = ("rerun on current suite" if rerun else "stale" if stale else f"{passed}/{applicable} checks \u00b7 {day}")
    return left, right


def badge_svg(slug: str, left: str, right: str, grey: bool, example: bool = False) -> str:
    """No script, no remote resource, no logo; the link goes to the project's row on the Pages matrix."""
    lw, rw = 6 * len(left) + 14, 6 * len(right) + 14
    color = "#9e9e9e" if grey else "#2e7d32"
    href = f"{PAGES}/matrix/#{slug}"
    title = f"{left}: {slug}, {right}" + (" (example, not a real result)" if example else "")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{lw + rw}" '
            f'height="20" role="img" aria-label="{html.escape(left)}: {html.escape(right)}">\n'
            f'<title>{html.escape(title)}</title>\n<a xlink:href="{href}" href="{href}">\n'
            f'<rect width="{lw}" height="20" fill="#555"/>\n<rect x="{lw}" width="{rw}" height="20" fill="{color}"/>\n'
            f'<g fill="#fff" font-family="Verdana,DejaVu Sans,sans-serif" font-size="11" text-anchor="middle">\n'
            f'<text x="{lw // 2}" y="14">{html.escape(left)}</text>\n'
            f'<text x="{lw + rw // 2}" y="14">{html.escape(right)}</text>\n</g>\n</a>\n</svg>\n')


ALT = "Tested with x402-conformance \u00b7 Optitransfer"


def snippets(slug: str) -> tuple[str, str]:
    """Copy-paste README snippets for one row: Markdown and HTML, each the badge plus the attribution line. The badge
    image itself shows the tier, so the snippet stays the same when a row moves from tier 1 to tier 2."""
    img, row = f"{PAGES}/badge/{slug}.svg", f"{PAGES}/matrix/#{slug}"
    md = f"[![{ALT}]({img})]({row}) Conformance tested by [Optitransfer/x402-conformance]({row})"
    h = (f'<a href="{row}"><img src="{img}" alt="{ALT}"></a> '
         f'Conformance tested by <a href="{row}">Optitransfer/x402-conformance</a>')
    return md, h


EXAMPLE = {
    "slug": "example", "project": "example-org/example-x402-server", "type": "merchant-paid-api",
    "repo": None, "site": None, "languages": ["TypeScript"], "chains": ["EVM"],
    "networks": ["eip155:84532"], "environment": "testnet", "tier": T.TIER1, "tier_label": T.TIER_LABEL[T.TIER1],
    "version": "1.4.0", "contact": "@example-org", "suite_tag": "v1.7.0", "suite_status": "current",
    "checks_passed": 8, "checks_applicable": 9, "failed_count": 1, "exercised": 9, "not_applicable": 2,
    "needs_self_hosted": 68, "na_reasons": {"P9": T.EXTERNAL_NA["P9"], "P10": T.EXTERNAL_NA["P10"]},
    "last_run": "2026-10-20", "release_alignment": "behind (v1.4.0 tested, v1.5.0 latest)", "stale": False,
    "readme_badge": "shown", "free_run": True, "program_end": "2027-04-20",
    "evidence": "evidence/impl-matrix/<slug>/run.json", "example": True,
}
EXAMPLE_LABEL = "Example (illustrative, not a real result)"


def results_of(r: dict[str, object], run: dict[str, object] | None, root: str) -> tuple[str | None, dict[str, object]]:
    """The row's tier and what its committed results say. Tier 2 comes only from a verified attestation in
    matrix/attestations/, tier 1 only from the run queue's external run in evidence/impl-matrix/."""
    att = os.path.join(root, str(r.get("attestation") or "-"))
    if r.get("tier") == T.TIER2 and os.path.isfile(att):
        doc = json.load(open(att, encoding="utf-8"))
        a = doc["attestation"]
        res = a["results"]
        return T.TIER2, {"counts": T.denominator(res, T.TIER2), "last_run": str(a.get("generated_at") or "")[:10],
                         "suite_tag": tag_of(a["suite"].get("version")), "suite_status": doc.get("suite_status"),
                         "na": {k: v.get("reason") for k, v in res.items() if v.get("status") == "not_applicable"},
                         "evidence": f"{REPO}/blob/main/{r['attestation']}"}
    if run:
        p = os.path.join(root, str(run["run"]))
        res = T.tier1_results(T.results_from_run(p)) if os.path.isfile(p) else {}
        doc = json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else {}
        version = ((doc.get("versions") or {}).get("x402-conformance") if isinstance(doc, dict) else None)
        st = "current" if pin(root).get("version") and norm(version) == norm(pin(root).get("version")) \
            else "rerun on current suite"
        return T.TIER1, {"counts": T.denominator(res, T.TIER1), "last_run": str(run.get("run_at") or "")[:10],
                         "suite_tag": tag_of(version), "suite_status": st,
                         "na": {k: v.get("reason") for k, v in res.items() if v.get("status") == "not_applicable"},
                         "evidence": f"{REPO}/blob/main/{run['run']}"}
    return None, {}


def view(rows: list[dict[str, object]], root: str) -> list[dict[str, object]]:
    """What is published for each accepted row: its public fields, its tier and the counts from its results."""
    compat = compat_rows(root)
    out = []
    for r in rows:
        run = run_of(r, compat)
        tier, got = results_of(r, run, root)
        c = got.get("counts") or {}
        last = str(got.get("last_run") or "") or None
        align, stale = alignment(str(r["version"]), last, r.get("release"), r.get("program_end"))
        out.append({
            "slug": r["slug"], "project": r["project"], "type": r["type"], "repo": r.get("repo"), "site": r.get("site"),
            "languages": r.get("languages") or [], "chains": r.get("chains") or [], "networks": r.get("networks") or [],
            "environment": environment(r, run), "tier": tier, "tier_label": T.TIER_LABEL.get(str(tier), "not run yet"),
            "version": r["version"], "contact": r["contact"],
            "suite_tag": got.get("suite_tag"), "suite_status": got.get("suite_status"),
            "checks_passed": c.get("passed"), "checks_applicable": c.get("applicable"),  # type: ignore[union-attr]
            "failed_count": c.get("failed"), "exercised": c.get("exercised"),  # type: ignore[union-attr]
            "not_applicable": c.get("not_applicable"), "needs_self_hosted": c.get("needs_self_hosted"),  # type: ignore[union-attr]
            "na_reasons": got.get("na") or {}, "last_run": last,
            "release_alignment": align, "stale": stale, "readme_badge": readme_flag(r.get("release")),
            "free_run": bool((r.get("consent") or {}).get("hook")),  # type: ignore[union-attr]
            "program_end": r.get("program_end"),
            "evidence": got.get("evidence"),
            "badge": f"{PAGES}/badge/{r['slug']}.svg" if tier else None,
            "source_issue": r["source_issue"],
        })
    return out


def readme_flag(release: object) -> str:
    v = release.get("readme_badge") if isinstance(release, dict) else None
    return "shown" if v is True else "missing (flagged)" if v is False else "not checked yet"


def counts(vs: list[dict[str, object]], key: str) -> str:
    c: dict[str, int] = {}
    for v in vs:
        vals = v[key] if isinstance(v[key], list) else [v[key]]
        for x in vals or ["none"]:
            c[str(x)] = c.get(str(x), 0) + 1
    return ", ".join(f"{k} {n}" for k, n in sorted(c.items())) or "none yet"


def denom(v: dict[str, object]) -> str:
    return f"{v['exercised']} exercised / {v['not_applicable']} NA / {v['needs_self_hosted']} needs self-hosted"


def suite_cell(v: dict[str, object]) -> str:
    return f"{v['suite_tag']}" + ("" if v.get("suite_status") == "current" else " (rerun on current suite)")


def md_row(v: dict[str, object]) -> str:
    md, _ = snippets(str(v["slug"]))
    if v.get("example"):
        name, last = f"**{EXAMPLE_LABEL}:** {v['project']}", f"{v['last_run']}: `{v['evidence']}`"
    else:
        link = v.get("repo") or v.get("site")
        name = f"[{v['project']}]({link})" if link else str(v["project"])
        last = f"[{v['last_run']}]({v['evidence']})"
    return (f"| <a id=\"project-{v['slug']}\"></a>{name} | {v['type']} | {v['tier_label']} | {v['environment']} | "
            f"{v['version']} | {v['release_alignment']} | {v['checks_passed']}/{v['checks_applicable']} | "
            f"{v['failed_count']} | {denom(v)} | {suite_cell(v)} | {last} | "
            f"{v['readme_badge']} | `{md}` | [add or update]({FORM}) |")


def example_badge() -> tuple[str, str]:
    e = EXAMPLE
    return badge_text(T.TIER1, str(e["suite_tag"]), e["checks_passed"], e["checks_applicable"], e["last_run"], False, False)


def table(rows: list[dict[str, object]], root: str) -> str:
    vs = view(rows, root)
    tested = [v for v in vs if v["tier"]]
    md, h = snippets("<slug>")
    el, er = example_badge()
    lines = [START, "",
             "Opt-in only: a project appears here after it accepts, through the "
             f"[Add or update my row]({FORM}) form or a pull request. Generated by `python3 tools/matrix_rows.py "
             "--write` from `matrix/rows/*.json`; CI fails when it is stale. The full searchable table of accepted "
             f"projects is on the [Pages matrix]({PAGES}/matrix/).", "",
             "Two tiers. **External-verified**: the run queue runs the checks that work from outside a project's "
             "stack against its public testnet endpoint, with no spend, on each new release. **Full suite "
             "(self-hosted)**: the project runs the whole suite in its own CI with the Action on each release, and "
             "the queue verifies the signed attestation; it never runs it. Each row shows its tier, checks passed out "
             "of applicable checks, the denominator (exercised / not applicable / needs the self-hosted run, out of "
             f"{len(T.catalogue())} in the catalogue), the suite tag and the date.", "",
             "Listed projects display the badge in their README with the line \"Conformance tested by "
             "Optitransfer/x402-conformance\", both linking to their row. The badge reads \"External-verified \u00b7 "
             "x402-conformance <tag> \u00b7 Optitransfer\" or \"Full suite (self-hosted) \u00b7 x402-conformance <tag> "
             "\u00b7 Optitransfer\", with checks passed out of applicable and the date, and turns grey when the row "
             "is stale or needs a rerun on the current suite. It is not a certification and not an endorsement, and "
             "carries no x402 logo. The weekly check reads each project's public README and flags a row whose README "
             f"no longer links it. The example row's badge reads \"{el}\" | \"{er}\". "
             "Copy-paste README snippet, per row (each row below has its own):", "",
             f"- Markdown: `{md}`", f"- HTML: `{h}`", "",
             "**Coverage of accepted projects**", "",
             "| by | accepted projects |", "|---|---|",
             f"| total | {len(vs)} accepted, {len(tested)} with results |",
             f"| tier | {counts(tested, 'tier_label') if tested else 'none yet'} |",
             f"| type | {counts(vs, 'type')} |", f"| chain | {counts(vs, 'chains')} |",
             f"| language | {counts(vs, 'languages')} |", f"| environment | {counts(vs, 'environment')} |", "",
             "**Accepted projects with evidence**", "",
             f"Release alignment: current (the version tested is the latest release), behind (vX tested, vY latest), "
             f"or stale (no run within {STALE_DAYS} days of the last release check, or behind for {STALE_DAYS} days "
             "or more). tools/matrix_freshness.py checks each project's latest release and default-branch commit "
             "every week.", "",
             "| project | type | tier | environment | version tested | release alignment | passed/applicable | failed "
             "| denominator | suite | last run | badge in README | README snippet | add or update |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
             md_row(EXAMPLE)]
    if not tested:
        lines.append(f"| no accepted project yet | | | | | | | | | | | | | [add your row]({FORM}) |")
    lines += [md_row(v) for v in tested]
    lines += ["", END]
    return "\n".join(lines)


def esc(x: object) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def html_row(v: dict[str, object]) -> str:
    md, h = snippets(str(v["slug"]))
    if v.get("example"):
        name = f'<strong>{EXAMPLE_LABEL}:</strong> {esc(v["project"])}'
        last = f'{esc(v["last_run"])}: <code>{esc(v["evidence"])}</code>'
    else:
        link = v.get("repo") or v.get("site")
        name = f'<a href="{esc(link)}">{esc(v["project"])}</a>' if link else esc(v["project"])
        last = f'<a href="{esc(v["evidence"])}">{esc(v["last_run"])}</a>' if v["evidence"] else "-"
    ran = v["tier"] is not None
    res = (f'{v["checks_passed"]}/{v["checks_applicable"]}</td><td>{v["failed_count"]}</td><td>{esc(denom(v))}'
           if ran else "not run yet</td><td>-</td><td>-")
    na = "; ".join(f"{k}: {r}" for k, r in (v.get("na_reasons") or {}).items())  # type: ignore[union-attr]
    badge = (f'<img src="{PAGES}/badge/{esc(v["slug"])}.svg" alt="{ALT}">'
             f'<br><code>{esc(md)}</code><br><code>{esc(h)}</code>') if ran else "-"
    cls = ' class="example"' if v.get("example") else ""
    return (f'<tr id="{esc(v["slug"])}"{cls}><td>{name}</td><td>{esc(v["type"])}</td><td>{esc(v["tier_label"])}</td>'
            f'<td>{esc(v["environment"])}</td>'
            f'<td>{esc(", ".join(v["languages"]))}</td><td>{esc(", ".join(v["networks"]))}</td>'  # type: ignore[arg-type]
            f'<td>{esc(v["version"])}</td><td>{esc(v["release_alignment"])}</td><td>{res}</td>'
            f'<td title="{esc(na)}">{esc(suite_cell(v)) if ran else "-"}</td><td>{last}</td>'
            f'<td>{badge}</td><td>{esc(v["readme_badge"])}</td><td>{esc(v["contact"])}</td>'
            f'<td><a href="{FORM}">add or update</a></td></tr>')


def page(rows: list[dict[str, object]], root: str) -> tuple[str, str]:
    """docs/site/matrix/index.html (searchable, one anchor per row for its badge) and docs/site/matrix/rows.json."""
    vs = view(rows, root)
    data = json.dumps({"schema": "x402-conformance.matrix-pages/2", "license": "CC BY 4.0",
                       "attribution": f"Optitransfer/x402-conformance, {REPO}", "catalogue": len(T.catalogue()),
                       "example": EXAMPLE, "rows": vs}, indent=1, ensure_ascii=False) + "\n"
    body = [html_row(EXAMPLE)] + [html_row(v) for v in vs]
    if not vs:
        body.append(f'<tr><td colspan="17">No accepted projects yet. <a href="{FORM}">Add your row</a>.</td></tr>')
    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>x402-conformance matrix: accepted projects</title>
<style>body{{font-family:system-ui,sans-serif;margin:2rem;max-width:96rem}}table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ccc;padding:.3rem .5rem;text-align:left;font-size:.85rem;vertical-align:top}}
tr:target{{background:#fff8c4}}tr.example{{font-style:italic;background:#f4f4f4}}code{{font-size:.75rem}}
input{{padding:.4rem;width:20rem;margin:.5rem 0}}</style>
</head>
<body>
<h1>x402-conformance matrix</h1>
<p>Projects that accepted to be listed, opt-in only, in two tiers. <strong>External-verified</strong>: the checks
that run from outside a project's stack against its public testnet endpoint, run by the x402-conformance run queue
on each new release, with no spend. <strong>Full suite (self-hosted)</strong>: the whole suite, run in the project's
own CI with the Action on each release; the queue verifies its signed attestation and never runs it. Each row shows
checks passed out of applicable checks, the denominator (exercised / not applicable / needs the self-hosted run, out
of {len(T.catalogue())}), the suite tag, the date and how the version tested lines up with the project's latest
release. There is no score and no ranking. Listed projects display the badge in their own README with the line
"Conformance tested by Optitransfer/x402-conformance"; both link to their row. The badge shows the tier, the suite
tag, the count and the date, and turns grey when the row is stale. It is not a certification and not an endorsement.
<a href="{FORM}">Add or update your row</a>. Data: <a href="rows.json">rows.json</a>, CC BY 4.0,
"Optitransfer/x402-conformance", <a href="{REPO}">{REPO}</a>.</p>
<label>Search <input id="q" type="search" placeholder="project, type, tier, chain, language"></label>
<table id="rows">
<thead><tr><th>project</th><th>type</th><th>tier</th><th>environment</th><th>languages</th><th>networks</th>
<th>version tested</th><th>release alignment</th><th>passed/applicable</th><th>failed</th><th>denominator</th>
<th>suite</th><th>last run</th><th>badge and README snippet</th><th>badge in README</th><th>contact</th>
<th>add or update</th></tr></thead>
<tbody>
{chr(10).join(body)}
</tbody>
</table>
<script>
document.getElementById("q").addEventListener("input", function (e) {{
  var q = e.target.value.toLowerCase();
  document.querySelectorAll("#rows tbody tr").forEach(function (tr) {{
    tr.hidden = q !== "" && tr.textContent.toLowerCase().indexOf(q) < 0;
  }});
}});
</script>
</body>
</html>
"""
    return doc, data


def badges(rows: list[dict[str, object]], root: str) -> dict[str, str]:
    el, er = example_badge()
    out = {f"{BADGES}/{EXAMPLE['slug']}.svg": badge_svg(str(EXAMPLE["slug"]), el, er, False, True)}
    for v in view(rows, root):
        if v["tier"]:
            rerun = v.get("suite_status") != "current"
            left, right = badge_text(str(v["tier"]), str(v["suite_tag"]), v["checks_passed"], v["checks_applicable"],
                                     v["last_run"], bool(v["stale"]), rerun)
            out[f"{BADGES}/{v['slug']}.svg"] = badge_svg(str(v["slug"]), left, right, bool(v["stale"]) or rerun)
    return out


def with_table(md: str, t: str) -> str:
    i, j = md.find(START), md.find(END)
    if i >= 0 and j > i:
        return md[:i] + t + md[j + len(END):]
    return md.rstrip("\n") + "\n\n## Listed projects\n\n" + t + "\n"


def consistency(rows: list[dict[str, object]], root: str) -> list[str]:
    """Every consented evidence row belongs to an accepted row, and every row's evidence exists."""
    compat = compat_rows(root)
    linked = {str(r.get("evidence") or "").rsplit("/", 1)[-1] for r in rows if r.get("evidence")}
    bad = [f"evidence/impl-matrix/{n} records consent but no matrix/rows/*.json links it"
           for n, c in sorted(compat.items()) if c.get("consent") and n not in linked]
    bad += [f"{ROWS}/{r['slug']}.json: its evidence {r['evidence']} is not in {COMPAT}"
            for r in rows if r.get("evidence") and run_of(r, compat) is None]
    bad += [f"{ROWS}/{r['slug']}.json: the slug 'example' is reserved for the illustrative row"
            for r in rows if r.get("slug") == EXAMPLE["slug"]]
    return bad


def outputs(rows: list[dict[str, object]], root: str) -> dict[str, str]:
    doc, data = page(rows, root)
    return {f"{PAGE_DIR}/index.html": doc, f"{PAGE_DIR}/rows.json": data, **badges(rows, root)}


def write_md(root: str) -> list[str]:
    rows, bad = load_rows(root)
    p = os.path.join(root, MD_OUT)
    md = open(p, encoding="utf-8").read()
    with open(p, "w", encoding="utf-8") as f:
        f.write(with_table(md, table(rows, root)))
    want = outputs(rows, root)
    bdir = os.path.join(root, BADGES)
    os.makedirs(bdir, exist_ok=True)
    os.makedirs(os.path.join(root, PAGE_DIR), exist_ok=True)
    for name in os.listdir(bdir):
        if name.endswith(".svg") and f"{BADGES}/{name}" not in want:
            os.remove(os.path.join(bdir, name))
    for rel, text in want.items():
        with open(os.path.join(root, rel), "w", encoding="utf-8") as f:
            f.write(text)
    return bad + consistency(rows, root)


def main(argv: list[str]) -> int:  # noqa: C901
    opt = {k: argv[argv.index(k) + 1] for k in ("--root", "--from-issue", "--issue-url", "--github-output", "--today")
           if k in argv and argv.index(k) + 1 < len(argv)}
    root = os.path.abspath(opt.get("--root", ROOT))
    if "--from-issue" in opt:
        body = open(opt["--from-issue"], encoding="utf-8").read()
        row, run_link, bad = from_issue(body, opt.get("--issue-url", ""), opt.get("--today", ""))
        bad += problems(row, root)
        if bad:
            print("Your row could not be added yet:\n")
            print("\n".join(f"- {b}" for b in bad))
            print(f"\nEdit the issue to fix it, and the check runs again. Form: {FORM}")
            return 1
        existing = os.path.join(root, ROWS, f"{row['slug']}.json")
        if os.path.isfile(existing):
            prev = json.load(open(existing, encoding="utf-8"))
            if prev.get("source_issue") != row["source_issue"]:
                print(f"Your row could not be added yet:\n\n- {ROWS}/{row['slug']}.json belongs to another issue "
                      f"({prev.get('source_issue')}); update it from that issue, or choose another project name")
                return 1
            # Results, tier and program dates are written by the tools, never by the form: an update keeps them.
            for k in ("release", "evidence", "tier", "attestation", "program_start", "program_end", "program_notice"):
                if prev.get(k) and (k not in ("program_start", "program_end", "program_notice") or row["consent"].get("hook")):  # type: ignore[union-attr]
                    row[k] = prev[k]
        os.makedirs(os.path.join(root, ROWS), exist_ok=True)
        with open(os.path.join(root, ROWS, f"{row['slug']}.json"), "w", encoding="utf-8") as f:
            json.dump(row, f, indent=1, ensure_ascii=False)
            f.write("\n")
        bad = write_md(root)
        m = RUN_URL.match(run_link)
        if opt.get("--github-output"):
            with open(opt["--github-output"], "a", encoding="utf-8") as f:
                f.write(f"slug={row['slug']}\nattest_repo={m.group(1) if m else ''}\nattest_run={m.group(2) if m else ''}\n")
        print(f"Your row is valid: {ROWS}/{row['slug']}.json. A maintainer reviews the pull request before it is listed."
              + (" The attestation of your full-suite run is verified next." if m else ""))
        return 1 if bad else 0
    if "--write" in argv:
        bad = write_md(root)
        for b in bad:
            print(f"matrix-rows: {b}")
        return 1 if bad else 0
    if "--check" in argv:
        rows, bad = load_rows(root)
        md = open(os.path.join(root, MD_OUT), encoding="utf-8").read()
        if START not in md or END not in md:
            bad.append(f"{MD_OUT} has no listed-projects table: run python3 tools/matrix_rows.py --write")
        elif md != with_table(md, table(rows, root)):
            bad.append(f"the listed-projects table in {MD_OUT} is stale or hand-edited: "
                       "run python3 tools/matrix_rows.py --write")
        bad += wording(md)
        bad += consistency(rows, root)
        want = outputs(rows, root)
        for rel, text in sorted(want.items()):
            p = os.path.join(root, rel)
            if not os.path.isfile(p) or open(p, encoding="utf-8").read() != text:
                bad.append(f"{rel} is missing, stale or hand-edited: run python3 tools/matrix_rows.py --write")
        bdir = os.path.join(root, BADGES)
        for name in sorted(os.listdir(bdir)) if os.path.isdir(bdir) else []:
            if name.endswith(".svg") and f"{BADGES}/{name}" not in want:
                bad.append(f"{BADGES}/{name} has no listed row: run python3 tools/matrix_rows.py --write")
        if FORM not in "\n".join(md.splitlines()[:12]):
            bad.append(f"{MD_OUT} must link the 'Add or update your row' form near the top")
        for b in bad:
            print(f"matrix-rows: {b}")
        print(f"matrix rows: {len(rows)} row(s), {len(bad)} problem(s)")
        return 1 if bad else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
