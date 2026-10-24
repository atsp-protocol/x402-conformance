#!/usr/bin/env python3
"""The interdependency map and the docs drift check.

    python3 tools/interdeps.py              write docs/INTERDEPENDENCY.md from the contract, the addenda and the tree
    python3 tools/interdeps.py --check      exit 1 if the committed docs/INTERDEPENDENCY.md is stale
    python3 tools/interdeps.py --drift      exit 1 on drift between the docs and the code (below)
    python3 tools/interdeps.py --versions X.Y.Z   exit 1 unless every package version is X.Y.Z
    python3 tools/interdeps.py --versions X.Y.Z --at REF   the same, read from the tree of git ref REF (a release tag)

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

Files: every tracked file belongs to one component (COMPONENTS, first match wins) and the components are joined by
EDGES (a -> b: when a changes, b is updated with it or reviewed). --check also fails on a tracked file no component
covers and on a component that covers nothing.

    python3 tools/interdeps.py --gate --base REF [--head REF]
        the PR gate: for each component the diff touches, its direct downstream components of kind doc, contract or
        test must be touched too, or acknowledged in a commit message or the PR body (env PR_BODY) with a line
            Interdeps-Ack: <component>[, <component> ...] - <reason>
        upstream components, other downstream kinds and components two steps out are printed for review only

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
    if files:
        return sorted(set(files))  # a file mid-merge is listed once per stage
    out = []  # not a git tree (the tests' copies): every file, dotfiles included, outside .git and node_modules
    for d, dirs, names in os.walk(root):
        dirs[:] = [x for x in dirs if x not in (".git", "node_modules")]
        out += [os.path.relpath(os.path.join(d, n), root) for n in names]
    return sorted(out)


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


def read_at(root: str, ref: str, path: str) -> str:
    """The file as committed at git ref `ref` (a release tag), or "" when the ref or the path does not exist there."""
    p = subprocess.run(["git", "-C", root, "show", f"{ref}:{path}"], capture_output=True, text=True)
    return p.stdout if p.returncode == 0 else ""


def versions(root: str, at: str | None = None) -> dict[str, str]:
    """Every package version string, from the working tree or, with `at`, from the tree of that git ref, so a release
    task's version criterion is checked against the release it names rather than against whatever is checked out."""
    def rd(path: str) -> str:
        return read_at(root, at, path) if at else read(root, path)

    v: dict[str, str] = {}
    m = re.search(r"^version\s*=\s*\"([^\"]+)\"", rd("pyproject.toml"), re.M)
    if m:
        v["pyproject.toml"] = m.group(1)
    m = re.search(r"__version__\s*=\s*\"([^\"]+)\"", rd("src/x402conf/__init__.py"))
    if m:
        v["src/x402conf/__init__.py"] = m.group(1)
    for f in ("ts/package.json", "ts/mcp/package.json"):
        if rd(f):
            v[f] = json.loads(rd(f)).get("version", "")
    for f in ("ts/package-lock.json", "ts/mcp/package-lock.json"):
        if rd(f):
            lock = json.loads(rd(f))
            v[f] = lock.get("version", "")
            v[f + " packages[\"\"]"] = lock.get("packages", {}).get("", {}).get("version", "")
    if rd("ts/mcp/server.json"):
        s = json.loads(rd("ts/mcp/server.json"))
        v["ts/mcp/server.json"] = s.get("version", "")
        for i, p in enumerate(s.get("packages", [])):
            tag = p.get("identifier", "").rsplit(":", 1)[-1] if p.get("registryType") == "oci" else ""
            v[f"ts/mcp/server.json packages[{i}]"] = p.get("version") or tag
    return v


# ---------------- files and components ----------------
# (id, kind, globs, what). The first component whose glob matches a file owns it, so specific ones come first.
COMPONENTS: list[tuple[str, str, tuple[str, ...], str]] = [
    ("interdeps", "code", ("tools/interdeps.py",), "this map's generator, drift check and PR gate"),
    ("interdeps-map", "doc", ("docs/INTERDEPENDENCY.md",), "this map"),
    ("interdeps-tests", "test", ("tests/test_interdeps.py",), "the generator's tests"),
    ("coverage", "code", ("tools/build_coverage.py",), "the generator of the check table in docs/COVERAGE.md"),
    ("contract", "contract", ("proofline.json", "proofline.json.sig", "guard/owner.pub"),
     "the owner-signed contract, its signature and key"),
    ("proposals", "contract", ("docs/proposals/**",), "proposed, unsigned contract addenda"),
    ("claims", "data", ("vv/claims.json",), "the tasks claimed done"),
    ("vv", "code", ("tools/vv.py", "tools/verify-sig.mjs"), "the V&V runner and the signature check"),
    ("doc-examples", "code", ("tools/doc_examples.py",),
     "the runnable docs examples: the fences marked in the docs, run against the bundled mock in CI"),
    ("vv-doc", "doc", ("docs/VV.md",), "the V&V matrix"),
    ("catalog", "code", ("src/x402conf/spec.py", "src/x402conf/types.py"), "the check catalogue and its types"),
    ("pytest-plugin", "code", ("src/x402conf/pytest_plugin.py",), "the pytest plugin"),
    ("devnet", "code", ("src/x402conf/devnet/**", "src/x402conf/fixtures/**"),
     "the devnet runner, its node helpers and fixtures"),
    ("py-suite", "code", ("src/x402conf/**", "pyproject.toml"), "the Python suite: CLI, harness, mock and package"),
    ("py-tests", "test", ("tests/**",), "the Python tests"),
    ("py-examples", "code", ("examples/**",), "the Python example server"),
    ("ts-catalog", "code", ("ts/src/catalog.ts",), "the TypeScript catalogue, kept identical to the Python one"),
    ("ts-cli", "code", ("ts/src/cli.ts",), "the x402conf-svm CLI"),
    ("ts-suite", "code", ("ts/src/**", "ts/package.json", "ts/package-lock.json", "ts/tsconfig.json", "ts/LICENSE"),
     "the TypeScript suite, library and matchers"),
    ("ts-tests", "test", ("ts/test/**", "ts/vitest/**", "ts/vitest.config.mjs"),
     "the TypeScript tests and the vitest matchers"),
    ("ts-examples", "code", ("ts/example/**",), "the TypeScript example servers"),
    ("ts-readme", "doc", ("ts/README.md",), "the npm package README"),
    ("mcp-readme", "doc", ("ts/mcp/README.md",), "the MCP package README"),
    ("mcp-tests", "test", ("ts/mcp/test/**",), "the MCP tests"),
    ("mcp", "code", ("ts/mcp/**",), "the MCP server and the AI SDK and LangChain tools"),
    ("action", "code", ("action.yml",), "the GitHub Action"),
    ("distribution", "deploy",
     ("ts/docker/**", "ts/ci/**", ".github/workflows/mcp-registry.yml", ".github/workflows/pages.yml"),
     "the Docker image, the GitLab CI component, the MCP Registry and Pages publishing"),
    ("mutation-matrix", "test", ("tools/mutation_matrix.py", "docs/site/mutation-matrix.json"),
     "the mutation matrix: which faulty build each check is proven to catch, built from the catalogue, on the site"),
    ("site", "doc", ("docs/site/**",), "the project site"),
    ("lean", "code", ("lean/**", "tools/lean_axioms.py"), "the Lean models and the axiom check"),
    ("corpus-schemas", "data", ("corpus/*.schema.json",), "the corpus case and report schemas"),
    ("corpus", "data", ("corpus/**",), "the corpus of anonymised cases and its fixtures"),
    ("evidence", "data", ("evidence/**",), "hashed evidence from live and devnet runs"),
    ("impl-matrix", "code", (".github/workflows/impl-matrix.yml",),
     "the implementation matrix workflow: the probe against stock servers at pinned versions, one job per evidence row"),
    ("compat-matrix", "code", ("tools/compat_matrix.py", ".github/workflows/compat-matrix.yml"),
     "the compatibility matrix: docs/compat-matrix.json and the table in docs/MATRIX.md, generated from the "
     "implementation-matrix runs and rebuilt on a schedule"),
    ("readme", "doc", ("README.md", "RELEASES.md"), "the project README and the release map"),
    ("changelog", "doc", ("CHANGELOG.md",), "the changelog"),
    ("docs", "doc", ("docs/**",), "architecture, spec mapping, threat model, usage, adoption, matrix and roadmap"),
    ("community", "doc", ("CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "SECURITY.md", ".github/ISSUE_TEMPLATE/**",
                          ".github/pull_request_template.md", ".github/CODEOWNERS"),
     "contributing, conduct, security and templates"),
    ("legal", "doc", ("LICENSE", "NOTICE"), "the licence and notice"),
    ("ci", "gate", (".github/workflows/ci.yml", ".github/truedone.yml", ".gitignore"),
     "CI: lint, tests, Lean, the TS and MCP builds, V&V, red-green and this map"),
]
GATE_KINDS = ("doc", "contract", "test")
U, R = "update", "review"
EDGES: list[tuple[str, str, str]] = [
    ("interdeps", "interdeps-map", U), ("interdeps", "interdeps-tests", R), ("interdeps", "ci", R),
    ("interdeps-tests", "ci", R), ("coverage", "interdeps-map", U), ("coverage", "docs", U), ("coverage", "py-tests", R),
    ("catalog", "coverage", R), ("contract", "interdeps-map", U), ("contract", "vv", R), ("contract", "vv-doc", R),
    ("contract", "claims", R), ("proposals", "interdeps-map", U), ("proposals", "contract", R),
    ("claims", "interdeps-map", U), ("claims", "vv", R), ("vv", "ci", R), ("vv", "vv-doc", R),
    ("docs", "doc-examples", R), ("ts-cli", "doc-examples", R), ("py-suite", "doc-examples", R), ("doc-examples", "ci", R),
    ("catalog", "interdeps-map", U), ("catalog", "ts-catalog", U), ("catalog", "docs", R), ("catalog", "readme", R),
    ("catalog", "mutation-matrix", U), ("py-suite", "mutation-matrix", R), ("ts-tests", "mutation-matrix", R),
    ("mutation-matrix", "site", R), ("mutation-matrix", "ci", R),
    ("catalog", "py-tests", R), ("catalog", "py-suite", R), ("catalog", "vv-doc", R), ("catalog", "changelog", R),
    ("ts-catalog", "ts-tests", R), ("ts-catalog", "catalog", R), ("py-suite", "py-tests", R),
    ("py-suite", "interdeps-map", U), ("py-suite", "readme", R), ("py-suite", "docs", R), ("py-suite", "pytest-plugin", R),
    ("py-suite", "action", R), ("py-suite", "py-examples", R), ("devnet", "py-tests", R), ("devnet", "evidence", R),
    ("devnet", "docs", R), ("pytest-plugin", "py-tests", R), ("pytest-plugin", "readme", R), ("ts-cli", "ts-tests", R),
    ("ts-cli", "ts-readme", R), ("ts-cli", "interdeps-map", U), ("ts-cli", "action", R), ("ts-suite", "ts-tests", R),
    ("ts-suite", "ts-readme", R), ("ts-suite", "mcp", R), ("ts-suite", "ts-examples", R), ("ts-suite", "distribution", R),
    ("ts-suite", "interdeps-map", U), ("mcp", "mcp-tests", R), ("mcp", "mcp-readme", R), ("mcp", "distribution", R),
    ("mcp", "interdeps-map", U), ("action", "readme", R), ("action", "docs", R), ("action", "interdeps-map", U),
    ("action", "ci", R), ("lean", "docs", R), ("lean", "ci", R), ("corpus-schemas", "corpus", R),
    ("corpus-schemas", "py-tests", R), ("corpus", "docs", R), ("evidence", "docs", R), ("py-examples", "docs", R),
    ("ts-examples", "ts-readme", R), ("readme", "site", R), ("docs", "site", R), ("docs", "readme", R),
    ("docs", "interdeps-map", U), ("readme", "interdeps-map", U), ("ts-readme", "interdeps-map", U),
    ("mcp-readme", "interdeps-map", U), ("community", "interdeps-map", U), ("ci", "community", R),
    ("distribution", "readme", R),
    ("ts-cli", "impl-matrix", R), ("ts-examples", "impl-matrix", R), ("py-examples", "impl-matrix", R),
    ("impl-matrix", "evidence", R),
    ("evidence", "compat-matrix", R), ("compat-matrix", "docs", R), ("compat-matrix", "ci", R),
]
ACK = re.compile(r"^[ \t]*Interdeps-Ack:[ \t]*(?P<ids>[A-Za-z0-9_.-]+(?:[ \t]*,[ \t]*[A-Za-z0-9_.-]+)*)"
                 r"[ \t]+-[ \t]+(?P<why>\S.*)$", re.M)


def owner(path: str) -> str | None:
    """The first component whose glob matches the path."""
    return next((c for c, _k, globs, _w in COMPONENTS if any(glob_match(path, g) for g in globs)), None)


def coverage(root: str) -> list[str]:
    """Tracked files no component covers, components that cover nothing, and bad edges."""
    files = tracked(root)
    ids = [c for c, *_ in COMPONENTS]
    out = [f"{f}: no component covers it" for f in files if owner(f) is None and f != ".git"]
    owned = {owner(f) for f in files}
    out += [f"component {c} covers no tracked file" for c in ids if c not in owned]
    seen = set()
    for a, b, k in EDGES:
        if a not in ids or b not in ids:
            out.append(f"edge {a} -> {b}: unknown component")
        if k not in (U, R) or a == b or (a, b) in seen:
            out.append(f"edge {a} -> {b}: bad kind, a loop or listed twice")
        seen.add((a, b))
    return out


def acks(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in ACK.finditer(text or ""):
        for i in re.split(r"\s*,\s*", m.group("ids").strip()):
            out[i] = m.group("why").strip()
    return out


def gate(paths: list[str], text: str) -> dict[str, Any]:
    """A touched component fails the gate only for its direct downstream components of kind doc, contract or test
    that are neither touched nor acknowledged. Everything else it reaches is listed for review and never fails."""
    hit = {o for p in paths if (o := owner(p))}
    kind = {c: k for c, k, *_ in COMPONENTS}
    need: dict[str, list[str]] = {}
    review: dict[str, list[str]] = {}
    for a, b, k in EDGES:
        if a in hit and b not in hit:
            (need if kind[b] in GATE_KINDS else review).setdefault(b, []).append(f"downstream of {a} ({k})")
        if b in hit and a not in hit:
            review.setdefault(a, []).append(f"upstream of {b} ({k})")
    near = hit | set(need) | set(review)
    for a, b, k in EDGES:
        if a in near - hit and b not in near:
            review.setdefault(b, []).append(f"two steps out, via {a} ({k})")
    ack = acks(text)
    return {"changed": sorted(hit), "required": dict(sorted(need.items())), "review": dict(sorted(review.items())),
            "missing": sorted(set(need) - set(ack)), "unknown_acks": sorted(set(ack) - set(kind))}


def run_gate(root: str, base: str, head: str) -> int:
    def git(*a: str) -> str:
        p = subprocess.run(["git", *a], cwd=root, capture_output=True, text=True)
        if p.returncode:
            raise SystemExit(f"git {' '.join(a)} failed: {p.stderr.strip()}")
        return p.stdout
    paths = [x for x in git("diff", "--name-only", "--no-renames", f"{base}...{head}").splitlines() if x]
    g = gate(paths, git("log", "--format=%B", f"{base}..{head}") + "\n" + os.environ.get("PR_BODY", ""))
    touched = ", ".join(g["changed"]) or "none"
    print(f"interdeps gate: {len(paths)} changed file(s) touch {len(g['changed'])} component(s): {touched}")
    for c, why in g["required"].items():
        print(f"  {'ok ' if c not in g['missing'] else 'MISSING'} {c}: {'; '.join(why)}")
    if g["review"]:
        print(f"  review only ({len(g['review'])} component(s), these never fail the gate):")
        for c, why in g["review"].items():
            print(f"    {c}: {'; '.join(why)}")
    for c in g["unknown_acks"]:
        print(f"  Interdeps-Ack names an unknown component: {c}")
    if g["missing"] or g["unknown_acks"]:
        if g["missing"]:
            print("\nTouch these components in the same PR, or acknowledge them in the PR body or a commit message:\n")
            print(f"Interdeps-Ack: {', '.join(g['missing'])} - <why they need no change>")
        return 1
    print("interdeps gate: ok")
    return 0


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

    o += ["## Components", "",
          "Every tracked file belongs to one component (`COMPONENTS` in `tools/interdeps.py`, first match wins). An update "
          "edge means the downstream component changes in the same change, a review edge means it is read and changed if "
          "the change reaches it. The PR gate (`--gate`) fails only when a touched component's direct downstream doc, "
          "contract or test component is neither touched nor acknowledged with `Interdeps-Ack: <component> - <reason>`; "
          "everything else it reaches is listed for review.", "", "```mermaid", "graph LR"]
    for c, k, _g, _w in COMPONENTS:
        o.append(f'  {c.replace("-", "_")}["{c}<br/>{k}"]')
    for a, b, k in EDGES:
        o.append(f'  {a.replace("-", "_")} {"==>" if k == U else "-.->"} {b.replace("-", "_")}')
    # No per-component file count: it changes whenever two pull requests add files in parallel, and each merge would
    # leave the other's committed map stale. The patterns are the structure; --check still fails on a file no
    # component covers and on a component that covers none.
    o += ["```", "", "| component | kind | covers | what |", "|---|---|---|---|"]
    for c, k, g, w in COMPONENTS:
        o.append(f"| {c} | {k} | {'; '.join(f'`{x}`' for x in g)} | {w} |")
    o += ["", "| from | to | kind |", "|---|---|---|"] + [f"| {a} | {b} | {k} |" for a, b, k in EDGES]
    gaps = [f for f in files if owner(f) is None]
    if gaps:
        o += ["", "Files no component covers: " + ", ".join(f"`{f}`" for f in gaps)]
    o.append("")

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
    if "--gate" in argv:
        if "--base" not in argv:
            print("usage: tools/interdeps.py --gate --base REF [--head REF]", file=sys.stderr)
            return 2
        head = argv[argv.index("--head") + 1] if "--head" in argv else "HEAD"
        return run_gate(root, argv[argv.index("--base") + 1], head)
    if "--check" in argv:
        want = build(root)
        bad = coverage(root)
        for x in bad:
            print("coverage:", x, file=sys.stderr)
        if read(root, MAP) != want:
            print(f"{MAP} is stale: run python3 tools/interdeps.py and commit it", file=sys.stderr)
            return 1
        if bad:
            return 1
        print(f"{MAP} is up to date and every tracked file is in a component")
        return 0
    if "--drift" in argv:
        p = drift(root)
        for x in p:
            print("drift:", x, file=sys.stderr)
        print(f"{len(p)} drift problem(s)")
        return 1 if p else 0
    if "--versions" in argv:
        want_v = argv[argv.index("--versions") + 1] if argv.index("--versions") + 1 < len(argv) else ""
        at = argv[argv.index("--at") + 1] if "--at" in argv and argv.index("--at") + 1 < len(argv) else None
        v = versions(root, at)
        if at and not v:
            print(f"version: git ref {at} has no versioned files (does the ref exist here?)", file=sys.stderr)
        bad = {f: x for f, x in v.items() if x != want_v}
        for f, x in sorted(bad.items()):
            print(f"version: {f} is {x}, not {want_v}", file=sys.stderr)
        print(f"{len(v) - len(bad)}/{len(v)} version(s) are {want_v}" + (f" at {at}" if at else ""))
        return 1 if bad or not v or not want_v else 0
    with open(os.path.join(root, MAP), "w", encoding="utf-8") as f:
        f.write(build(root))
    print(f"wrote {MAP}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
