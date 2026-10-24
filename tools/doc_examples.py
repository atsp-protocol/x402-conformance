#!/usr/bin/env python3
"""Run the docs' examples, so a broken one fails the build (XC-27).

    python3 tools/doc_examples.py --list [--root DIR] [--only FILE]     the marked examples
    python3 tools/doc_examples.py --run  [--root DIR] [--only FILE]     run them; exit 1 and name each one that fails

An example is a fenced block in README.md, docs/*.md or examples/**/README.md whose previous non-blank line is the
marker <!-- runnable: <kind> [key="value" ...] -->, invisible in the rendered page. The kinds:

  cli      every line that is not blank or a comment runs as a shell command from the tree root, in order, with
           src on PYTHONPATH. A trailing comment can say "exits N" to expect that exit code; the default is 0.
           subst="old=new;old2=new2" rewrites each line first, so a published command (npx -y x402-conformance-svm)
           runs the tree's own build (node ts/dist/src/cli.js). Nothing here reaches the network: mark only the
           commands that run against the bundled mock.
  actions  a GitHub Actions workflow or a list of steps: parses as YAML, and every step that uses this action gives
           only inputs action.yml declares.
  gitlab   a .gitlab-ci.yml fragment: parses as YAML, includes the tracked GitLab template by its path, and sets only
           the variables the template or the ci entry point read.
  python   the block parses as Python.
  ts       the block parses as TypeScript (the compiler in ts/node_modules, syntax only).
  json     the block parses as JSON.
"""
from __future__ import annotations

import ast
import glob
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = ["README.md", "docs/*.md", "examples/**/README.md"]
MARKER = re.compile(r"^\s*<!--\s*runnable:\s*(?P<kind>[a-z]+)(?P<attrs>(?:\s+[a-z_]+=(?:\"[^\"]*\"|\S+))*)\s*-->\s*$")
ATTR = re.compile(r"([a-z_]+)=(?:\"([^\"]*)\"|(\S+))")
FENCE = re.compile(r"^(`{3,})\s*([\w-]*)")
EXITS = re.compile(r"#.*\bexits\s+(\d+)\b")
ACTION = "atsp-protocol/x402-conformance"
GITLAB_TEMPLATE = "ts/ci/gitlab/x402-conformance.gitlab-ci.yml"
KINDS = ("cli", "actions", "gitlab", "python", "ts", "json")
COMMAND_TIMEOUT = 300


@dataclass
class Example:
    file: str
    line: int          # the fence's line, 1-based
    kind: str
    attrs: dict[str, str]
    lang: str
    body: list[str]
    problems: list[str] = field(default_factory=list)

    @property
    def where(self) -> str:
        return f"{self.file}:{self.line}"


# ---------------- finding the examples ----------------
def doc_files(root: str, only: str | None = None) -> list[str]:
    if only:
        return [only]
    out: list[str] = []
    for pat in DOCS:
        out += sorted(os.path.relpath(p, root) for p in glob.glob(os.path.join(root, pat), recursive=True))
    return out


def parse(root: str, rel: str) -> list[Example]:
    """The marked fenced blocks of one file, and a problem for a marker that is not followed by a fence."""
    with open(os.path.join(root, rel), encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    out: list[Example] = []
    i = 0
    while i < len(lines):
        m = MARKER.match(lines[i])
        if not m:
            i += 1
            continue
        kind = m.group("kind")
        attrs = {k: v if v is not None else w for k, v, w in ATTR.findall(m.group("attrs"))}
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        f = FENCE.match(lines[j]) if j < len(lines) else None
        if not f:
            out.append(Example(rel, i + 1, kind, attrs, "", [],
                               [f"the runnable marker on line {i + 1} is not followed by a fenced block"]))
            i += 1
            continue
        fence, lang = f.group(1), f.group(2)
        k = j + 1
        while k < len(lines) and not lines[k].startswith(fence):
            k += 1
        ex = Example(rel, j + 1, kind, attrs, lang, lines[j + 1:k])
        if k >= len(lines):
            ex.problems.append("the fenced block is not closed")
        if kind not in KINDS:
            ex.problems.append(f"unknown kind {kind!r}; one of {', '.join(KINDS)}")
        out.append(ex)
        i = k + 1
    return out


def examples(root: str, only: str | None = None) -> list[Example]:
    return [e for rel in doc_files(root, only) for e in parse(root, rel)]


# ---------------- the checks ----------------
def _yaml() -> Any:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:  # pragma: no cover  (CI installs it; the error names the fix)
        raise SystemExit("doc_examples: a yaml example is marked, so this needs PyYAML: pip install pyyaml") from None
    return yaml


_built: set[str] = set()


def ensure_build(root: str) -> str | None:
    """The cli and ts kinds need the tree's own Node build. When ts/node_modules or ts/dist is missing (the V&V job
    checks out a bare tree), install and build once; the reason is returned when that fails."""
    ts_dir = os.path.join(root, "ts")
    if root in _built or not os.path.isfile(os.path.join(ts_dir, "package.json")):
        return None
    if os.path.isdir(os.path.join(ts_dir, "node_modules")) and os.path.isfile(os.path.join(ts_dir, "dist", "src", "cli.js")):
        _built.add(root)
        return None
    for cmd in (["npm", "ci", "--silent", "--no-audit", "--no-fund"], ["npx", "tsc", "-p", "."]):
        p = subprocess.run(cmd, cwd=ts_dir, capture_output=True, text=True, timeout=600)
        if p.returncode != 0:
            return f"`{' '.join(cmd)}` in ts failed: " + (p.stderr or p.stdout).strip().splitlines()[-1]
    _built.add(root)
    return None


def substitute(line: str, subst: str) -> str:
    for pair in filter(None, subst.split(";")):
        old, _, new = pair.partition("=")
        line = line.replace(old, new)
    return line


def commands(ex: Example) -> list[tuple[str, int]]:
    """The (command, expected exit) pairs of a cli block, with continuation lines joined."""
    out: list[tuple[str, int]] = []
    joined: list[str] = []
    for raw in ex.body + [""]:
        if raw.rstrip().endswith("\\"):
            joined.append(raw.rstrip()[:-1])
            continue
        line = " ".join(joined + [raw]).strip()
        joined = []
        if not line or line.startswith("#"):
            continue
        m = EXITS.search(line)
        want = int(m.group(1)) if m else 0
        cmd = re.sub(r"\s+#.*$", "", line) if "#" in line else line
        out.append((substitute(cmd, ex.attrs.get("subst", "")), want))
    return out


def check_cli(root: str, ex: Example) -> None:
    built = ensure_build(root)
    if built:
        ex.problems.append(built)
        return
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.join(root, "src") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.setdefault("X402CONF_VIA", "cli-py")
    for cmd, want in commands(ex):
        try:
            p = subprocess.run(["sh", "-c", cmd], cwd=root, env=env, capture_output=True, text=True, timeout=COMMAND_TIMEOUT)
        except subprocess.TimeoutExpired:
            ex.problems.append(f"`{cmd}` did not finish in {COMMAND_TIMEOUT} s")
            continue
        if p.returncode != want:
            tail = (p.stderr or p.stdout).strip().splitlines()[-3:]
            ex.problems.append(f"`{cmd}` exited {p.returncode}, expected {want}: " + " | ".join(tail))


def action_inputs(root: str) -> set[str]:
    doc = _yaml().safe_load(open(os.path.join(root, "action.yml"), encoding="utf-8"))
    return set((doc or {}).get("inputs") or {})


def check_actions(root: str, ex: Example) -> None:
    try:
        doc = _yaml().safe_load("\n".join(ex.body))
    except Exception as e:  # noqa: BLE001  the reason is the finding
        ex.problems.append(f"not valid YAML: {str(e).splitlines()[0]}")
        return
    steps: list[dict[str, Any]] = []
    if isinstance(doc, list):
        steps = [s for s in doc if isinstance(s, dict)]
    elif isinstance(doc, dict):
        for job in (doc.get("jobs") or {}).values():
            steps += [s for s in (job or {}).get("steps") or [] if isinstance(s, dict)]
    ours = [s for s in steps if str(s.get("uses", "")).startswith(ACTION + "@")]
    if not steps:
        ex.problems.append("no workflow jobs or steps in the block")
        return
    inputs = action_inputs(root)
    for s in ours:
        for key in (s.get("with") or {}):
            if key not in inputs:
                ex.problems.append(f"step `{s['uses']}` gives input `{key}`, which action.yml does not declare")


def gitlab_variables(root: str) -> set[str]:
    """The variables the template and the ci entry point read: every X402 name in either file."""
    names: set[str] = set()
    for rel in (GITLAB_TEMPLATE, "ts/src/cli.ts"):
        try:
            with open(os.path.join(root, rel), encoding="utf-8") as fh:
                names |= set(re.findall(r"X402(?:CONF)?_[A-Z_]+", fh.read()))
        except FileNotFoundError:
            pass
    return names


def check_gitlab(root: str, ex: Example) -> None:
    try:
        doc = _yaml().safe_load("\n".join(ex.body))
    except Exception as e:  # noqa: BLE001
        ex.problems.append(f"not valid YAML: {str(e).splitlines()[0]}")
        return
    if not isinstance(doc, dict):
        ex.problems.append("not a .gitlab-ci.yml mapping")
        return
    includes = doc.get("include") or []
    remotes = [str(i.get("remote", "")) for i in includes if isinstance(i, dict)]
    if not any(r.endswith("/" + GITLAB_TEMPLATE) for r in remotes):
        ex.problems.append(f"the include does not name the tracked template {GITLAB_TEMPLATE}")
    elif not os.path.isfile(os.path.join(root, GITLAB_TEMPLATE)):
        ex.problems.append(f"{GITLAB_TEMPLATE} is not in the tree")
    allowed = gitlab_variables(root)
    for name, job in doc.items():
        if name == "include" or not isinstance(job, dict):
            continue
        for key in (job.get("variables") or {}):
            if key not in allowed:
                ex.problems.append(f"job `{name}` sets `{key}`, which neither the template nor the ci entry point reads")


def check_python(root: str, ex: Example) -> None:
    try:
        ast.parse("\n".join(ex.body), filename=ex.where)
    except SyntaxError as e:
        ex.problems.append(f"not valid Python: {e.msg} (line {e.lineno})")


def check_ts(root: str, ex: Example) -> None:
    ts_dir = os.path.join(root, "ts")
    built = ensure_build(root)
    if built:
        ex.problems.append(built)
        return
    if not os.path.isdir(os.path.join(ts_dir, "node_modules", "typescript")):
        ex.problems.append("a ts example is marked, but ts/node_modules has no typescript: run npm ci in ts")
        return
    with tempfile.NamedTemporaryFile("w", suffix=".ts", delete=False, encoding="utf-8") as fh:
        fh.write("\n".join(ex.body))
        path = fh.name
    script = ("const ts=require('typescript');const src=require('fs').readFileSync(process.argv[1],'utf8');"
              "const r=ts.transpileModule(src,{reportDiagnostics:true,compilerOptions:{module:ts.ModuleKind.ESNext}});"
              "const d=(r.diagnostics||[]).map(x=>ts.flattenDiagnosticMessageText(x.messageText,' '));"
              "if(d.length){console.log(d.join(' | '));process.exit(1)}")
    try:
        p = subprocess.run(["node", "-e", script, path], cwd=ts_dir, capture_output=True, text=True, timeout=120)
    finally:
        os.unlink(path)
    if p.returncode != 0:
        ex.problems.append("not valid TypeScript: " + (p.stdout or p.stderr).strip().splitlines()[-1])


def check_json(root: str, ex: Example) -> None:
    try:
        json.loads("\n".join(ex.body))
    except ValueError as e:
        ex.problems.append(f"not valid JSON: {e}")


CHECKS = {"cli": check_cli, "actions": check_actions, "gitlab": check_gitlab, "python": check_python, "ts": check_ts,
          "json": check_json}


def run(root: str, only: str | None = None) -> tuple[list[Example], list[str]]:
    exs = examples(root, only)
    for ex in exs:
        if not ex.problems:
            CHECKS[ex.kind](root, ex)
    problems = [f"{ex.where}: {p}" for ex in exs for p in ex.problems]
    return exs, problems


def main(argv: list[str]) -> int:
    root = ROOT
    only = None
    mode = None
    args = list(argv)
    while args:
        a = args.pop(0)
        if a in ("--list", "--run"):
            mode = a
        elif a == "--root" and args:
            root = os.path.abspath(args.pop(0))
        elif a == "--only" and args:
            only = args.pop(0)
        else:
            print(__doc__.strip().splitlines()[2].strip())
            print(__doc__.strip().splitlines()[3].strip())
            return 2
    if mode == "--list":
        for ex in examples(root, only):
            n = len(commands(ex)) if ex.kind == "cli" else len(ex.body)
            print(f"{ex.where} {ex.kind} ({n} {'command' if ex.kind == 'cli' else 'line'}{'' if n == 1 else 's'})"
                  + (" " + " ".join(f"{k}={shlex.quote(v)}" for k, v in ex.attrs.items()) if ex.attrs else ""))
        return 0
    if mode != "--run":
        print("usage: python3 tools/doc_examples.py --list|--run [--root DIR] [--only FILE]")
        return 2
    exs, problems = run(root, only)
    for p in problems:
        print(f"doc_examples: {p}")
    kinds: dict[str, int] = {}
    for ex in exs:
        kinds[ex.kind] = kinds.get(ex.kind, 0) + 1
    summary = ", ".join(f"{v} {k}" for k, v in sorted(kinds.items()))
    print(f"doc examples: {len(exs)} run ({summary or 'none'}), {len(problems)} problem(s)")
    return 1 if problems or not exs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
