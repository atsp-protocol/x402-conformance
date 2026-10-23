#!/usr/bin/env python3
"""The interdependency map and the docs drift check.

    python3 tools/interdeps.py              write docs/INTERDEPENDENCY.md from the contract, the addenda and the tree
    python3 tools/interdeps.py --check      exit 1 if the committed docs/INTERDEPENDENCY.md is stale
    python3 tools/interdeps.py --drift      exit 1 on drift between the docs and the code (below)
    python3 tools/interdeps.py --versions X.Y.Z   exit 1 unless every package version is X.Y.Z

The map lists every contract task (signed in proofline.json, or proposed in an unmerged addendum under
docs/proposals/) with its dependencies, requirements, scope and status, and every check id with its profile, spec
basis, upstream references, tasks, and the code, tests and docs that name it, with a mermaid graph of the tasks.
The output depends only on the tree: no timestamps, everything sorted.

Drift is any of:
  a doc names a check id that is neither built (src/x402conf/spec.py CATALOG) nor planned (named by a task)
  a built check id that no doc names
  a doc names a flag of x402conf, x402conf-svm or the pytest plugin that the code doesn't have
  a flag in the code that no doc names
  a doc's `with:` block for this Action names an input action.yml doesn't have
  an action.yml input that no doc names
  the package versions disagree

--root DIR runs against another tree (the tests use it on a copy)."""

from __future__ import annotations

import ast
import fnmatch
import glob
import json
import os
import re
import subprocess
import sys
from typing import Any

MAP = "docs/INTERDEPENDENCY.md"
PREFIXES = "SPFRBDGUWXC"  # the letters check ids start with
ID = re.compile(rf"(?<![A-Za-z0-9_/.-])([{PREFIXES}]\d{{1,2}}[a-z]?)(?![A-Za-z0-9_])")
RANGE = re.compile(rf"\b([{PREFIXES}])(\d{{1,2}})(?:-|\s+to\s+)\1?(\d{{1,2}})\b")
FLAG = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]*)")
TOOLS = ("x402conf-svm", "x402-conformance-svm", "x402conf", "pytest")


def read(root: str, path: str) -> str:
    try:
        with open(os.path.join(root, path), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def tracked(root: str) -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True).stdout
    files = [f for f in out.splitlines() if f]
    return sorted(files) if files else sorted(
        os.path.relpath(p, root) for p in glob.glob(os.path.join(root, "**", "*"), recursive=True)
        if os.path.isfile(p) and "/.git/" not in p and "/node_modules/" not in p)


def glob_match(path: str, pat: str) -> bool:
    if pat.endswith("/**"):
        return path.startswith(pat[:-3] + "/")
    return fnmatch.fnmatchcase(path, pat)


# ---------------- inputs ----------------
def tasks(root: str) -> list[dict[str, Any]]:
    """Signed tasks from proofline.json, then proposed ones from addenda that aren't merged yet."""
    signed = json.loads(read(root, "proofline.json") or "{}").get("tasks", [])
    out = [dict(t, _status="signed") for t in signed]
    have = {t["id"] for t in out}
    for f in sorted(glob.glob(os.path.join(root, "docs", "proposals", "*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        if "merged" in str(d.get("status", "")):
            continue
        for t in d.get("tasks", []):
            if t["id"] not in have:
                out.append(dict(t, _status="proposed", _file=os.path.relpath(f, root)))
                have.add(t["id"])
    claims = set(json.loads(read(root, "vv/claims.json") or "{}").get("done", []))
    for t in out:
        if t["_status"] == "signed" and t["id"] in claims:
            t["_status"] = "done"
    return sorted(out, key=lambda t: task_key(t["id"]))


def task_key(tid: str) -> tuple[int, int, str]:
    m = re.match(r"XC-(M?)(\d+)", tid)
    return (1 if m and m.group(1) else 0, int(m.group(2)) if m else 0, tid)


def catalog(root: str) -> dict[str, dict[str, Any]]:
    """The CATALOG literal in src/x402conf/spec.py, read without importing it."""
    src = read(root, "src/x402conf/spec.py")
    tree = ast.parse(src)
    consts: dict[str, Any] = {}
    for node in tree.body:
        target = node.targets[0] if isinstance(node, ast.Assign) else node.target if isinstance(node, ast.AnnAssign) else None
        if not isinstance(target, ast.Name) or node.value is None:
            continue
        if target.id == "CATALOG":
            # the constants go in as globals: before Python 3.12 a comprehension can't see the caller's locals
            env: dict[str, Any] = {"__builtins__": {"range": range}, **consts}
            return dict(eval(compile(ast.Expression(node.value), "spec.py", "eval"), env))  # noqa: S307
        try:
            consts[target.id] = ast.literal_eval(node.value)
        except ValueError:
            pass
    return {}


def check_ids_in(text: str) -> set[str]:
    text = re.sub(r"(?m)^(#+\s+)P\d\.", r"\1", text)  # a priority heading ("### P0. ...") is not a check id
    ids = set(ID.findall(text))
    for p, a, b in RANGE.findall(text):
        if int(a) < int(b) <= int(a) + 20:
            ids.update(f"{p}{i}" for i in range(int(a), int(b) + 1))
    return ids


def planned(ts: list[dict[str, Any]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for t in ts:
        for c in check_ids_in(t.get("title", "")):
            out.setdefault(c, []).append(t["id"])
    return out


def doc_files(root: str) -> list[str]:
    docs = ["README.md", "CONTRIBUTING.md", "ts/README.md", "ts/mcp/README.md"]
    docs += [os.path.relpath(p, root) for p in glob.glob(os.path.join(root, "docs", "**", "*.md"), recursive=True)]
    return sorted(d for d in set(docs) if d != MAP and os.path.isfile(os.path.join(root, d)))


def code_flags(root: str) -> dict[str, set[str]]:
    py: set[str] = set()
    for f in ("src/x402conf/cli.py", "src/x402conf/devnet/runner.py"):  # x402conf devnet hands its flags to the runner
        py.update(re.findall(r"add_argument\(\s*\"(--[a-z][a-z0-9-]*)\"", read(root, f)))
    ts_src = read(root, "ts/src/cli.ts")
    ts: set[str] = set()
    for m in re.finditer(r"new Set\(\[(.*?)\]\)", ts_src, re.S):
        ts.update(re.findall(r"\"(--[a-z][a-z0-9-]*)\"", m.group(1)))
    b = re.search(r"const BINDING = \[(.*?)\]", ts_src, re.S)
    if b:
        ts.update(f"--{x}" for x in re.findall(r"\"([a-z][a-z0-9-]*)\"", b.group(1)))
    ts.update(re.findall(r"argv\.includes\(\"(--[a-z][a-z0-9-]*)\"\)", ts_src))
    ts.update(re.findall(r"\"(--[a-z][a-z0-9-]*)\"(?=[^\n]*\]\.includes\(argv)", ts_src))
    plugin = set(re.findall(r"addoption\(\s*\"(--[a-z][a-z0-9-]*)\"", read(root, "src/x402conf/pytest_plugin.py")))
    return {"x402conf": py | {"--help"}, "x402conf-svm": ts | {"--help"}, "pytest": plugin}


def doc_flags(root: str) -> dict[str, dict[str, set[str]]]:
    """Flags the docs give on a command line of one of our CLIs: {tool: {flag: {doc, ...}}}."""
    out: dict[str, dict[str, set[str]]] = {"x402conf": {}, "x402conf-svm": {}, "pytest": {}}
    for d in doc_files(root):
        for line in read(root, d).splitlines():
            for seg in re.split(r"`|&&|\|\||;|\|", line):
                words = seg.split()
                tool = next((w for w in words if w in TOOLS), None)
                if not tool:
                    continue
                key = "x402conf-svm" if tool in ("x402conf-svm", "x402-conformance-svm") else tool
                for f in FLAG.findall(seg[seg.index(tool):]):
                    if key == "pytest" and not f.startswith("--x402"):
                        continue
                    out[key].setdefault(f, set()).add(d)
    return out


def action_inputs(root: str) -> list[str]:
    src = read(root, "action.yml")
    m = re.search(r"^inputs:\n(.*?)^\S", src, re.S | re.M)
    return sorted(re.findall(r"^  ([a-z][a-z0-9-]*):\s*$", m.group(1), re.M)) if m else []


def doc_action_inputs(root: str) -> dict[str, set[str]]:
    """Keys under `with:` in a step that uses this Action, in the docs' yaml."""
    out: dict[str, set[str]] = {}
    for d in doc_files(root):
        lines = read(root, d).splitlines()
        for i, line in enumerate(lines):
            if not re.search(r"uses:\s*atsp-protocol/x402-conformance@", line):
                continue
            ind = len(line) - len(line.lstrip(" -"))
            j = i + 1
            while j < len(lines) and lines[j].strip() and (len(lines[j]) - len(lines[j].lstrip(" "))) >= ind \
                    and not lines[j].lstrip().startswith("- "):
                if lines[j].strip() == "with:":
                    w = len(lines[j]) - len(lines[j].lstrip(" "))
                    k = j + 1
                    while k < len(lines) and (len(lines[k]) - len(lines[k].lstrip(" "))) > w and lines[k].strip():
                        m = re.match(r"\s*([a-z][a-z0-9-]*):", lines[k])
                        if m and len(lines[k]) - len(lines[k].lstrip(" ")) == w + 2:
                            out.setdefault(m.group(1), set()).add(d)
                        k += 1
                j += 1
    return out


def versions(root: str) -> dict[str, str]:
    v: dict[str, str] = {}
    m = re.search(r"^version\s*=\s*\"([^\"]+)\"", read(root, "pyproject.toml"), re.M)
    if m:
        v["pyproject.toml"] = m.group(1)
    m = re.search(r"__version__\s*=\s*\"([^\"]+)\"", read(root, "src/x402conf/__init__.py"))
    if m:
        v["src/x402conf/__init__.py"] = m.group(1)
    for f in ("ts/package.json", "ts/mcp/package.json"):
        if read(root, f):
            v[f] = json.loads(read(root, f)).get("version", "")
    for f in ("ts/package-lock.json", "ts/mcp/package-lock.json"):
        if read(root, f):
            lock = json.loads(read(root, f))
            v[f] = lock.get("version", "")
            v[f + " packages[\"\"]"] = lock.get("packages", {}).get("", {}).get("version", "")
    if read(root, "ts/mcp/server.json"):
        s = json.loads(read(root, "ts/mcp/server.json"))
        v["ts/mcp/server.json"] = s.get("version", "")
        for i, p in enumerate(s.get("packages", [])):
            tag = p.get("identifier", "").rsplit(":", 1)[-1] if p.get("registryType") == "oci" else ""
            v[f"ts/mcp/server.json packages[{i}]"] = p.get("version") or tag
    return v


# ---------------- the map ----------------
def short(s: str, n: int = 48) -> str:
    s = s.replace('"', "'")
    return s if len(s) <= n else s[:n].rstrip() + "..."


def cell(xs: Any) -> str:
    xs = list(xs)
    return ", ".join(xs) if xs else "-"


def build(root: str) -> str:
    ts = tasks(root)
    ids = {t["id"] for t in ts}
    needed: dict[str, list[str]] = {}
    for t in ts:
        for d in t.get("depends_on", []):
            needed.setdefault(d, []).append(t["id"])
    cat = catalog(root)
    plan = planned(ts)
    files = tracked(root)
    code = [f for f in files if (f.startswith(("src/", "ts/src/", "ts/mcp/src/", "ts/example/")) or f == "action.yml")
            and f.endswith((".py", ".ts", ".yml"))]
    tests = [f for f in files if f.startswith(("tests/", "ts/test/", "ts/mcp/test/")) and f.endswith((".py", ".ts"))
             and f != "tests/test_interdeps.py"]  # its fixtures name made-up and planned ids
    docs = doc_files(root)
    named: dict[str, dict[str, list[str]]] = {}
    for kind, group in (("code", code), ("tests", tests), ("docs", docs)):
        for f in group:
            for c in check_ids_in(read(root, f)):
                named.setdefault(c, {}).setdefault(kind, []).append(f)

    o = ["# Interdependency map", "",
         "Generated by `python3 tools/interdeps.py` from `proofline.json`, the unmerged addenda in `docs/proposals/`, "
         "`vv/claims.json`, `src/x402conf/spec.py` and the tracked tree. Don't edit it by hand: "
         "`python3 tools/interdeps.py --check` fails in CI when it is stale, and `--drift` fails when the docs and the "
         "code disagree on check ids, CLI flags, Action inputs or versions.", "",
         "Status: done means the task is claimed in `vv/claims.json` and `tools/vv.py` holds it to every mandatory "
         "criterion; signed means it is in the owner-signed contract and still open; proposed means it sits in an "
         "unmerged addendum and binds nothing yet.", "", "## Task graph", "", "```mermaid", "graph LR"]
    node = {"done": ("[", "]"), "signed": ("[", "]"), "proposed": ("(", ")")}
    for t in ts:
        a, b = node[t["_status"]]
        o.append(f'  {t["id"].replace("-", "_")}{a}"{t["id"]}<br/>{short(t["title"])}"{b}')
    for t in ts:
        for d in t.get("depends_on", []):
            o.append(f'  {d.replace("-", "_")} --> {t["id"].replace("-", "_")}')
    o.append("  classDef done fill:#e6f4ea,stroke:#2e7d32")
    o.append("  classDef proposed stroke-dasharray: 4 3")
    for st in ("done", "proposed"):
        group = [t["id"].replace("-", "_") for t in ts if t["_status"] == st]
        if group:
            o.append(f"  class {','.join(group)} {st}")
    o += ["```", "", "Green boxes are done, plain boxes signed and open, round dashed boxes proposed.", ""]
    missing = sorted({d for t in ts for d in t.get("depends_on", []) if d not in ids})
    if missing:
        o += [f"Dependencies on tasks that are in no contract or addendum here: {', '.join(missing)}.", ""]

    o += ["## Tasks", "",
          "| task | phase | status | depends on | needed by | requirements | criteria | scope |",
          "|---|---|---|---|---|---|---|---|"]
    for t in ts:
        crit = t.get("criteria", [])
        kinds: dict[str, int] = {}
        for c in crit:
            k = c.get("verifier", {}).get("type", "?")
            kinds[k] = kinds.get(k, 0) + 1
        scope = "; ".join(f"`{p}`" for p in t.get("scope", {}).get("allow", [])) or "-"
        o.append(f"| {t['id']} {t['title']} | {t.get('phase', '-')} | {t['_status']} | {cell(t.get('depends_on', []))} | "
                 f"{cell(sorted(needed.get(t['id'], []), key=task_key))} | {cell(t.get('requirements', []))} | "
                 f"{len(crit)} ({', '.join(f'{k} {n}' for k, n in sorted(kinds.items()))}) | {scope} |")

    o += ["", "## Checks", "",
          "Built checks are the entries in `src/x402conf/spec.py` CATALOG (and `ts/src/catalog.ts`, which a test "
          "keeps identical). Planned checks are named in a task title and not built yet. The code, tests and docs "
          "columns list the tracked files that name the check id.", "",
          "| check | status | profile | spec basis | upstream | tasks | code | tests | docs |",
          "|---|---|---|---|---|---|---|---|---|"]
    every = sorted(set(cat) | set(plan), key=lambda c: (PREFIXES.index(c[0]), int(re.sub(r"\D", "", c)), c))
    for c in every:
        e = cat.get(c, {})
        n = named.get(c, {})
        up = str(e.get("upstream", "")).replace("x402-foundation/x402", "")
        o.append(f"| {c} | {'built' if e else 'planned'} | {e.get('profile', '-')} | "
                 f"{str(e.get('basis', '-')).replace('|', '/')} | {up or '-'} | "
                 f"{cell(sorted(set(plan.get(c, [])), key=task_key))} | {cell(n.get('code', []))} | "
                 f"{cell(n.get('tests', []))} | {cell(n.get('docs', []))} |")
    o += ["", "Upstream references are issue and PR numbers in x402-foundation/x402.", ""]

    o += ["## Entry points", "", "Every entry point is a thin wrapper over the same suite and corpus.", "",
          "| entry point | code | in this tree | how users reach it |", "|---|---|---|---|"]
    for name, path, how in ENTRY_POINTS:
        o.append(f"| {name} | `{path}` | {'yes' if path in files else 'not yet'} | `{how}` |")
    o += ["", "## CLI flags and Action inputs", "", "| surface | names |", "|---|---|"]
    for tool, fl in sorted(code_flags(root).items()):
        o.append(f"| {tool} | {', '.join(f'`{f}`' for f in sorted(fl))} |")
    o.append(f"| action.yml inputs | {', '.join(f'`{i}`' for i in action_inputs(root))} |")
    o += ["", "## Versions", "", "| file | version |", "|---|---|"]
    for f, v in sorted(versions(root).items()):
        o.append(f"| `{f}` | {v} |")
    return "\n".join(o) + "\n"


ENTRY_POINTS = [
    ("CLI x402conf (PyPI)", "src/x402conf/cli.py", "pip install x402-conformance"),
    ("CLI x402-conformance-svm (npm)", "ts/src/cli.ts", "npx x402-conformance-svm"),
    ("GitHub Action", "action.yml", "uses: atsp-protocol/x402-conformance@v1"),
    ("TypeScript library and matchers", "ts/src/testing.ts", "import from x402-conformance-svm"),
    ("MCP server", "ts/mcp/src/server.ts", "npx x402-conformance-mcp"),
    ("Vercel AI SDK tools", "ts/mcp/src/ai-sdk.ts", "x402-conformance-mcp/ai-sdk"),
    ("LangChain.js tools", "ts/mcp/src/langchain.ts", "x402-conformance-mcp/langchain"),
    ("pytest plugin", "src/x402conf/pytest_plugin.py", "pytest -p x402conf"),
    ("Docker image", "ts/docker/Dockerfile", "docker run ghcr.io/atsp-protocol/x402-conformance"),
    ("GitLab CI component", "ts/ci/gitlab/x402-conformance.yml", "include: component"),
]


# ---------------- drift ----------------
def drift(root: str) -> list[str]:
    problems: list[str] = []
    ts = tasks(root)
    cat = catalog(root)
    known = set(cat) | set(planned(ts))
    for t in ts:
        known |= check_ids_in(t.get("title", "") + " " + t.get("description", ""))
    docs = doc_files(root)
    in_docs: dict[str, set[str]] = {}
    for d in docs:
        for c in check_ids_in(read(root, d)):
            in_docs.setdefault(c, set()).add(d)
    for c in sorted(set(in_docs) - known):
        problems.append(f"check id {c} is named in {', '.join(sorted(in_docs[c]))} but is neither built nor planned")
    for c in sorted(set(cat) - set(in_docs)):
        problems.append(f"check id {c} is built but no doc names it")
    text = "\n".join(read(root, d) for d in docs)
    have = code_flags(root)
    named = doc_flags(root)
    for tool in sorted(have):
        for f in sorted(set(named[tool]) - have[tool]):
            problems.append(f"{tool} flag {f} is in {', '.join(sorted(named[tool][f]))} but not in the code")
        for f in sorted(have[tool] - {"--help"}):
            if not re.search(rf"(?<![\w-]){re.escape(f)}(?![\w-])", text):
                problems.append(f"{tool} flag {f} is in the code but no doc names it")
    inputs = set(action_inputs(root))
    used = doc_action_inputs(root)
    for i in sorted(set(used) - inputs):
        problems.append(f"Action input {i} is in {', '.join(sorted(used[i]))} but not in action.yml")
    for i in sorted(inputs):
        if not re.search(rf"(?<![\w-]){re.escape(i)}(?![\w-])", text):
            problems.append(f"Action input {i} is in action.yml but no doc names it")
    v = versions(root)
    if len(set(v.values())) > 1:
        problems.append("package versions disagree: " + ", ".join(f"{f}={x}" for f, x in sorted(v.items())))
    return problems


def main(argv: list[str]) -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if "--root" in argv:
        root = os.path.abspath(argv[argv.index("--root") + 1])
    if "--check" in argv:
        want = build(root)
        if read(root, MAP) != want:
            print(f"{MAP} is stale: run python3 tools/interdeps.py and commit it", file=sys.stderr)
            return 1
        print(f"{MAP} is up to date")
        return 0
    if "--drift" in argv:
        p = drift(root)
        for x in p:
            print("drift:", x, file=sys.stderr)
        print(f"{len(p)} drift problem(s)")
        return 1 if p else 0
    if "--versions" in argv:
        want_v = argv[argv.index("--versions") + 1] if argv.index("--versions") + 1 < len(argv) else ""
        v = versions(root)
        bad = {f: x for f, x in v.items() if x != want_v}
        for f, x in sorted(bad.items()):
            print(f"version: {f} is {x}, not {want_v}", file=sys.stderr)
        print(f"{len(v) - len(bad)}/{len(v)} version(s) are {want_v}")
        return 1 if bad or not v or not want_v else 0
    with open(os.path.join(root, MAP), "w", encoding="utf-8") as f:
        f.write(build(root))
    print(f"wrote {MAP}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
