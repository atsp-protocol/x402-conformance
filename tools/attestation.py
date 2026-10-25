#!/usr/bin/env python3
"""Verify a tier-2 attestation (XC-98): the queue verifies a project's own full-suite run, it never runs it.

    python3 tools/attestation.py verify --file ATTESTATION.json --slug SLUG --gh-json VERIFY.json
                                        [--now ISO] [--root DIR] [--apply]
    python3 tools/attestation.py check [--root DIR]

ATTESTATION.json is what the Action writes with `attest: true` (src/x402conf/tiers.py) in the project's own CI, on a
release. VERIFY.json is the output of
`gh attestation verify ATTESTATION.json --repo <row repo> --source-digest <commit> --format json`, which checks the
Sigstore signature (GitHub artifact attestations, the job's OIDC identity) against the transparency log. On top of
it this tool refuses, and writes nothing, unless:

  - the attestation is for this row, and its vendor repository is the row's repository
  - it was made on a release tag (ref_type tag), within the row's free program window
  - the signed subject is this exact file (sha256), and the signing identity is GitHub Actions OIDC for a workflow in
    the row's repository at the attested commit, tag and run
  - every check of the pinned suite (matrix/queue/suite.json) is present with pass, fail, warn or not_applicable, and
    each not_applicable has a reason; a not_run check is an applicable check that is missing
  - nothing in it looks like an email or a secret

The suite must be the pinned release: its version, and its tag, commit or major tag (v1) as the ref. When it is
not, the attestation is still recorded and the row is marked 'rerun on current suite'. With --apply the verified
attestation is written to matrix/attestations/<slug>.json, the row becomes tier 2 (Full suite (self-hosted)) and the
matrix is regenerated; a pull request then goes up for review. check validates the committed attestations against their rows.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from x402conf import tiers as T  # noqa: E402

ROWS = "matrix/rows"
OUT = "matrix/attestations"
PIN = "matrix/queue/suite.json"
VERIFIED = "x402-conformance.verified-attestation/1"
ISSUER = "https://token.actions.githubusercontent.com"
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
SECRET = re.compile(r"(?i)\b[0-9a-f]{64}\b|-----BEGIN|\bmnemonic\b|\bseed phrase\b|\bprivate key\b|\bsk_live_")
SHA = re.compile(r"^[0-9a-f]{40}$")


def load(path: str) -> object:
    return json.load(open(path, encoding="utf-8"))


def repo_of(row: dict[str, object]) -> str:
    return str(row.get("repo") or "").rstrip("/").removeprefix("https://github.com/")


def suite_status(att: dict[str, object], pin: dict[str, object]) -> str:
    s = att.get("suite") if isinstance(att.get("suite"), dict) else {}
    tag = str(pin.get("tag") or "")
    refs = {tag, str(pin.get("commit") or ""), tag.split(".")[0]} - {""}  # the release, its commit, or its major tag
    ok = (tag and s.get("repository") == pin.get("repository")  # type: ignore[union-attr]
          and s.get("ref") in refs  # type: ignore[union-attr]
          and str(s.get("version")) == str(pin.get("version")))  # type: ignore[union-attr]
    return "current" if ok else "rerun on current suite"


def structure(att: object, row: dict[str, object], pin: dict[str, object]) -> tuple[list[str], list[str]]:
    """Problems with the document itself, and the applicable checks it is missing."""
    if not isinstance(att, dict) or att.get("schema") != T.ATTESTATION_FORMAT:
        return [f"not an x402-conformance attestation ({T.ATTESTATION_FORMAT})"], []
    bad: list[str] = []
    v = att.get("vendor") if isinstance(att.get("vendor"), dict) else {}
    if att.get("row") != row.get("slug"):
        bad.append(f"the attestation is for row {att.get('row')!r}, not {row.get('slug')!r}")
    if v.get("repository") != repo_of(row):  # type: ignore[union-attr]
        bad.append(f"the attestation is from {v.get('repository')!r}, not the row's repository {repo_of(row)!r}")  # type: ignore[union-attr]
    if v.get("ref_type") != "tag" or not v.get("ref"):  # type: ignore[union-attr]
        bad.append("the attestation must come from a release (a tag), not a branch")
    if not SHA.match(str(v.get("commit") or "")):  # type: ignore[union-attr]
        bad.append("the attestation has no 40-hex vendor commit")
    if not str(v.get("run_id") or "").isdigit():  # type: ignore[union-attr]
        bad.append("the attestation has no run id")
    text = json.dumps(att)
    if EMAIL.search(text) or SECRET.search(text.replace(str(v.get("commit") or "-"), "")):  # type: ignore[union-attr]
        bad.append("the attestation has an email address or something that looks like a secret")
    res = att.get("results") if isinstance(att.get("results"), dict) else {}
    missing: list[str] = []
    for cid in pin.get("checks") or []:  # type: ignore[union-attr]
        e = res.get(cid)  # type: ignore[union-attr]
        st = e.get("status") if isinstance(e, dict) else None
        if st not in T.STATUSES or st == "not_run":
            missing.append(str(cid))
        elif st == "not_applicable" and not T.REASON.match(str(e.get("reason") or "")):  # type: ignore[union-attr]
            bad.append(f"{cid} is not applicable without a reason")
    extra = sorted(set(res) - set(pin.get("checks") or []))  # type: ignore[arg-type]
    if extra and suite_status(att, pin) == "current":
        bad.append(f"checks the pinned suite does not have: {', '.join(extra)}")
    return bad, missing


def identity(gh: object, att_path: str, att: dict[str, object]) -> list[str]:
    """The Sigstore verification gh made, read back: this file, GitHub's OIDC issuer, the row's repository, the
    attested commit, tag and run."""
    digest = hashlib.sha256(open(att_path, "rb").read()).hexdigest()
    v = att["vendor"]  # type: ignore[index]
    repo, commit, ref, run = v["repository"], v["commit"], v["ref"], str(v["run_id"])  # type: ignore[index]
    entries = gh if isinstance(gh, list) else []
    for e in entries:
        r = e.get("verificationResult") if isinstance(e, dict) else None
        if not isinstance(r, dict):
            continue
        cert = ((r.get("signature") or {}).get("certificate") or {})
        subj = ((r.get("statement") or {}).get("subject") or [])
        if not any(isinstance(s, dict) and (s.get("digest") or {}).get("sha256") == digest for s in subj):
            continue
        checks = {
            "issuer": cert.get("issuer") == ISSUER,
            "repository": cert.get("sourceRepositoryURI") == f"https://github.com/{repo}",
            "commit": cert.get("sourceRepositoryDigest") == commit,
            "tag": cert.get("sourceRepositoryRef") == f"refs/tags/{ref}",
            "run": re.search(rf"/{re.escape(repo)}/actions/runs/{re.escape(run)}(/|$)", str(cert.get("runInvocationURI") or ""))
            is not None,
        }
        failed = [k for k, ok in checks.items() if not ok]
        if not failed:
            return []
        return [f"the signing identity does not match the attestation: {', '.join(failed)}"]
    return ["no verified signature over this file: run gh attestation verify on it (GitHub artifact attestations)"]


def verify(opt: dict[str, str], root: str) -> tuple[dict[str, object] | None, list[str]]:
    slug = opt.get("--slug", "")
    rp = os.path.join(root, ROWS, f"{slug}.json")
    if not re.match(r"^[a-z0-9][a-z0-9-]{0,62}$", slug) or not os.path.isfile(rp):
        return None, [f"no listed row {slug!r}"]
    row = load(rp)
    pin = load(os.path.join(root, PIN))
    assert isinstance(row, dict) and isinstance(pin, dict)
    if not pin.get("tag"):
        return None, ["no suite release is pinned yet (matrix/queue/suite.json): nothing can be verified"]
    now = opt.get("--now", "")[:10]
    if not row.get("program_end") or (now and now > str(row["program_end"])):
        return None, [f"the free program for {slug} has ended or was not joined: verification and listing are part of "
                      "it; the row stays listed with its last result"]
    try:
        att = load(opt["--file"])
    except (OSError, ValueError, KeyError):
        return None, ["the attestation is missing or not JSON"]
    bad, missing = structure(att, row, pin)
    if missing:
        bad.append(f"incomplete: {len(missing)} applicable check(s) not run: {', '.join(missing[:20])}"
                   + (" ..." if len(missing) > 20 else "") + "; run them, or declare them not applicable with a reason")
    if not bad:
        try:
            gh = load(opt["--gh-json"])
        except (OSError, ValueError, KeyError):
            gh = None
        bad += identity(gh, opt["--file"], att)  # type: ignore[arg-type]
    if bad:
        return None, bad
    assert isinstance(att, dict)
    v = att["vendor"]
    doc: dict[str, object] = {
        "schema": VERIFIED, "slug": slug, "verified_at": now or None, "suite_status": suite_status(att, pin),
        "pinned": {k: pin.get(k) for k in ("tag", "commit", "version")},
        "identity": {"repository": v["repository"], "ref": v["ref"], "commit": v["commit"],
                     "workflow_ref": v.get("workflow_ref"),
                     "run": f"https://github.com/{v['repository']}/actions/runs/{v['run_id']}"},
        "summary": T.denominator(att["results"], T.TIER2),  # type: ignore[arg-type]
        "attestation": att,
    }
    return doc, []


def apply(doc: dict[str, object], root: str) -> int:
    slug = str(doc["slug"])
    os.makedirs(os.path.join(root, OUT), exist_ok=True)
    with open(os.path.join(root, OUT, f"{slug}.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, sort_keys=True)
        f.write("\n")
    rp = os.path.join(root, ROWS, f"{slug}.json")
    row = load(rp)
    assert isinstance(row, dict)
    row["attestation"] = f"{OUT}/{slug}.json"
    row["tier"] = T.TIER2
    row["version"] = str(doc["identity"]["ref"]).lstrip("v")[:40]  # type: ignore[index]
    with open(rp, "w", encoding="utf-8") as f:
        json.dump(row, f, indent=1, ensure_ascii=False)
        f.write("\n")
    return subprocess.run([sys.executable, os.path.join(ROOT, "tools", "matrix_rows.py"), "--write", "--root", root]).returncode


def check(root: str) -> list[str]:
    bad: list[str] = []
    pin = load(os.path.join(root, PIN))
    assert isinstance(pin, dict)
    d = os.path.join(root, OUT)
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not name.endswith(".json"):
            continue
        doc = load(os.path.join(d, name))
        rp = os.path.join(root, ROWS, name)
        if not isinstance(doc, dict) or doc.get("schema") != VERIFIED or not os.path.isfile(rp):
            bad.append(f"{OUT}/{name}: not a verified attestation of a listed row")
            continue
        row = load(rp)
        assert isinstance(row, dict)
        att = doc.get("attestation") if isinstance(doc.get("attestation"), dict) else {}
        probs, missing = structure(att, row, {**pin, "checks": list(att.get("results") or {})})
        bad += [f"{OUT}/{name}: {p}" for p in probs + ([f"{len(missing)} check(s) not run"] if missing else [])]
        if row.get("attestation") != f"{OUT}/{name}" or row.get("tier") != T.TIER2:
            bad.append(f"{OUT}/{name}: the row does not link it as its tier-2 attestation")
    return bad


def main(argv: list[str]) -> int:
    keys = ("--file", "--slug", "--gh-json", "--now", "--root")
    opt = {k: argv[argv.index(k) + 1] for k in keys if k in argv and argv.index(k) + 1 < len(argv)}
    root = os.path.abspath(opt.get("--root", ROOT))
    if argv[:1] == ["verify"]:
        doc, bad = verify(opt, root)
        for b in bad:
            print(f"attestation: {b}")
        if doc is None:
            print("attestation: refused, nothing written")
            return 1
        s = doc["summary"]
        print(f"attestation: verified for {doc['slug']}: {s['passed']}/{s['applicable']} applicable checks passed, "  # type: ignore[index]
              f"{s['not_applicable']} not applicable; suite {doc['suite_status']}")  # type: ignore[index]
        return apply(doc, root) if "--apply" in argv else 0
    if argv[:1] == ["check"]:
        bad = check(root)
        for b in bad:
            print(f"attestation: {b}")
        return 1 if bad else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
