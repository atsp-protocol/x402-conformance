"""Command line.

    x402conf live <facilitator-base-url> ... [--evidence DIR] [--fail-on-error]   S0-S4, GET /supported only
    x402conf resource <paid-url> ... [--fail-on-error] [--share]                  P1-P7, one unpaid GET per URL
    x402conf offline                                                F1-F12 and S5 against the reference and faulty doubles
    x402conf devnet [--faults] [--evidence DIR] ...                  F1-F6 over real /verify and /settle on Solana devnet
    x402conf report [--dir DIR] [--sarif FILE] [--junit FILE] [--fail-on-error]   SARIF 2.1.0 and JUnit XML

Exit codes: 0 done (and, with --fail-on-error, no error-severity check failed); 1 an error-severity check failed
(offline always; live, resource and report only with --fail-on-error); 2 usage or configuration error, or report found
no results JSON."""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import ipaddress
import json
import os
import platform
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from xml.sax.saxutils import quoteattr

from . import __version__
from . import harness as H
from . import mock as M
from . import spec as S

DOCS = "https://github.com/atsp-protocol/x402-conformance/blob/main/docs/"
REPO = "https://github.com/atsp-protocol/x402-conformance"
LINKS = {
    "repo": REPO,
    "fixes": f"{REPO}/blob/main/docs/FIXES.md",
    "corpus": f"{REPO}/tree/main/corpus",
    "contribute": f"{REPO}/issues/new?template=corpus-case.yml",
    "using": f"{REPO}/blob/main/docs/USING.md",
    "badge": "[![Tested with x402-conformance](https://img.shields.io/badge/tested%20with-x402--conformance-2ea44f)]"
             f"({REPO})",
}


# ---------------- the shared report and the opt-in corpus case ----------------
# The same report (x402-conformance.report/1) and case (x402-conformance.case/1) as ts/src/report.ts and
# ts/src/corpus.ts. corpus/fixtures holds one report and the case both languages must derive from it.
def _labels(check: str) -> dict[str, str]:
    """Evidence v2 labels for the shared report, the same as normalise() in ts/src/report.ts."""
    e = S.CATALOG.get(check.split(" ")[0])
    return {"profile": str(e["profile"]), "basis": str(e["basis"])} if e else {}


def make_report(kind: str, target: str, checks: list[dict[str, Any]], via: str | None = None,
                error: str | None = None) -> dict[str, Any]:
    rs = [{"check": c["check"], "pass": bool(c["pass"]), "status": c.get("status") or ("pass" if c["pass"] else "fail"),
           "severity": c.get("severity", "error"), "detail": c.get("detail"), **_labels(c["check"])} for c in checks]
    failed = [r for r in rs if not r["pass"] and r["status"] != "unsupported"]
    out: dict[str, Any] = {
        "schema": "x402-conformance.report/1", "tool": "x402-conformance", "version": __version__,
        "via": via or H.via(), "kind": kind, "run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "target": target, "results": rs,
        "summary": {"checks": len(rs), "failed": len(failed), "failed_ids": [r["check"].split(" ")[0] for r in failed],
                    "unsupported": any(r["status"] == "unsupported" for r in rs)},
        "links": LINKS}
    if error:
        out["error"] = error
    return out


_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s\"'<>]+", re.I)
_EVM = re.compile(r"\b0x[0-9a-fA-F]{16,}\b")
_B58 = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,88}\b")
_HOST = re.compile(r"\b(?:[a-z0-9-]+\.)+(?:com|net|org|io|xyz|ai|app|dev|co|cloud|sh|gg|so|me|tech)\b", re.I)
_IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b")
_KEEP = frozenset({"EtWTRABZaYq6iMfeYKouRu166VU2xqa1", "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
                   "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU", "0x036CbD53842c5426634e7929541eC2318f3dCF7e"})
_SENSITIVE = frozenset({"payTo", "pay_to", "resource", "url", "payer", "from", "to", "transaction", "signature", "nonce",
                        "facilitator", "facilitator_double", "authorization", "cookie", "host"})


def _scrub_str(s: str) -> str:
    s = _URL.sub("<url>", s)
    s = _EVM.sub(lambda m: m.group(0) if m.group(0) in _KEEP else "<hex>", s)
    s = _B58.sub(lambda m: m.group(0) if m.group(0) in _KEEP else "<base58>", s)
    return _HOST.sub("<host>", _IP.sub("<ip>", s))


def scrub(v: Any, depth: int = 0) -> Any:
    if depth > 8:
        return "<truncated>"
    if isinstance(v, str):
        return _scrub_str(v)[:300]
    if isinstance(v, list):
        return [scrub(x, depth + 1) for x in v[:10]]
    if isinstance(v, dict):
        return {k: "<redacted>" if k in _SENSITIVE else scrub(x, depth + 1) for k, x in v.items()}
    return v


def _loopback(target: str) -> bool:
    host = urllib.parse.urlsplit(target).hostname or ""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host) in (ipaddress.ip_address("127.0.0.1"), ipaddress.ip_address("::1"))
    except ValueError:
        return False


def anonymise(report: dict[str, Any], stack: dict[str, str] | None = None) -> dict[str, Any]:
    """An anonymised corpus case: no URLs, hosts, IPs, addresses or transaction data. Sends nothing."""
    clean = {k: _scrub_str(v)[:80] for k, v in (stack or {}).items() if isinstance(v, str) and v}
    return {"schema": "x402-conformance.case/1", "tool_version": report.get("version") or __version__,
            "via": report["via"], "kind": report["kind"], "target": "loopback" if _loopback(report["target"]) else "redacted",
            "stack": clean, "failed_ids": report["summary"]["failed_ids"],
            "results": [{"id": r["check"].split(" ")[0], "check": r["check"], "status": r["status"],
                         "severity": r["severity"], "detail": None if r["pass"] else scrub(r["detail"])}
                        for r in report["results"]]}


def share_url(case: dict[str, Any]) -> str | None:
    """A link to the pre-filled corpus case issue form, or None when nothing failed. A person submits it, or not."""
    if not case["failed_ids"]:
        return None
    text = json.dumps(case, indent=1)
    if len(text) > 5000:
        text = text[:5000] + "\n... (cut; attach the full case file)"
    fw = case["stack"].get("framework")
    q = {"template": "corpus-case.yml",
         "title": f"[corpus] {', '.join(case['failed_ids'])} via {case['via']}" + (f" on {fw}" if fw else ""),
         "labels": "corpus-case", "via": case["via"], "checks": ", ".join(case["failed_ids"]),
         "stack": "\n".join(f"{k}: {v}" for k, v in case["stack"].items()), "case": text}
    return f"{REPO}/issues/new?" + urllib.parse.urlencode(q)


def funnel_footer(report: dict[str, Any]) -> str:
    lines = [f"x402-conformance {report['version']} via {report['via']}. Corpus of known x402 failures: {LINKS['corpus']}"]
    if report["summary"]["failed"]:
        lines.append("Share this failure as an anonymised corpus case (opt-in, reviewed by you first): re-run with "
                     f"--share, or {LINKS['contribute']}")
    else:
        lines.append(f"All checks passed. Add the badge to your README: {LINKS['badge']}")
    lines.append(f"Using it from other stacks: {LINKS['using']}")
    return "\n".join(lines)


def write_cases(reports: list[dict[str, Any]], directory: str = ".") -> list[tuple[str, str | None]]:
    """--share: one anonymised case file per report, and the link to submit each failing one. Nothing is sent."""
    out = []
    for i, rep in enumerate(reports):
        case = anonymise(rep)
        path = os.path.join(directory, f"x402-conformance-case-{rep['kind']}-{i + 1}.json")
        with open(path, "w") as f:
            f.write(json.dumps(case, indent=1) + "\n")
        out.append((path, share_url(case)))
    return out


def collect(d: str) -> list[dict[str, Any]]:
    """One row per check from live.json, resource-server.json and offline.json in d, the files the Action writes.

    Offline rows cover the reference double only, plus one row saying whether every fault-injected double was caught:
    a fault-injected double failing its target check is the expected result, not a finding."""
    rows: list[dict[str, Any]] = []

    def load(name: str) -> Any:
        p = os.path.join(d, name)
        if not os.path.exists(p):
            return None
        with open(p) as f:
            return json.load(f)

    def row(target: str, check: str, ok: bool, severity: str, detail: Any, source: str) -> None:
        rows.append({"id": check.split()[0], "target": target, "check": check, "pass": bool(ok),
                     "severity": severity, "detail": detail, "source": source})

    for name in ("live.json", "resource-402.json"):
        for r in (load(name) or {}).get("results", []):
            checks = r.get("checks", [])
            if r.get("error") and not checks:  # results written before 1.3.0 carried the error without an S0 check
                row(r["target"], H.S0, False, "error", r["error"], name)
            for c in checks:
                row(r["target"], c["check"], c["pass"], c.get("severity", "error"), c.get("detail"), name)
    rsv = load("resource-server.json")
    if rsv is not None:
        if rsv.get("error"):
            row(rsv.get("resource") or "resource server", "RX the probe ran to completion", False, "error",
                {"error": rsv["error"]}, "resource-server.json")
        for c in rsv.get("results", []):
            detail = c.get("detail")
            if c.get("status") == "unsupported":
                detail = {"status": "unsupported", "detail": detail}
            row(rsv.get("resource") or "resource server (binding)", c["check"], c["pass"], "error", detail,
                "resource-server.json")
    off = load("offline.json")
    if off is not None:
        res = off["results"]
        for c in res["reference"]:
            row("reference double", c["check"], c["pass"], c.get("severity", "error"), c.get("detail"), "offline.json")
        missed = [k for k, v in res.items() if k != "reference" and all(c["pass"] for c in v)]
        row("fault-injected doubles", "FX every fault-injected double is caught by at least one check", not missed,
            "error", {"uncaught": missed}, "offline.json")
    return rows


def anchor(check_id: str) -> str:
    return DOCS + "FIXES.md#" + check_id.lower()


def sarif(rows: list[dict[str, Any]], results_dir: str) -> dict[str, Any]:
    """SARIF 2.1.0 for GitHub code scanning: one rule per check id, one result per failed check.

    A result points at the results file it came from, because a failed x402 check is a property of a running service,
    not of a line of source code."""
    rules: dict[str, dict[str, Any]] = {}
    for r in rows:
        rules.setdefault(r["id"], {
            "id": r["id"], "name": "x402" + r["id"],
            "shortDescription": {"text": r["check"][len(r["id"]):].strip() or r["id"]},
            "helpUri": anchor(r["id"]),
            "help": {"text": f"What failed and how to fix it: {anchor(r['id'])}"},
            "properties": {"tags": ["x402", "payments", "security"]},
        })
    ids = sorted(rules)
    results = []
    for r in rows:
        if r["pass"]:
            continue
        key = hashlib.sha256(f"{r['target']}|{r['id']}".encode()).hexdigest()
        detail = json.dumps(r["detail"], sort_keys=True)[:500]
        results.append({
            "ruleId": r["id"], "ruleIndex": ids.index(r["id"]),
            "level": {"error": "error", "warning": "warning"}.get(r["severity"], "note"),
            "message": {"text": f"{r['target']}: {r['check']} failed. Detail: {detail}. Fix: {anchor(r['id'])}"},
            "locations": [{"physicalLocation": {"artifactLocation": {
                "uri": os.path.join(results_dir, r["source"]).replace(os.sep, "/")}}}],
            "partialFingerprints": {"x402ConformanceCheck/v1": key},
        })
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json", "version": "2.1.0",
        "runs": [{"tool": {"driver": {"name": "x402-conformance", "version": __version__,
                                      "informationUri": "https://github.com/atsp-protocol/x402-conformance",
                                      "rules": [rules[i] for i in ids]}},
                  "results": results}],
    }


def junit(rows: list[dict[str, Any]]) -> str:
    """JUnit XML: one test suite per target, one test case per check. Warning and info failures are reported as skipped."""
    suites: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        suites.setdefault(r["target"], []).append(r)
    fails = sum(1 for r in rows if not r["pass"] and r["severity"] == "error")
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<testsuites name="x402-conformance" tests="{len(rows)}" failures="{fails}">']
    for target, rs in suites.items():
        nf = sum(1 for r in rs if not r["pass"] and r["severity"] == "error")
        ns = sum(1 for r in rs if not r["pass"] and r["severity"] != "error")
        out.append(f'  <testsuite name={quoteattr(target)} tests="{len(rs)}" failures="{nf}" skipped="{ns}">')
        for r in rs:
            case = f'    <testcase classname={quoteattr("x402." + r["id"])} name={quoteattr(r["check"])}'
            if r["pass"]:
                out.append(case + "/>")
                continue
            msg = quoteattr(f"{r['id']} failed; how to fix it: {anchor(r['id'])}")
            body = json.dumps(r["detail"], sort_keys=True)[:2000]
            body = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            tag = "failure" if r["severity"] == "error" else "skipped"
            out += [case + ">", f"      <{tag} message={msg}>{body}</{tag}>", "    </testcase>"]
        out.append("  </testsuite>")
    out.append("</testsuites>")
    return "\n".join(out) + "\n"


def report(a: argparse.Namespace) -> int:
    rows = collect(a.dir)
    if not rows:
        print(f"no results JSON found in {a.dir}", file=sys.stderr)
        return 2
    if a.sarif:
        with open(a.sarif, "w") as f:
            json.dump(sarif(rows, a.dir), f, indent=1)
            f.write("\n")
    if a.junit:
        with open(a.junit, "w") as f:
            f.write(junit(rows))
    bad = [r for r in rows if not r["pass"] and r["severity"] == "error"]
    if a.badge:
        with open(a.badge, "w") as f:
            json.dump(badge(rows), f, indent=1)
            f.write("\n")
    print(json.dumps({"checks": len(rows), "failed": len(bad), "failed_ids": sorted({r["id"] for r in bad})}))
    return 1 if bad and a.fail_on_error else 0


def failed_errors(runs: list[dict[str, Any]]) -> bool:
    return any(not c["pass"] and c.get("severity", "error") == "error" for r in runs for c in r.get("checks", []))


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="x402conf", description="Experimental conformance and safety checks for x402.",
                                 epilog="Exit codes: 0 done; 1 an error-severity check failed (offline always; live, "
                                        "resource and report with --fail-on-error); 2 usage or configuration error. "
                                        "Docs: https://github.com/atsp-protocol/x402-conformance")
    ap.add_argument("--version", action="version", version=f"x402conf {__version__}")
    sub = ap.add_subparsers(dest="mode", required=True, metavar="{demo,live,resource,offline,report,pr-comment,devnet}")
    dm = sub.add_parser("demo", help="run S0-S4, P1-P7 and F1-F12 and S5 against a bundled mock on loopback, no wallet",
                        description="A first run with nothing to set up: a bundled mock facilitator and paid route on "
                                    "127.0.0.1, then the offline self-test. No wallet, no chain, well under a minute. "
                                    "--fault shows a failing run and its fix links.")
    dm.add_argument("--fault", choices=DEMO_FAULTS, help="serve a faulty mock to see what a failure looks like")
    dm.add_argument("--dir", help="also write the results JSON here (then x402conf report --dir works on it)")
    pc = sub.add_parser("pr-comment", help="create or update one sticky pull request comment from a markdown file",
                        description="Posts FILE as a comment on the pull request in GITHUB_EVENT_PATH, or updates the "
                                    "comment this tool posted before. Needs GITHUB_TOKEN with pull-requests: write. "
                                    "Outside a pull request, or when the token can't comment (a fork), it warns and "
                                    "exits 0.")
    pc.add_argument("file")
    fe = "exit 1 when an error-severity check fails (default: exit 0 and read the pass fields)"
    lv = sub.add_parser("live", help="S0-S4 over a facilitator's GET /supported; never signs, pays or POSTs",
                        description="S0-S4 over GET /supported. Optional credentials come from the environment only: "
                                    f"{H.AUTH_ENV} is sent as the Authorization header to the host named in "
                                    f"{H.AUTH_HOST_ENV} and to no other host, and is never printed.")
    lv.add_argument("targets", nargs="+", metavar="FACILITATOR_URL")
    lv.add_argument("--evidence", help="directory for raw bodies, run.json and SHA256SUMS")
    lv.add_argument("--fail-on-error", action="store_true", help=fe)
    rs = sub.add_parser("resource", help="P1-P7 over one unpaid GET of a paid URL: the 402 answer and its PaymentRequired",
                        description="P1-P7: one unpaid GET per URL, any network, V1 or V2. Never pays or POSTs.")
    rs.add_argument("targets", nargs="+", metavar="PAID_URL")
    rs.add_argument("--fail-on-error", action="store_true", help=fe)
    rs.add_argument("--share", action="store_true",
                    help="opt-in: write an anonymised corpus case per URL and print the link to submit a failing one; "
                         "nothing is sent")
    sub.add_parser("offline", help="F1-F12 and S5 against the built-in reference and fault-injected facilitator doubles",
                   description="Self-test of the suite: F1-F12 and S5 against in-process doubles. Exits 1 unless the reference "
                               "passes and every fault-injected double is caught. It does not test your code.")
    rp = sub.add_parser("report", help="convert results JSON in a directory to SARIF 2.1.0 and JUnit XML",
                        description="Convert live.json, resource-402.json, resource-server.json and offline.json to "
                                    "SARIF or JUnit")
    rp.add_argument("--dir", default="x402-conformance", help="directory holding the results JSON files")
    rp.add_argument("--sarif", help="write SARIF 2.1.0 here (for GitHub code scanning)")
    rp.add_argument("--junit", help="write JUnit XML here (for test-report viewers)")
    rp.add_argument("--badge", help="write a shields.io endpoint badge (JSON) here")
    rp.add_argument("--fail-on-error", action="store_true", help=fe)
    sub.add_parser("devnet", help="F1-F6 over real /verify and /settle on Solana devnet (self-hosted reference)",
                   add_help=False)
    return ap


COMMENT_MARKER = "<!-- x402-conformance:sticky -->"


def badge(rows: list[dict[str, Any]], result: str | None = None) -> dict[str, Any]:
    """A shields.io endpoint badge: https://img.shields.io/endpoint?url=<where badge.json is served>."""
    failed = sum(1 for r in rows if not r["pass"] and r["severity"] == "error")
    res = result or ("pass" if rows and not failed else "fail")
    if res == "pass":
        msg, color = f"pass {len(rows)}/{len(rows)}", "brightgreen"
    elif res == "unsupported":
        msg, color = "unsupported", "lightgrey"
    else:
        msg, color = (f"{failed} failing" if failed else "fail"), "red"
    return {"schemaVersion": 1, "label": "x402 conformance", "message": msg, "color": color}


def _gh(method: str, url: str, token: str, body: Any = None) -> Any:
    req = urllib.request.Request(url, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                          "Content-Type": "application/json", "User-Agent": "x402-conformance"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read() or b"null")


def pr_comment(path: str, env: dict[str, str] | None = None) -> int:
    """Create or update the one comment carrying COMMENT_MARKER. Never fails the job over a comment."""
    e = dict(os.environ if env is None else env)
    try:
        with open(e.get("GITHUB_EVENT_PATH", "")) as f:
            number = (json.load(f).get("pull_request") or {}).get("number")
    except (OSError, ValueError):
        number = None
    token, repo = e.get("GITHUB_TOKEN", ""), e.get("GITHUB_REPOSITORY", "")
    if not number or not token or not repo:
        print("::warning title=x402 Conformance::pr-comment: not a pull request run, or no token; no comment posted")
        return 0
    with open(path) as f:
        body = f.read()
    if COMMENT_MARKER not in body:
        body = COMMENT_MARKER + "\n" + body
    api = e.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    try:
        mine = None
        for page in range(1, 11):
            batch = _gh("GET", f"{api}/repos/{repo}/issues/{number}/comments?per_page=100&page={page}", token)
            mine = next((c for c in batch if COMMENT_MARKER in (c.get("body") or "")), None)
            if mine or len(batch) < 100:
                break
        if mine:
            _gh("PATCH", f"{api}/repos/{repo}/issues/comments/{mine['id']}", token, {"body": body})
        else:
            _gh("POST", f"{api}/repos/{repo}/issues/{number}/comments", token, {"body": body})
    except (urllib.error.URLError, OSError, ValueError) as err:
        print(f"::warning title=x402 Conformance::pr-comment: could not post the comment ({err}); a fork's token "
              "is read-only, and the caller needs permissions: pull-requests: write")
        return 0
    print(f"pr-comment: {'updated' if mine else 'posted'} on {repo}#{number}")
    return 0


DEMO_FAULTS = ["no_fee_payer", "no_402"]
DEMO_FEE_PAYER = "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin"


def _demo_server(fault: str | None) -> tuple[http.server.ThreadingHTTPServer, str]:
    """A bundled mock facilitator (GET /supported) and paid route (GET /paid) on 127.0.0.1, read-only like the
    checks that read them. Nothing here signs, pays or reaches the network."""
    fee = None if fault == "no_fee_payer" else DEMO_FEE_PAYER
    supported = {"kinds": [{"x402Version": 2, "scheme": "exact", "network": S.SOLANA_DEVNET,
                            "extra": {"feePayer": fee} if fee else {}}],
                 "extensions": [], "signers": {"solana:*": [DEMO_FEE_PAYER]}}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_: Any) -> None:
            pass

        def do_GET(self) -> None:  # noqa: N802
            host = self.headers.get("Host", "127.0.0.1")
            if self.path == "/supported":
                return self._send(200, {}, supported)
            if self.path == "/paid" and fault == "no_402":
                return self._send(200, {}, {"content": "served without payment"})
            if self.path == "/paid":
                pr = {"x402Version": 2, "error": "payment required",
                      "resource": {"url": f"http://{host}/paid", "description": "x402-conformance demo",
                                   "mimeType": "application/json"},
                      "accepts": [{"scheme": "exact", "network": S.SOLANA_DEVNET, "amount": "10000",
                                   "asset": "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU", "payTo": DEMO_FEE_PAYER,
                                   "maxTimeoutSeconds": 60, "extra": {"feePayer": fee} if fee else {}}]}
                hdr = base64.b64encode(json.dumps(pr).encode()).decode()
                return self._send(402, {"PAYMENT-REQUIRED": hdr}, {})
            return self._send(404, {}, {"error": "not found"})

        def _send(self, status: int, headers: dict[str, str], body: Any) -> None:
            raw = json.dumps(body).encode()
            self.send_response(status)
            for k, v in {"Content-Type": "application/json", "Content-Length": str(len(raw)), **headers}.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(raw)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def demo(a: argparse.Namespace) -> int:
    t0 = time.monotonic()
    srv, base = _demo_server(a.fault)
    try:
        live = H.run_live(base)
        live.pop("raw", None)
        res402 = H.run_resource(base + "/paid")
    finally:
        srv.shutdown()
        srv.server_close()
    off = {k: H.check_safety(f(), M.vectors()) for k, f in M.FAULTS.items()}
    off.update({k: H.check_safety(M.Reference(), M.vectors(), guard=g) for k, g in H.GUARD_FAULTS.items()})
    secs = time.monotonic() - t0
    rows = [(c, "mock facilitator") for c in live.get("checks", [])] + \
        [(c, "mock paid route") for c in res402.get("checks", [])] + \
        [(c, "suite self-test") for c in off["reference"]]
    print(f"x402conf {__version__} demo: a bundled mock facilitator and paid route on loopback"
          + (f" (fault: {a.fault})" if a.fault else "") + ", then the offline self-test. No wallet, no chain.\n")
    bad = 0
    for c, where in rows:
        failing = not c["pass"] and c.get("severity", "error") == "error"
        bad += failing
        mark = "pass" if c["pass"] else ("FAIL" if failing else "warn")
        print(f"  {mark}  [{where}] {c['check']}")
        if not c["pass"]:
            print(f"        fix: {anchor(c['check'].split()[0])}")
    caught = all(any(not r["pass"] for r in v) for k, v in off.items() if k != "reference")
    print(f"\n{len(rows) - bad}/{len(rows)} checks pass; the self-test caught "
          f"{'every' if caught else 'NOT every'} faulty build ({len(off) - 1}) in {secs:.1f} s\n")
    print("Next, check your own endpoints (read-only, nothing is paid):\n"
          "  x402conf resource https://your.api/paid\n  x402conf live https://your.facilitator\n"
          "and your server under fault injection: npx x402-conformance-svm demo, then probe --resource ...")
    if a.dir:
        os.makedirs(a.dir, exist_ok=True)
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        head = {"tool": f"x402-conformance {__version__}", **_evidence(), "run_at": stamp, "demo": True}
        for name, doc in (("live.json", {**head, "mode": "live-GET-only", "results": [live]}),
                          ("resource-402.json", {**head, "mode": "resource-GET-only", "results": [res402]}),
                          ("offline.json", {**head, "mode": "offline", "results": off})):
            with open(os.path.join(a.dir, name), "w") as f:
                json.dump(doc, f, indent=1)
                f.write("\n")
    return 0 if not bad and caught else 1


def action_summary(env: dict[str, str] | None = None) -> int:
    """The GitHub Action's last step: job summary, `result` output and exit status. Fail-closed: a run the caller asked
    for that left no results file (a crash, a build failure, a taken port) is a failure, never a silent pass."""
    e = dict(os.environ if env is None else env)
    d = e.get("X402C_DIR", "x402-conformance")
    want = {name: e.get(var) == "true" for name, var in (("live.json", "X402C_WANT_LIVE"),
                                                          ("resource-402.json", "X402C_WANT_402"),
                                                          ("resource-server.json", "X402C_WANT_PROBE"),
                                                          ("offline.json", "X402C_WANT_OFFLINE"))}
    bad: list[str] = []
    for name, wanted in want.items():
        if wanted and not os.path.exists(os.path.join(d, name)):
            bad.append(f"{name}: the requested run produced no results (it crashed or could not start); see the step log")
    rows = collect(d) if os.path.isdir(d) else []
    unsupported = False
    for r in rows:
        if r["pass"] or r["severity"] != "error":
            continue
        if isinstance(r["detail"], dict) and r["detail"].get("status") == "unsupported":
            unsupported = True
            bad.append(f"{r['target']}: unsupported, the probe can grade only Solana devnet or Base Sepolia exact routes")
        elif r["id"] == "RX" and isinstance(r["detail"], dict):
            bad.append(f"{r['target']}: the probe did not complete: {r['detail'].get('error')}")
        else:
            bad.append(f"{r['target']}: {r['check']}")
    rsv = os.path.join(d, "resource-server.json")
    if want["resource-server.json"] and os.path.exists(rsv):
        with open(rsv) as f:
            doc = json.load(f)
        core = [c for c in doc.get("results", []) if not c["check"].startswith(("R11", "R14"))]
        n = len(core)
        if doc.get("resource") and not doc.get("error") and not unsupported and n < 11 and all(c["pass"] for c in core):
            bad.append(f"{doc.get('resource')}: the probe stopped after {n} checks")
    if not any(want.values()):
        bad.append("nothing to check: set facilitators, resources, resource-url or offline")
    result = "pass" if not bad else ("unsupported" if unsupported and len(bad) == 1 else "fail")
    out = [f"## x402 Conformance: {result}", "", "| target | check | result |", "|---|---|---|"]
    for r in rows:
        mark = "pass" if r["pass"] else ("FAIL" if r["severity"] == "error" else r["severity"])
        target = "suite self-test (" + r["target"] + ")" if r["source"] == "offline.json" else r["target"]
        out.append(f"| {target} | {r['check']} | {mark} |")
    out += [""] + [f"- {b}" for b in bad if b.endswith("see the step log") or b.startswith("nothing")]
    out += ["", "How to fix a failed check: " + DOCS + "FIXES.md", "",
            "Checks map to spec text; they are not a certification of x402 conformance. "
            "Docs: https://github.com/atsp-protocol/x402-conformance"]
    if e.get("GITHUB_STEP_SUMMARY"):
        with open(e["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write("\n".join(out) + "\n")
    if os.path.isdir(d):
        failed = [r for r in rows if not r["pass"] and r["severity"] == "error"]
        comment = [COMMENT_MARKER] + out[:1] + [""]
        comment += ([f"{len(rows) - len(failed)}/{len(rows)} checks pass."] if rows else [])
        if failed:
            comment += ["", "| target | failed check | how to fix |", "|---|---|---|"]
            comment += [f"| {r['target']} | {r['check']} | [FIXES.md#{r['id'].lower()}]({anchor(r['id'])}) |"
                        for r in failed[:50]]
        comment += [f"- {b}" for b in bad if b.endswith("see the step log") or b.startswith("nothing")]
        comment += ["", "<sub>x402-conformance " + __version__ + ". Checks map to spec text; they are not a "
                        "certification. Full table in the job summary.</sub>"]
        with open(os.path.join(d, "pr-comment.md"), "w") as f:
            f.write("\n".join(comment) + "\n")
        with open(os.path.join(d, "badge.json"), "w") as f:
            json.dump(badge(rows, result), f, indent=1)
            f.write("\n")
    if e.get("GITHUB_OUTPUT"):
        with open(e["GITHUB_OUTPUT"], "a") as f:
            f.write(f"result={result}\n")
    for b in bad:
        print(f"::error title=x402 Conformance::{b}")
    return 1 if bad and e.get("X402C_FAIL", "true") == "true" else 0


def _evidence() -> dict[str, Any]:
    """Evidence v2: the format, and the versions a rerun needs to reproduce the result."""
    return {"evidence": S.EVIDENCE_FORMAT,
            "versions": {"x402-conformance": __version__, "python": platform.python_version()}}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["--"]:  # `pipx run ... x402conf -- --version` passes the separator through
        args = args[1:]
    if args[:1] == ["devnet"]:
        from .devnet import runner

        return runner.main(args[1:])
    a = parser().parse_args(args)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if a.mode == "report":
        return report(a)
    if a.mode == "demo":
        return demo(a)
    if a.mode == "pr-comment":
        return pr_comment(a.file)
    if a.mode == "resource":
        rruns = [H.run_resource(t) for t in a.targets]
        reports = [make_report("resource-402", r["target"], r["checks"]) for r in rruns]
        print(json.dumps({"tool": f"x402-conformance {__version__}", **_evidence(), "run_at": stamp,
                          "mode": "resource-GET-only", "via": H.via(), "links": LINKS, "results": rruns},
                         indent=1, sort_keys=True))
        if a.share:
            for path, link in write_cases(reports):
                print(f"x402conf: anonymised case written to {path}. " + (
                    f"Review it, then submit it here (nothing was sent):\n{link}" if link else
                    "Nothing failed, so there is no case to share."), file=sys.stderr)
        for rep in reports:
            print(funnel_footer(rep), file=sys.stderr)
        return 1 if a.fail_on_error and failed_errors(rruns) else 0
    if a.mode == "live":
        try:
            runs = [H.run_live(t) for t in a.targets]
        except H.UsageError as e:
            print(f"x402conf live: {e}", file=sys.stderr)
            return 2
        sums = []
        for r in runs:
            raw = r.pop("raw", None)
            if raw is not None:
                r["body_sha256"] = hashlib.sha256(raw).hexdigest()
                if a.evidence:
                    os.makedirs(a.evidence, exist_ok=True)
                    name = "supported-" + r["target"].split("//", 1)[-1].replace("/", "_") + ".json"
                    with open(os.path.join(a.evidence, name), "wb") as fb:
                        fb.write(raw)
                    sums.append(f"{r['body_sha256']}  {name}")
        out = {"tool": f"x402-conformance {__version__}", **_evidence(), "run_at": stamp, "mode": "live-GET-only",
               "results": runs}
        text = json.dumps(out, indent=1, sort_keys=True)
        if a.evidence:
            os.makedirs(a.evidence, exist_ok=True)
            with open(os.path.join(a.evidence, "run.json"), "w") as f:
                f.write(text + "\n")
            sums.append(hashlib.sha256((text + "\n").encode()).hexdigest() + "  run.json")
            with open(os.path.join(a.evidence, "SHA256SUMS"), "w") as f:
                f.write("\n".join(sorted(sums, key=lambda s: s.split("  ")[1])) + "\n")
        print(text)
        return 1 if a.fail_on_error and failed_errors(runs) else 0
    res = {k: H.check_safety(f(), M.vectors()) for k, f in M.FAULTS.items()}
    res.update({k: H.check_safety(M.Reference(), M.vectors(), guard=g) for k, g in H.GUARD_FAULTS.items()})
    print(json.dumps({"tool": f"x402-conformance {__version__}", **_evidence(), "run_at": stamp, "mode": "offline",
                      "results": res},
                     indent=1))
    ref_ok = all(r["pass"] for r in res["reference"])
    caught = all(any(not r["pass"] for r in v) for k, v in res.items() if k != "reference")
    return 0 if ref_ok and caught else 1


if __name__ == "__main__":
    sys.exit(main())
