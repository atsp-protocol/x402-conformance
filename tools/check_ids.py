"""Stable check ids (XC-53).

The catalogue in src/x402conf/spec.py is the source. This writes docs/check-ids.json,
one object per id: profile, one-line property, spec basis, first release and status.
An id is never reused or removed. A change of meaning needs a new id. A deprecation
keeps the original property and is listed in CHANGELOG.md.

  python3 tools/check_ids.py
  python3 tools/check_ids.py --check --since v1.6.0

--check fails when the committed registry is stale, when an id published at the
--since tag is missing, or when that id's property changed without a deprecation entry.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from typing import Any

REGISTRY = "docs/check-ids.json"
SPEC = "src/x402conf/spec.py"
TAG = re.compile(r"v\d+\.\d+\.\d+")


def oneline(text: str) -> str:
    return " ".join(text.split())


def deprecation_mentioned(changelog: str, cid: str) -> bool:
    """A deprecation entry names the id and says it is deprecated."""
    word = re.compile(rf"\b{re.escape(cid)}\b")
    for line in changelog.splitlines():
        if word.search(line) and re.search(r"deprecat", line, re.I):
            return True
    return False


def meaning_problems(since: dict[str, dict[str, Any]], registry: list[dict[str, Any]], changelog: str) -> list[str]:
    """Removed id, reused id, or a property change with no deprecation entry.

    A reused id is the same id with a new property after a deprecation entry: the entry
    does not license a new meaning. A silent change is a new property with no entry.
    """
    by_id = {str(e.get("id")): e for e in registry}
    out: list[str] = []
    for cid, meta in since.items():
        if cid not in by_id:
            out.append(f"removed {cid}")
            continue
        got = by_id[cid]
        same = got.get("property") == oneline(str(meta.get("basis") or "")) and got.get("profile") == meta.get("profile")
        if same:
            continue
        if got.get("property") != oneline(str(meta.get("basis") or "")) and deprecation_mentioned(changelog, cid):
            out.append(f"reused {cid}")
        else:
            out.append(f"silent {cid}")
    return out


def _catalog_module(root: str) -> Any:
    sys.path.insert(0, os.path.join(root, "tools"))
    import interdeps  # noqa: E402

    return interdeps


def catalog_from_source(root: str, src: str) -> dict[str, dict[str, Any]]:
    """Parse a spec.py CATALOG the same way tools/interdeps.py does."""
    interdeps = _catalog_module(root)
    with tempfile.TemporaryDirectory() as d:
        dest = os.path.join(d, "src", "x402conf")
        os.makedirs(dest)
        with open(os.path.join(dest, "spec.py"), "w", encoding="utf-8") as f:
            f.write(src)
        return interdeps.catalog(d)


def catalog_at(root: str, rev: str) -> dict[str, dict[str, Any]]:
    try:
        src = subprocess.check_output(
            ["git", "-C", root, "show", f"{rev}:{SPEC}"], text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        return {}
    return catalog_from_source(root, src)


def current_catalog(root: str) -> dict[str, dict[str, Any]]:
    return _catalog_module(root).catalog(root)


def release_tags(root: str) -> list[str]:
    raw = subprocess.check_output(["git", "-C", root, "tag", "-l", "v[0-9]*"], text=True)
    tags = [t for t in raw.split() if TAG.fullmatch(t)]

    def key(tag: str) -> tuple[int, ...]:
        return tuple(int(p) for p in tag[1:].split("."))

    return sorted(set(tags), key=key)


def first_releases(root: str, current: dict[str, dict[str, Any]]) -> dict[str, str]:
    found: dict[str, str] = {}
    for tag in release_tags(root):
        for cid in catalog_at(root, tag):
            found.setdefault(cid, tag)
    for cid in current:
        found.setdefault(cid, "unreleased")
    return found


def make_entry(cid: str, meta: dict[str, Any], first: str, status: str) -> dict[str, str]:
    basis = oneline(str(meta.get("basis") or ""))
    return {
        "id": cid,
        "profile": str(meta.get("profile") or ""),
        "property": basis,
        "basis": basis,
        "first_release": first,
        "status": status,
    }


def build_registry(current: dict[str, dict[str, Any]], since: dict[str, dict[str, Any]],
                   first: dict[str, str]) -> list[dict[str, str]]:
    out = [make_entry(cid, meta, first.get(cid, "unreleased"), "active") for cid, meta in current.items()]
    for cid, meta in since.items():
        if cid not in current:
            out.append(make_entry(cid, meta, first.get(cid, "unreleased"), "deprecated"))
    return out


def read_json(path: str) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_registry(path: str, ids: list[dict[str, str]]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"ids": ids}, f, indent=2)
        f.write("\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Write or check the stable check-id registry.")
    p.add_argument("--check", action="store_true", help="fail if the registry is stale or an id changed meaning")
    p.add_argument("--since", default="", help="release tag whose published ids must still match, e.g. v1.6.0")
    p.add_argument("--root", default=".")
    args = p.parse_args(argv)
    root = os.path.abspath(args.root)
    current = current_catalog(root)
    since: dict[str, dict[str, Any]] = {}
    if args.since:
        if subprocess.call(
                ["git", "-C", root, "rev-parse", "--verify", "--quiet", args.since + "^{commit}"],
                stdout=subprocess.DEVNULL) != 0:
            print(f"tag {args.since} is not in this clone")
            return 1
        since = catalog_at(root, args.since)
    if not args.check:
        if not args.since:
            print("pass --since so first_release is taken from the tags")
            return 1
        ids = build_registry(current, since, first_releases(root, current))
        write_registry(os.path.join(root, REGISTRY), ids)
        print(f"wrote {len(ids)} ids to {REGISTRY}")
        return 0
    path = os.path.join(root, REGISTRY)
    if not os.path.isfile(path):
        print(f"missing {REGISTRY}")
        return 1
    committed = read_json(path).get("ids")
    expected = build_registry(current, since, first_releases(root, current))
    problems: list[str] = []
    if committed != expected:
        problems.append(f"stale {REGISTRY}")
    if args.since:
        changelog = open(os.path.join(root, "CHANGELOG.md"), encoding="utf-8").read()
        problems.extend(meaning_problems(since, committed or [], changelog))
    if problems:
        print("\n".join(problems))
        return 1
    print(f"ok {len(expected)} ids")
    return 0


if __name__ == "__main__":
    sys.exit(main())
