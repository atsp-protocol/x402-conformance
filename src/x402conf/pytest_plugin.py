"""x402-conformance inside pytest. Installed with the package and registered as the `x402` plugin, so any test suite
gets the `x402` fixture with no conftest changes:

    def test_my_402_answer(x402):
        x402.assert_passed(x402.check_payment_required("http://127.0.0.1:8000/paid"))

    def test_my_server_never_serves_before_settlement(x402):
        report = x402.probe("http://127.0.0.1:4020/paid", start="uvicorn app:app --port 4020")
        x402.assert_passed(report)

check_payment_required runs P1-P7 in Python with one unpaid GET. probe runs R0-R10 through the Node probe
(x402conf-svm, or X402CONF_SVM, or npx), which starts the facilitator double and your server with
X402_FACILITATOR_URL pointing at it. Every report is the shared x402-conformance.report/1 with via=pytest. Options:
--x402-report-dir DIR writes each report there; --x402-share also writes anonymised corpus cases and lists the links to
submit them in the terminal summary. Nothing is ever sent."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
from typing import Any

import pytest

from . import __version__
from . import cli as C
from . import harness as H

VIA = "pytest"


def _explain(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [f"x402-conformance {report['version']} ({report['kind']}, via {report['via']}) on {report['target']}: " +
             (f"could not complete: {report['error']}" if report.get("error") else
              f"{s['checks']} checks, {s['failed']} failed")]
    for r in report["results"]:
        if r["pass"]:
            continue
        cid = r["check"].split(" ")[0]
        lines += [f"  {'UNSUPPORTED' if r['status'] == 'unsupported' else r['severity'].upper()} {r['check']}",
                  f"    detail: {json.dumps(r['detail'])[:300]}",
                  f"    how to fix: {C.LINKS['fixes']}#{cid.lower()}"]
    return "\n".join(lines + [C.funnel_footer(report)])


def passed(report: dict[str, Any]) -> bool:
    return not report.get("error") and not report["summary"]["unsupported"] and all(
        r["pass"] or r["severity"] == "warning" for r in report["results"])


def _svm_command() -> list[str]:
    env = os.environ.get("X402CONF_SVM")
    if env:
        return shlex.split(env)
    exe = shutil.which("x402conf-svm")
    if exe:
        return [exe]
    npx = shutil.which("npx")
    if npx:
        return [npx, "-y", f"x402-conformance-svm@{__version__}"]
    raise pytest.UsageError("x402.probe needs Node 20+: install x402-conformance-svm, put npx on PATH, or set "
                            "X402CONF_SVM to the command that runs x402conf-svm")


class X402:
    """The `x402` fixture."""

    def __init__(self, config: pytest.Config) -> None:
        self._config = config
        self.reports: list[dict[str, Any]] = []

    def _keep(self, report: dict[str, Any]) -> dict[str, Any]:
        self.reports.append(report)
        d = self._config.getoption("x402_report_dir")
        if d:
            os.makedirs(d, exist_ok=True)
            name = f"{report['kind']}-{len(_session_reports(self._config)) + 1}"
            with open(os.path.join(d, name + ".json"), "w") as f:
                f.write(json.dumps(report, indent=1) + "\n")
        _session_reports(self._config).append(report)
        return report

    def check_payment_required(self, url: str, timeout: float = 15) -> dict[str, Any]:
        """P1-P7 against url: one unpaid GET, never a payment."""
        old = os.environ.get(H.VIA_ENV)
        os.environ[H.VIA_ENV] = VIA
        try:
            run = H.run_resource(url, timeout=timeout)
        finally:
            if old is None:
                os.environ.pop(H.VIA_ENV, None)
            else:
                os.environ[H.VIA_ENV] = old
        return self._keep(C.make_report("resource-402", url, run["checks"], via=VIA))

    def probe(self, resource_url: str, *, start: str | None = None, network: str = "auto", port: int = 4402,
              timeout: float = 600) -> dict[str, Any]:
        """R0-R10 against your server through the facilitator double on 127.0.0.1:port. With start, the probe starts
        your server with X402_FACILITATOR_URL set; without it, your server must already use that URL."""
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "resource-server.json")
            cmd = [*_svm_command(), "probe", "--resource", resource_url, "--port", str(port), "--network", network,
                   "--out", out]
            if start:
                cmd += ["--start", start]
            try:
                p = subprocess.run(cmd, env={**os.environ, H.VIA_ENV: VIA}, capture_output=True, text=True,
                                   timeout=timeout)
            except (OSError, subprocess.TimeoutExpired) as e:
                return self._keep(C.make_report("resource-server", resource_url, [], via=VIA,
                                                error=f"could not run x402conf-svm: {e}"[:300]))
            if not os.path.exists(out):
                return self._keep(C.make_report("resource-server", resource_url, [], via=VIA,
                                                error=(p.stderr.strip() or f"x402conf-svm exited {p.returncode}")[:300]))
            with open(out) as f:
                doc = json.load(f)
        return self._keep(C.make_report("resource-server", resource_url, doc.get("results", []), via=VIA,
                                        error=doc.get("error")))

    @staticmethod
    def assert_passed(report: dict[str, Any]) -> None:
        """Fails the test with every failed check, its detail and fix link, and how to share it."""
        if not passed(report):
            pytest.fail(_explain(report), pytrace=False)


_KEY = pytest.StashKey[list[dict[str, Any]]]()


def _session_reports(config: pytest.Config) -> list[dict[str, Any]]:
    if _KEY not in config.stash:
        config.stash[_KEY] = []
    return config.stash[_KEY]


def pytest_addoption(parser: pytest.Parser) -> None:
    g = parser.getgroup("x402", "x402-conformance")
    g.addoption("--x402-report-dir", dest="x402_report_dir", default=None,
                help="write every x402-conformance report (x402-conformance.report/1) to this directory")
    g.addoption("--x402-share", dest="x402_share", action="store_true", default=False,
                help="opt-in: write anonymised corpus cases for failing x402 runs and list the links to submit them; "
                     "nothing is sent")


@pytest.fixture
def x402(request: pytest.FixtureRequest) -> X402:
    """Run x402-conformance checks from a test: check_payment_required(url), probe(url, start=...), assert_passed()."""
    return X402(request.config)


def pytest_terminal_summary(terminalreporter: Any, exitstatus: int, config: pytest.Config) -> None:
    reports = _session_reports(config)
    if not reports:
        return
    tr = terminalreporter
    failed = [r for r in reports if not passed(r)]
    tr.section("x402-conformance")
    tr.write_line(f"{len(reports)} run(s), {len(failed)} with failures. Corpus of known x402 failures: "
                  f"{C.LINKS['corpus']}")
    if failed and config.getoption("x402_share"):
        directory = config.getoption("x402_report_dir") or "."
        os.makedirs(directory, exist_ok=True)
        for path, link in C.write_cases(failed, directory):
            if link:
                tr.write_line(f"anonymised case: {path}. Review it, then submit it here (nothing was sent): {link}")
    elif failed:
        tr.write_line("Share a failure as an anonymised corpus case (opt-in): re-run with --x402-share, or "
                      f"{C.LINKS['contribute']}")
    else:
        tr.write_line(f"All passed. Add the badge to your README: {C.LINKS['badge']}")
