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


def table(rows: list[dict[str, object]], root: str) -> str:
    compat_path = os.path.join(root, COMPAT)
    compat = {r["row"]: r for r in json.load(open(compat_path))["rows"]} if os.path.isfile(compat_path) else {}
    lines = [START, "",
             "Projects that asked to be listed, from `matrix/rows/*.json`. Generated by `python3 tools/matrix_rows.py "
             "--write`; CI fails when it is stale. A row is added only with the project's consent, and its results come "
             f"only from committed evidence. [Add or update your row]({FORM}).", "",
             "| project | type | environment | languages | networks | version tested | passed/run | failed | last run "
             "| contact | add or update |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    if not rows:
        lines.append(f"| none yet | | | | | | | | | | [add your row]({FORM}) |")
    for r in rows:
        ev = str(r.get("evidence") or "")
        run = compat.get(ev.rsplit("/", 1)[-1]) if ev else None
        name = str(r["project"])
        link = r.get("repo") or r.get("site")
        cell = f"[{name}]({link})" if link else name
        res = (f"{run['checks_passed']}/{run['checks_run']} | {run['failed_count']} | "
               f"[{str(run.get('run_at') or '')[:10]}](../{run['run']})") if run else "not run yet | - | -"
        nets = ", ".join(f"`{n}`" for n in r.get("networks") or []) or "-"  # type: ignore[union-attr]
        lines.append(f"| <a id=\"project-{r['slug']}\"></a>{cell} | {r['type']} | {environment(r, run)} | "
                     f"{', '.join(r.get('languages') or []) or '-'} | {nets} | {r['version']} | {res} | "  # type: ignore[arg-type]
                     f"{r['contact']} | [add or update]({FORM}) |")
    lines += ["", END]
    return "\n".join(lines)


def with_table(md: str, t: str) -> str:
    i, j = md.find(START), md.find(END)
    if i >= 0 and j > i:
        return md[:i] + t + md[j + len(END):]
    return md.rstrip("\n") + "\n\n## Listed projects\n\n" + t + "\n"


def write_md(root: str) -> list[str]:
    rows, bad = load_rows(root)
    p = os.path.join(root, MD_OUT)
    md = open(p, encoding="utf-8").read()
    with open(p, "w", encoding="utf-8") as f:
        f.write(with_table(md, table(rows, root)))
    return bad


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
