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
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from x402conf.discovery import Validator  # noqa: E402

SCHEMA = "matrix/schema/row.schema.json"
ROWS = "matrix/rows"
MD_OUT = "docs/MATRIX.md"
COMPAT = "docs/compat-matrix.json"
PAGE_DIR = "docs/site/matrix"
BADGES = "docs/site/badge"
STALE_DAYS = 30
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
    "version": "Version or commit", "evidence": "Evidence JSON from your own run (optional)",
    "contact": "Public contact handle", "consent": "Consent",
}
CONSENTS = {"listing": "list this project", "data_license": "CC BY 4.0", "testnet_only": "testnet-only probes"}
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


def from_issue(body: str, issue_url: str) -> tuple[dict[str, object], str, list[str]]:
    """The row, any evidence JSON text, and the problems found reading the form."""
    s = sections(body)
    bad: list[str] = []
    for key, label in LABELS.items():
        if label not in s and key not in ("evidence", "testnet_endpoint", "site"):
            bad.append(f"the form has no '{label}' section")
    ticked = {k: bool(re.search(r"^- \[[xX]\] .*" + re.escape(w), s.get(LABELS["consent"], ""), re.M | re.I))
              for k, w in CONSENTS.items()}
    for k, ok in ticked.items():
        if not ok:
            bad.append(f"consent not given: '{CONSENTS[k]}' must be ticked; nothing is listed without it")
    t = s.get(LABELS["type"], "").strip().lower()
    evidence = s.get(LABELS["evidence"], "").strip()
    evidence = re.sub(r"^```(json)?\s*|\s*```$", "", evidence).strip()
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
        "evidence": None,
    }
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
        if row.get("type") == "facilitator-hosted" and row.get("testnet_endpoint"):
            pass  # listed as offered; a hosted facilitator is probed only with written permission (SECURITY.md)
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


def alignment(version: str, last_run: str | None, release: object) -> tuple[str, bool]:
    """Release alignment, and whether the row is stale. It is computed only from what is committed (the run date and
    the release check tools/matrix_freshness.py records), never from today's date, so the output is reproducible.
    current: the version tested is the latest release. behind (vX tested, vY latest): it is not. stale: no run within
    STALE_DAYS of the last release check, or behind for STALE_DAYS or more."""
    if not last_run:
        return "not run yet", False
    if not isinstance(release, dict) or not release.get("checked_at"):
        return "not checked yet", False
    checked = str(release["checked_at"])
    latest = release.get("latest")
    behind = bool(latest) and norm(latest) != norm(version)
    since = str(release.get("behind_since") or checked)
    if days(last_run, checked) > STALE_DAYS or (behind and days(since, checked) >= STALE_DAYS):
        return (f"stale (v{norm(version)} tested, v{norm(latest)} latest)" if behind else "stale"), True
    if behind:
        return f"behind (v{norm(version)} tested, v{norm(latest)} latest)", False
    return ("current" if latest else "current (no release published; default branch tested)"), False


def badge_svg(slug: str, version: str, stale: bool, example: bool = False) -> str:
    """'Tested with x402-conformance · Optitransfer' and the version tested, grey 'stale' when stale. No script, no
    remote resource, no logo; the link goes to the project's row on the Pages matrix."""
    left = "Tested with x402-conformance \u00b7 Optitransfer"
    right = "stale" if stale else f"v{norm(version)}"[:24]
    lw, rw = 6 * len(left) + 14, 7 * len(right) + 14
    color = "#9e9e9e" if stale else "#2e7d32"
    href = f"{PAGES}/matrix/#{slug}"
    title = f"{left}: {slug}, {right}" + (" (example, not a real result)" if example else "")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{lw + rw}" '
            f'height="20" role="img" aria-label="{html.escape(left)}: {html.escape(right)}">\n'
            f'<title>{html.escape(title)}</title>\n<a xlink:href="{href}" href="{href}">\n'
            f'<rect width="{lw}" height="20" fill="#555"/>\n<rect x="{lw}" width="{rw}" height="20" fill="{color}"/>\n'
            f'<g fill="#fff" font-family="Verdana,DejaVu Sans,sans-serif" font-size="11" text-anchor="middle">\n'
            f'<text x="{lw // 2}" y="14">{html.escape(left)}</text>\n'
            f'<text x="{lw + rw // 2}" y="14">{html.escape(right)}</text>\n</g>\n</a>\n</svg>\n')


def snippets(slug: str) -> tuple[str, str]:
    """Copy-paste badge markdown and HTML for one row."""
    img, row = f"{PAGES}/badge/{slug}.svg", f"{PAGES}/matrix/#{slug}"
    alt = "Tested with x402-conformance \u00b7 Optitransfer"
    return f"[![{alt}]({img})]({row})", f'<a href="{row}"><img src="{img}" alt="{alt}"></a>'


EXAMPLE = {
    "slug": "example", "project": "example-org/example-x402-server", "type": "merchant-paid-api",
    "repo": None, "site": None, "languages": ["TypeScript"], "chains": ["EVM", "SVM"],
    "networks": ["eip155:84532", "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"], "environment": "testnet",
    "version": "1.4.0", "contact": "@example-org", "checks_run": 48, "checks_passed": 42, "failed_count": 6,
    "last_run": "2026-10-20", "release_alignment": "behind (v1.4.0 tested, v1.5.0 latest)", "stale": False,
    "evidence": "evidence/impl-matrix/<slug>/run.json", "example": True,
}
EXAMPLE_LABEL = "Example (illustrative, not a real result)"


def view(rows: list[dict[str, object]], root: str) -> list[dict[str, object]]:
    """What is published for each accepted row: its public fields and the counts from its committed evidence."""
    compat = compat_rows(root)
    out = []
    for r in rows:
        run = run_of(r, compat)
        last = str(run.get("run_at") or "")[:10] if run else None
        align, stale = alignment(str(r["version"]), last or None, r.get("release"))
        out.append({
            "slug": r["slug"], "project": r["project"], "type": r["type"], "repo": r.get("repo"), "site": r.get("site"),
            "languages": r.get("languages") or [], "chains": r.get("chains") or [], "networks": r.get("networks") or [],
            "environment": environment(r, run), "version": r["version"], "contact": r["contact"],
            "checks_run": run["checks_run"] if run else None, "checks_passed": run["checks_passed"] if run else None,
            "failed_count": run["failed_count"] if run else None, "last_run": last,
            "release_alignment": align, "stale": stale,
            "evidence": f"{REPO}/blob/main/{run['run']}" if run else None,
            "badge": f"{PAGES}/badge/{r['slug']}.svg" if run else None,
            "source_issue": r["source_issue"],
        })
    return out


def counts(vs: list[dict[str, object]], key: str) -> str:
    c: dict[str, int] = {}
    for v in vs:
        vals = v[key] if isinstance(v[key], list) else [v[key]]
        for x in vals or ["none"]:
            c[str(x)] = c.get(str(x), 0) + 1
    return ", ".join(f"{k} {n}" for k, n in sorted(c.items())) or "none yet"


def md_row(v: dict[str, object]) -> str:
    md, _ = snippets(str(v["slug"]))
    if v.get("example"):
        name, last = f"**{EXAMPLE_LABEL}:** {v['project']}", f"{v['last_run']}: `{v['evidence']}`"
    else:
        link = v.get("repo") or v.get("site")
        name = f"[{v['project']}]({link})" if link else str(v["project"])
        last = f"[{v['last_run']}]({v['evidence']})"
    return (f"| <a id=\"project-{v['slug']}\"></a>{name} | {v['type']} | {v['environment']} | {v['version']} | "
            f"{v['release_alignment']} | {v['checks_passed']}/{v['checks_run']} | {v['failed_count']} | {last} | "
            f"`{md}` | [add or update]({FORM}) |")


def table(rows: list[dict[str, object]], root: str) -> str:
    vs = view(rows, root)
    tested = [v for v in vs if v["checks_run"] is not None]
    md, h = snippets("<slug>")
    lines = [START, "",
             "Opt-in only: a project appears here after it accepts, through the "
             f"[Add or update my row]({FORM}) form or a pull request. Generated by `python3 tools/matrix_rows.py "
             "--write` from `matrix/rows/*.json`; CI fails when it is stale. The full searchable table of accepted "
             f"projects is on the [Pages matrix]({PAGES}/matrix/).", "",
             "Listed projects add the badge to their own README. It reads \"Tested with x402-conformance \u00b7 "
             "Optitransfer\" and the version tested, links to the project's row, and turns grey with \"stale\" when "
             "the row is stale. It is not a certification and not an endorsement, and carries no x402 logo. "
             "Copy-paste, per row (each row below has its own):", "",
             f"- Markdown: `{md}`", f"- HTML: `{h}`", "",
             "**Coverage of accepted projects**", "",
             "| by | accepted projects |", "|---|---|",
             f"| total | {len(vs)} accepted, {len(tested)} with committed evidence |",
             f"| type | {counts(vs, 'type')} |", f"| chain | {counts(vs, 'chains')} |",
             f"| language | {counts(vs, 'languages')} |", f"| environment | {counts(vs, 'environment')} |", "",
             "**Accepted projects with evidence**", "",
             f"Release alignment: current (the version tested is the latest release), behind (vX tested, vY latest), "
             f"or stale (no run within {STALE_DAYS} days of the last release check, or behind for {STALE_DAYS} days "
             "or more). tools/matrix_freshness.py checks each project's latest release and default-branch commit "
             "every week.", "",
             "| project | type | environment | version tested | release alignment | passed/run | failed | last run "
             "| badge markdown | add or update |",
             "|---|---|---|---|---|---|---|---|---|---|",
             md_row(EXAMPLE)]
    if not tested:
        lines.append(f"| no accepted project yet | | | | | | | | | [add your row]({FORM}) |")
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
    res = (f'{v["checks_passed"]}/{v["checks_run"]}</td><td>{v["failed_count"]}' if v["checks_run"] is not None
           else "not run yet</td><td>-")
    badge = (f'<img src="{PAGES}/badge/{esc(v["slug"])}.svg" alt="Tested with x402-conformance \u00b7 Optitransfer">'
             f'<br><code>{esc(md)}</code><br><code>{esc(h)}</code>') if v["checks_run"] is not None else "-"
    cls = ' class="example"' if v.get("example") else ""
    return (f'<tr id="{esc(v["slug"])}"{cls}><td>{name}</td><td>{esc(v["type"])}</td><td>{esc(v["environment"])}</td>'
            f'<td>{esc(", ".join(v["languages"]))}</td><td>{esc(", ".join(v["networks"]))}</td>'  # type: ignore[arg-type]
            f'<td>{esc(v["version"])}</td><td>{esc(v["release_alignment"])}</td><td>{res}</td><td>{last}</td>'
            f'<td>{badge}</td><td>{esc(v["contact"])}</td><td><a href="{FORM}">add or update</a></td></tr>')


def page(rows: list[dict[str, object]], root: str) -> tuple[str, str]:
    """docs/site/matrix/index.html (searchable, one anchor per row for its badge) and docs/site/matrix/rows.json."""
    vs = view(rows, root)
    data = json.dumps({"schema": "x402-conformance.matrix-pages/1", "license": "CC BY 4.0",
                       "attribution": f"x402-conformance by Optitransfer, {REPO}", "example": EXAMPLE, "rows": vs},
                      indent=1, ensure_ascii=False) + "\n"
    body = [html_row(EXAMPLE)] + [html_row(v) for v in vs]
    if not vs:
        body.append(f'<tr><td colspan="13">No accepted projects yet. <a href="{FORM}">Add your row</a>.</td></tr>')
    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>x402-conformance matrix: accepted projects</title>
<style>body{{font-family:system-ui,sans-serif;margin:2rem;max-width:90rem}}table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ccc;padding:.3rem .5rem;text-align:left;font-size:.85rem;vertical-align:top}}
tr:target{{background:#fff8c4}}tr.example{{font-style:italic;background:#f4f4f4}}code{{font-size:.75rem}}
input{{padding:.4rem;width:20rem;margin:.5rem 0}}</style>
</head>
<body>
<h1>x402-conformance matrix</h1>
<p>Projects that accepted to be listed, opt-in only. Each row shows checks passed out of checks run and a failed count
from its committed evidence, and how the version tested lines up with the project's latest release. There is no score
and no ranking. Listed projects add the badge, "Tested with x402-conformance &middot; Optitransfer", to their own
README; it links to their row, shows the version tested and turns grey when the row is stale. It is not a
certification and not an endorsement. <a href="{FORM}">Add or update your row</a>. Data:
<a href="rows.json">rows.json</a>, CC BY 4.0, "x402-conformance by Optitransfer", <a href="{REPO}">{REPO}</a>.</p>
<label>Search <input id="q" type="search" placeholder="project, type, chain, language"></label>
<table id="rows">
<thead><tr><th>project</th><th>type</th><th>environment</th><th>languages</th><th>networks</th><th>version tested</th>
<th>release alignment</th><th>passed/run</th><th>failed</th><th>last run</th><th>badge</th><th>contact</th>
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
    out = {f"{BADGES}/{EXAMPLE['slug']}.svg": badge_svg(str(EXAMPLE["slug"]), str(EXAMPLE["version"]), False, True)}
    for v in view(rows, root):
        if v["checks_run"] is not None:
            out[f"{BADGES}/{v['slug']}.svg"] = badge_svg(str(v["slug"]), str(v["version"]), bool(v["stale"]))
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
    opt = {k: argv[argv.index(k) + 1] for k in ("--root", "--from-issue", "--issue-url", "--github-output")
           if k in argv and argv.index(k) + 1 < len(argv)}
    root = os.path.abspath(opt.get("--root", ROOT))
    if "--from-issue" in opt:
        body = open(opt["--from-issue"], encoding="utf-8").read()
        row, evidence, bad = from_issue(body, opt.get("--issue-url", ""))
        bad += problems(row, root)
        bundle = None
        if evidence and not bad:
            bundle = tempfile.mkdtemp()
            try:
                json.loads(evidence)
            except ValueError:
                bad.append("the evidence is not JSON: paste the run.json your run wrote, or leave it empty")
            else:
                with open(os.path.join(bundle, "run.json"), "w", encoding="utf-8") as f:
                    f.write(evidence + "\n")
                with open(os.path.join(bundle, "README.md"), "w", encoding="utf-8") as f:
                    f.write(f"# {row['slug']}\n\nSubmitted by the project with its own run, for review: "
                            f"{row['source_issue']}\n")
        if bad:
            print("Your row could not be added yet:\n")
            print("\n".join(f"- {b}" for b in bad))
            print(f"\nEdit the issue to fix it, and the check runs again. Form: {FORM}")
            return 1
        existing = os.path.join(root, ROWS, f"{row['slug']}.json")
        if os.path.isfile(existing):
            prev = json.load(open(existing, encoding="utf-8"))
            if prev.get("source_issue") == row["source_issue"]:
                row["release"] = prev.get("release")
                if not bundle:
                    row["evidence"] = prev.get("evidence")
            if prev.get("source_issue") != row["source_issue"]:
                print(f"Your row could not be added yet:\n\n- {ROWS}/{row['slug']}.json belongs to another issue "
                      f"({prev.get('source_issue')}); update it from that issue, or choose another project name")
                shutil.rmtree(bundle, True) if bundle else None
                return 1
        elif bundle and os.path.exists(os.path.join(root, "evidence", "impl-matrix", str(row["slug"]))):
            print(f"Your row could not be added yet:\n\n- evidence/impl-matrix/{row['slug']} already exists for another row; "
                  "choose another project name")
            shutil.rmtree(bundle, True)
            return 1
        if bundle:
            rc = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "row_from_evidence.py"), bundle,
                                 "--row", str(row["slug"]), "--consent", str(row["source_issue"]), "--root", root,
                                 "--update"], capture_output=True, text=True)
            shutil.rmtree(bundle, True)
            if rc.returncode:
                print("Your evidence could not be added:\n")
                print(rc.stdout.strip())
                return 1
            row["evidence"] = f"evidence/impl-matrix/{row['slug']}"
        os.makedirs(os.path.join(root, ROWS), exist_ok=True)
        with open(os.path.join(root, ROWS, f"{row['slug']}.json"), "w", encoding="utf-8") as f:
            json.dump(row, f, indent=1, ensure_ascii=False)
            f.write("\n")
        bad = write_md(root)
        if opt.get("--github-output"):
            with open(opt["--github-output"], "a", encoding="utf-8") as f:
                f.write(f"slug={row['slug']}\nevidence={'yes' if row['evidence'] else 'no'}\n")
        print(f"Your row is valid: {ROWS}/{row['slug']}.json. A maintainer reviews the pull request before it is listed.")
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
