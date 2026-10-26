"""Spec-clause anchors and the USENIX crosswalk (XC-55).

Normative check ids in docs/check-ids.json carry an anchor: an upstream spec
file, the pinned x402-foundation/x402 commit, and a line range. The quoted
text is those lines joined with a newline, and quoted_text_sha256 is its
SHA-256. --check --offline compares that hash to the vendored snapshot under
docs/spec-snapshots/<commit>/. It does not use the network.

--drift COMMIT lists the normative ids whose anchored lines differ in the
snapshot of COMMIT. --crosswalk usenix-2026 --check requires every facilitator
check (an id that starts with F) to map to zero or more rules, and requires
SR1-SR8 and Server-SR1-SR2 each to be mapped or named as a gap with a task id.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

REGISTRY = "docs/check-ids.json"
SNAPSHOTS = "docs/spec-snapshots"
CROSSWALK = "docs/crosswalk/usenix-2026.json"
RULES = tuple(f"SR{n}" for n in range(1, 9)) + ("Server-SR1", "Server-SR2")
TASK_ID = re.compile(r"XC-\d+")


def quote(lines: list[str]) -> str:
    return "\n".join(lines)


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def snapshot_lines(root: str, commit: str, spec_file: str) -> list[str]:
    path = os.path.join(root, SNAPSHOTS, commit, spec_file)
    with open(path, encoding="utf-8") as f:
        return f.read().splitlines()


def anchored_text(root: str, anchor: dict) -> str:
    lines = snapshot_lines(root, anchor["upstream_commit"], anchor["spec_file"])
    start, end = int(anchor["line_start"]), int(anchor["line_end"])
    if start < 1 or end < start or end > len(lines):
        raise ValueError(f"line range {start}-{end} outside {anchor['spec_file']}")
    return quote(lines[start - 1:end])


def load_checks(root: str) -> list[dict]:
    with open(os.path.join(root, REGISTRY), encoding="utf-8") as f:
        data = json.load(f)
    checks = data.get("checks")
    if not isinstance(checks, list):
        raise ValueError("docs/check-ids.json has no checks list")
    return checks


def offline_problems(root: str) -> list[str]:
    problems: list[str] = []
    for check in load_checks(root):
        if check.get("profile") != "normative":
            continue
        anchor = check.get("anchor")
        if not isinstance(anchor, dict):
            problems.append(f"missing anchor {check.get('id')}")
            continue
        try:
            text = anchored_text(root, anchor)
        except (OSError, ValueError, KeyError) as exc:
            problems.append(f"anchor {check.get('id')}: {exc}")
            continue
        if digest(text) != anchor.get("quoted_text_sha256"):
            problems.append(f"quote changed {check.get('id')}")
    return problems


def drifted(root: str, commit: str) -> list[str]:
    changed: list[str] = []
    for check in load_checks(root):
        if check.get("profile") != "normative":
            continue
        anchor = check["anchor"]
        current = anchored_text(root, anchor)
        other = dict(anchor)
        other["upstream_commit"] = commit
        if anchored_text(root, other) != current:
            changed.append(check["id"])
    return changed


def crosswalk_problems(root: str) -> list[str]:
    with open(os.path.join(root, CROSSWALK), encoding="utf-8") as f:
        doc = json.load(f)
    mappings = doc.get("mappings") or {}
    rules = doc.get("rules") or {}
    problems: list[str] = []
    for check in load_checks(root):
        cid = check.get("id", "")
        if not cid.startswith("F"):
            continue
        mapped = mappings.get(cid)
        if not isinstance(mapped, list):
            problems.append(f"unmapped facilitator check {cid}")
    for rule in RULES:
        entry = rules.get(rule)
        if not isinstance(entry, dict):
            problems.append(f"missing rule {rule}")
            continue
        gap = entry.get("gap")
        checks = entry.get("checks")
        if isinstance(gap, str) and TASK_ID.fullmatch(gap):
            continue
        if isinstance(checks, list) and checks:
            continue
        problems.append(f"rule {rule} is neither mapped nor a gap")
    return problems


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Check spec anchors and the USENIX crosswalk.")
    p.add_argument("--check", action="store_true")
    p.add_argument("--offline", action="store_true")
    p.add_argument("--drift", default="", metavar="COMMIT")
    p.add_argument("--crosswalk", default="")
    p.add_argument("--root", default=".")
    args = p.parse_args(argv)
    root = os.path.abspath(args.root)
    problems: list[str] = []
    if args.check and args.offline:
        problems.extend(offline_problems(root))
    if args.drift:
        for cid in drifted(root, args.drift):
            print(cid)
    if args.crosswalk:
        if args.crosswalk != "usenix-2026":
            print(f"unknown crosswalk {args.crosswalk}")
            return 1
        if args.check:
            problems.extend(crosswalk_problems(root))
    if problems:
        print("\n".join(problems))
        return 1
    if args.check and args.offline:
        print("ok anchors")
    if args.crosswalk and args.check:
        print("ok crosswalk")
    return 0


if __name__ == "__main__":
    sys.exit(main())
