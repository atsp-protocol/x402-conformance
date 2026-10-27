"""Cross-SDK parity report (XC-56).

x402conf parity sends one vector set (docs/parity/vectors.json) to a harness per SDK and writes a run file: per
vector, per SDK, the observed {status, content_type, isValid, invalidReason, threw}. This tool checks that file and
the vector set, compares each SDK's outcome with the expected outcome and with the other SDKs, and writes the
evidence.

  python3 tools/parity_report.py --validate RUN          exit 1 unless RUN is a complete, offline run at the pin
  python3 tools/parity_report.py --coverage VECTORS --require TAG,...
                                                         exit 1 unless every TAG is on at least one vector
  python3 tools/parity_report.py --anchors VECTORS       exit 1 unless every vector names a spec-anchored check id
                                                         from docs/check-ids.json or is labelled security-profile
  python3 tools/parity_report.py --evidence DIR RUN      write DIR/<pin>/run.json (with divergences) and SHA256SUMS
  python3 tools/parity_report.py --check DIR             exit 1 unless every DIR/<pin>/SHA256SUMS verifies and its
                                                         run.json validates
  python3 tools/parity_report.py --divergences RUN       print the divergences, one per line

A divergence is either a field where an SDK's outcome differs from the vector's expected outcome, or a vector where
the SDKs disagree with each other. Each one carries the vector id and its spec anchor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VECTORS = "docs/parity/vectors.json"
PIN = "docs/parity/pin"
PINS = "docs/parity/pins.json"
REGISTRY = "docs/check-ids.json"
RUN_SCHEMA = "x402conf.parity-run/1"
VECTOR_SCHEMA = "x402conf.parity-vectors/1"
SHA = re.compile(r"^[0-9a-f]{40}$")
TARGETS = ("verify", "paid-route")
FIELDS = ("status", "content_type", "isValid", "invalidReason", "threw")


def load(path: str) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def read_pin(root: str = ROOT) -> str:
    with open(os.path.join(root, PIN), encoding="utf-8") as f:
        return f.read().strip()


def vector_problems(doc: Any) -> list[str]:
    """Shape of the vector set itself."""
    if not isinstance(doc, dict) or doc.get("schema") != VECTOR_SCHEMA:
        return [f"not a {VECTOR_SCHEMA} document"]
    vs = doc.get("vectors")
    if not isinstance(vs, list) or not vs:
        return ["no vectors"]
    out, seen = [], set()
    for i, v in enumerate(vs):
        vid = v.get("id") if isinstance(v, dict) else None
        if not isinstance(vid, str) or not vid:
            out.append(f"vector {i} has no id")
            continue
        if vid in seen:
            out.append(f"{vid}: duplicate id")
        seen.add(vid)
        if v.get("target") not in TARGETS:
            out.append(f"{vid}: target must be one of {', '.join(TARGETS)}")
        if not isinstance(v.get("tags"), list) or not v["tags"]:
            out.append(f"{vid}: no tags")
        if not isinstance(v.get("input"), dict):
            out.append(f"{vid}: no input")
        exp = v.get("expect")
        if not isinstance(exp, dict) or not exp or set(exp) - set(FIELDS):
            out.append(f"{vid}: expect must name some of {', '.join(FIELDS)} and nothing else")
    return out


def coverage_problems(doc: Any, required: list[str]) -> list[str]:
    tags = {t for v in doc.get("vectors", []) if isinstance(v, dict) for t in v.get("tags", [])}
    return [f"no vector is tagged {t}" for t in required if t not in tags]


def anchor_problems(doc: Any, checks: list[dict[str, Any]]) -> list[str]:
    anchored = {c["id"] for c in checks if isinstance(c.get("anchor"), dict)}
    known = {c["id"] for c in checks}
    out = []
    for v in doc.get("vectors", []):
        vid, a, prof = v.get("id"), v.get("anchor"), v.get("profile")
        if prof == "security-profile" and a is None:
            continue
        if prof == "security-profile":
            if a not in known:
                out.append(f"{vid}: anchor {a!r} is not a check id in {REGISTRY}")
            continue
        if a not in anchored:
            out.append(f"{vid}: anchor {a!r} is not a spec-anchored check id in {REGISTRY}, "
                       "and the vector is not labelled security-profile")
    return out


def _matches(field: str, want: Any, got: Any) -> bool:
    if field in ("status", "invalidReason") and isinstance(want, list):
        return got in want
    if field == "content_type" and isinstance(want, str):
        return isinstance(got, str) and got.split(";")[0].strip().lower() == want.lower()
    return bool(got == want)


def divergences(run: dict[str, Any], doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Each SDK against the expected outcome, then the SDKs against each other, per vector."""
    by_id = {v["id"]: v for v in doc["vectors"]}
    rows: dict[str, list[dict[str, Any]]] = {}
    for r in run.get("results", []):
        rows.setdefault(r["vector"], []).append(r)
    out = []
    for vid, v in by_id.items():
        anchor = v.get("anchor") or v.get("profile")
        got = sorted(rows.get(vid, []), key=lambda r: r["sdk"])
        for r in got:
            for field, want in v["expect"].items():
                if not _matches(field, want, r.get(field)):
                    out.append({"vector": vid, "anchor": anchor, "kind": "expected", "sdk": r["sdk"], "field": field,
                                "expected": want, "observed": r.get(field)})
        for field in v["expect"]:
            seen = {r["sdk"]: r.get(field) for r in got}
            norm = {json.dumps(x, sort_keys=True) for x in seen.values()}
            if len(norm) > 1:
                out.append({"vector": vid, "anchor": anchor, "kind": "cross-sdk", "field": field, "observed": seen})
    return out


def run_problems(run: Any, doc: dict[str, Any], pin: str, pins: dict[str, Any] | None = None) -> list[str]:
    """A complete, offline run at the pin: every vector answered once by every SDK, nothing sent off the box."""
    if not isinstance(run, dict) or run.get("schema") != RUN_SCHEMA:
        return [f"not a {RUN_SCHEMA} document"]
    out = []
    if run.get("pin") != pin:
        out.append(f"run pin {run.get('pin')!r} is not docs/parity/pin {pin!r}")
    if run.get("offline") is not True:
        out.append("the run was not offline")
    sdks = run.get("sdks")
    if not isinstance(sdks, dict) or not sdks:
        return out + ["the run names no SDK"]
    net = run.get("network") or {}
    if net.get("outbound_connections") != 0:
        out.append(f"outbound connections recorded: {net.get('outbound_connections')!r}")
    if net.get("signer_writes") != 0:
        out.append(f"the stub signer was asked to write: {net.get('signer_writes')!r}")
    for sdk, meta in sdks.items():
        want = (pins or {}).get("sdks", {}).get(sdk, {}).get("version")
        if want is not None and meta.get("version") != want:
            out.append(f"{sdk}: library version {meta.get('version')!r} is not the pinned {want!r}")
    ids = [v["id"] for v in doc["vectors"]]
    seen: dict[tuple[str, str], int] = {}
    for r in run.get("results", []):
        if not isinstance(r, dict):
            out.append("a result is not an object")
            continue
        k = (str(r.get("vector")), str(r.get("sdk")))
        seen[k] = seen.get(k, 0) + 1
        if not isinstance(r.get("threw"), bool):
            out.append(f"{k[0]} {k[1]}: threw is not a boolean")
        if r.get("status") is not None and not isinstance(r.get("status"), int):
            out.append(f"{k[0]} {k[1]}: status is not an integer")
        if r.get("isValid") is not None and not isinstance(r.get("isValid"), bool):
            out.append(f"{k[0]} {k[1]}: isValid is not a boolean")
    for sdk in sdks:
        for vid in ids:
            n = seen.get((vid, sdk), 0)
            if n != 1:
                out.append(f"{vid} {sdk}: {n} results, expected exactly one")
    extra = {k for k in seen if k[0] not in ids or k[1] not in sdks}
    out += [f"{k[0]} {k[1]}: not a vector or SDK of this run" for k in sorted(extra, key=str)]
    return out


def write_evidence(run: dict[str, Any], doc: dict[str, Any], base: str) -> str:
    d = os.path.join(base, run["pin"])
    os.makedirs(d, exist_ok=True)
    body = dict(run, divergences=divergences(run, doc))
    text = json.dumps(body, indent=1, sort_keys=True) + "\n"
    with open(os.path.join(d, "run.json"), "w", encoding="utf-8") as f:
        f.write(text)
    with open(os.path.join(d, "SHA256SUMS"), "w", encoding="utf-8") as f:
        f.write(hashlib.sha256(text.encode()).hexdigest() + "  run.json\n")
    return d


def evidence_problems(base: str, doc: dict[str, Any], pins: dict[str, Any] | None = None) -> list[str]:
    if not os.path.isdir(base):
        return [f"{base}: no evidence directory"]
    out, n = [], 0
    for name in sorted(os.listdir(base)):
        d = os.path.join(base, name)
        if not os.path.isdir(d):
            continue
        n += 1
        if not SHA.match(name):
            out.append(f"{name}: not a 40-hex commit")
        sums = os.path.join(d, "SHA256SUMS")
        if not os.path.isfile(sums):
            out.append(f"{name}: no SHA256SUMS")
            continue
        for line in read_bytes(sums).decode("utf-8").splitlines():
            h, _, f = line.partition("  ")
            p = os.path.join(d, f)
            if not os.path.isfile(p):
                out.append(f"{name}/{f}: listed but missing")
            elif hashlib.sha256(read_bytes(p)).hexdigest() != h:
                out.append(f"{name}/{f}: hash does not match SHA256SUMS")
        try:
            run = load(os.path.join(d, "run.json"))
        except (OSError, ValueError) as e:
            out.append(f"{name}/run.json: {e}")
            continue
        out += [f"{name}: {p}" for p in run_problems(run, doc, name, pins)]
        if run.get("divergences") != divergences(run, doc):
            out.append(f"{name}: the recorded divergences are not the ones this vector set gives")
    if not n:
        out.append(f"{base}: no evidence for any commit")
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Check and report a cross-SDK parity run.")
    p.add_argument("--validate", metavar="RUN")
    p.add_argument("--coverage", metavar="VECTORS")
    p.add_argument("--require", default="")
    p.add_argument("--anchors", metavar="VECTORS")
    p.add_argument("--evidence", metavar="DIR")
    p.add_argument("--check", metavar="DIR")
    p.add_argument("--divergences", metavar="RUN")
    p.add_argument("--root", default=ROOT)
    p.add_argument("run", nargs="?")
    a = p.parse_args(argv)
    root = a.root
    pins = load(os.path.join(root, PINS)) if os.path.isfile(os.path.join(root, PINS)) else None

    def vectors(path: str | None = None) -> dict[str, Any]:
        doc: dict[str, Any] = load(path or os.path.join(root, VECTORS))
        return doc

    problems: list[str] = []
    if a.coverage:
        doc = vectors(a.coverage)
        problems += vector_problems(doc) + coverage_problems(doc, [t for t in a.require.split(",") if t])
    elif a.anchors:
        doc = vectors(a.anchors)
        problems += vector_problems(doc) + anchor_problems(doc, load(os.path.join(root, REGISTRY))["checks"])
    elif a.validate:
        doc = vectors()
        problems += vector_problems(doc) + run_problems(load(a.validate), doc, read_pin(root), pins)
    elif a.check:
        doc = vectors()
        problems += vector_problems(doc) + evidence_problems(a.check, doc, pins)
    elif a.evidence and a.run:
        doc, run = vectors(), load(a.run)
        problems += vector_problems(doc) + run_problems(run, doc, read_pin(root), pins)
        if not problems:
            print(f"wrote {write_evidence(run, doc, a.evidence)}")
    elif a.divergences:
        for d in divergences(load(a.divergences), vectors()):
            print(json.dumps(d, sort_keys=True))
        return 0
    else:
        p.print_usage(sys.stderr)
        return 2
    for x in problems:
        print(x, file=sys.stderr)
    print(f"{len(problems)} problem(s)" if problems else "ok")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
