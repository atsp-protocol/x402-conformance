"""XC-83: the offline CI job another repository can paste in, docs/ci/x402-conformance-offline.yml.

    PYTHONPATH=src python3 -m unittest -v tests.test_ci_template     the template's rules and the runner
    python3 tests/test_ci_template.py --run docs/ci/x402-conformance-offline.yml
                                                                      run the template's job as written, from the
                                                                      tree root (this repo's CI does, so it cannot rot)

The rules: the template references no secret, no key or wallet variable, no URL and no network, uses only checkout and
setup-python, has one job, and pins the suite to the version in pyproject.toml. docs/USING.md shows it verbatim. The
runner runs every `run` step in order with bash -e and stops at the first that fails; it refuses any other action,
because the CI job that calls it sets up checkout and Python itself, the same way the template does.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = "docs/ci/x402-conformance-offline.yml"
ACTIONS = {"actions/checkout@v4", "actions/setup-python@v5"}
STEP_KEYS = {"name", "uses", "with", "run", "env"}
FORBIDDEN = [
    (re.compile(r"secrets\s*\.", re.I), "a secret"),
    (re.compile(r"private[_-]?key|mnemonic|seed[_ -]?phrase|api[_-]?key|password|token|secret", re.I), "a key variable"),
    (re.compile(r"wallet|keypair", re.I), "a wallet"),
    (re.compile(r"https?://", re.I), "a URL (a paid endpoint or a hosted service)"),
    (re.compile(r"\b(eip155|solana):", re.I), "a network"),
]
# the package as a whole word on a pip install line, with its version spec if any
PIN = re.compile(r"(?<![\w.-])x402-conformance(?P<spec>[=<>~!]=?[^\s]*)?(?=\s|$)")


def read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def load(path: str) -> dict:
    import yaml  # CI's test job installs pyyaml
    with open(path, encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    return doc if isinstance(doc, dict) else {}


def released() -> str:
    m = re.search(r'(?m)^version = "([^"]+)"', read(os.path.join(ROOT, "pyproject.toml")))
    return m.group(1) if m else ""


def job_of(doc: dict) -> tuple[str, dict]:
    jobs = doc.get("jobs") if isinstance(doc.get("jobs"), dict) else {}
    return next(iter(jobs.items())) if len(jobs) == 1 else ("", {})


def problems(doc: dict, version: str) -> list[str]:
    """What keeps a parsed template from being a job anyone can paste in. Comments are gone once parsed."""
    out: list[str] = []
    jobs = doc.get("jobs") if isinstance(doc.get("jobs"), dict) else {}
    if len(jobs) != 1:
        out.append(f"the template has {len(jobs)} jobs, not one")
    text = json.dumps(doc)
    for pat, what in FORBIDDEN:
        hit = pat.search(text)
        if hit:
            out.append(f"the template references {what}: {hit.group(0)!r}")
    pins = []
    for name, job in jobs.items():
        for i, step in enumerate(job.get("steps") or []):
            extra = set(step) - STEP_KEYS
            if extra:
                out.append(f"{name} step {i + 1} has keys the runner does not run: {', '.join(sorted(extra))}")
            if "uses" in step and step["uses"] not in ACTIONS:
                out.append(f"{name} step {i + 1} uses {step['uses']}, not one of {', '.join(sorted(ACTIONS))}")
            pins += [m.group("spec") or "" for line in str(step.get("run") or "").splitlines() if "pip install" in line
                     for m in PIN.finditer(line)]
    if not pins:
        out.append("the template never installs x402-conformance")
    for spec in pins:
        if spec != f"=={version}":
            out.append(f"x402-conformance{spec} is not pinned to the released version =={version}")
    return out


def run_job(path: str, root: str = ROOT) -> int:
    """Run the template's job as written: every `run` step in order, from `root`, with bash -e."""
    _, job = job_of(load(path))
    if not job:
        print(f"{path}: not exactly one job", file=sys.stderr)
        return 2
    env = {**os.environ, **{k: str(v) for k, v in (job.get("env") or {}).items()}}
    for i, step in enumerate(job.get("steps") or []):
        if "uses" in step:
            if step["uses"] not in ACTIONS:
                print(f"{path}: step {i + 1} uses {step['uses']}, which this runner cannot run", file=sys.stderr)
                return 2
            continue  # the calling CI job sets up checkout and Python itself
        print(f"::group::{step.get('name') or step['run'].splitlines()[0]}", flush=True)
        rc = subprocess.run(["bash", "-e", "-c", step["run"]], cwd=root,
                            env={**env, **{k: str(v) for k, v in (step.get("env") or {}).items()}}).returncode
        print("::endgroup::", flush=True)
        if rc:
            print(f"{path}: step {i + 1} ({step.get('name') or 'run'}) exited {rc}", file=sys.stderr)
            return rc
    return 0


class Template(unittest.TestCase):
    def setUp(self) -> None:
        self.doc = load(os.path.join(ROOT, TEMPLATE))

    def test_the_template_follows_the_rules(self) -> None:
        self.assertEqual(problems(self.doc, released()), [])

    def test_it_pins_the_released_version(self) -> None:
        self.assertTrue(released())
        self.assertIn(f"x402-conformance=={released()}", read(os.path.join(ROOT, TEMPLATE)))

    def test_using_md_shows_it_verbatim(self) -> None:
        template = read(os.path.join(ROOT, TEMPLATE)).strip()
        using = read(os.path.join(ROOT, "docs", "USING.md"))
        self.assertIn(f"```yaml\n{template}\n```", using)

    def test_this_repos_ci_runs_it_as_written(self) -> None:
        ci = load(os.path.join(ROOT, ".github", "workflows", "ci.yml"))
        _, job = job_of(self.doc)
        want = [s for s in job["steps"] if "uses" in s]
        runs = [(n, j) for n, j in (ci.get("jobs") or {}).items()
                if any(f"tests/test_ci_template.py --run {TEMPLATE}" in str(s.get("run") or "") for s in j.get("steps") or [])]
        self.assertEqual(len(runs), 1, "one CI job runs the template")
        steps = runs[0][1]["steps"]
        # the CI job sets up exactly what the template's own uses steps set up, before it runs the template
        self.assertEqual([s for s in steps if "uses" in s], want)


class Rules(unittest.TestCase):
    def doc(self, *steps: dict, jobs: int = 1) -> dict:
        base = [{"uses": "actions/checkout@v4"}, {"uses": "actions/setup-python@v5", "with": {"python-version": "3.12"}},
                {"run": f"python -m pip install x402-conformance=={released()}"}, {"run": "x402conf offline"}]
        return {"name": "t", "on": {"pull_request": None},
                "jobs": {f"j{i}": {"runs-on": "ubuntu-latest", "steps": base + list(steps)} for i in range(jobs)}}

    def caught(self, doc: dict, what: str) -> None:
        self.assertTrue(any(what in p for p in problems(doc, released())), (what, problems(doc, released())))

    def test_a_clean_job_passes(self) -> None:
        self.assertEqual(problems(self.doc(), released()), [])

    def test_a_secret_is_caught(self) -> None:
        self.caught(self.doc({"run": "echo ${{ secrets.FACILITATOR }}"}), "a secret")

    def test_a_key_variable_is_caught(self) -> None:
        self.caught(self.doc({"run": "x402conf offline", "env": {"PRIVATE_KEY": "0x00"}}), "a key variable")

    def test_a_wallet_is_caught(self) -> None:
        self.caught(self.doc({"run": "solana-keygen new --outfile wallet.json"}), "a wallet")

    def test_a_paid_endpoint_is_caught(self) -> None:
        self.caught(self.doc({"run": "x402conf resource https://api.example.com/paid"}), "a URL")

    def test_a_network_is_caught(self) -> None:
        self.caught(self.doc({"run": "x402conf devnet --network solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"}), "a network")

    def test_an_unpinned_or_stale_install_is_caught(self) -> None:
        self.caught(self.doc({"run": "pip install x402-conformance"}), "not pinned")
        self.caught(self.doc({"run": "pip install x402-conformance==1.0.0"}), "not pinned")

    def test_another_action_and_a_second_job_are_caught(self) -> None:
        self.caught(self.doc({"uses": "some-org/pay-action@v1"}), "uses some-org/pay-action@v1")
        self.caught(self.doc(jobs=2), "2 jobs")

    def test_a_step_key_the_runner_does_not_run_is_caught(self) -> None:
        self.caught(self.doc({"run": "true", "if": "always()"}), "keys the runner does not run: if")


class Runner(unittest.TestCase):
    def template(self, steps: list) -> str:
        d = tempfile.mkdtemp()
        p = os.path.join(d, "t.yml")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"jobs": {"j": {"runs-on": "ubuntu-latest", "steps": steps}}}, f)  # JSON is YAML
        return p

    def test_it_runs_each_run_step_in_order_from_the_root(self) -> None:
        d = tempfile.mkdtemp()
        p = self.template([{"uses": "actions/checkout@v4"}, {"run": "echo one >> order.txt"},
                           {"run": "echo two >> order.txt", "env": {"X402_T": "x"}}, {"run": "echo $X402_T >> order.txt"}])
        self.assertEqual(run_job(p, d), 0)
        self.assertEqual(read(os.path.join(d, "order.txt")).split(), ["one", "two"])

    def test_it_stops_at_the_first_failing_step(self) -> None:
        d = tempfile.mkdtemp()
        p = self.template([{"run": "echo one >> order.txt"}, {"run": "exit 3"}, {"run": "echo three >> order.txt"}])
        self.assertEqual(run_job(p, d), 3)
        self.assertEqual(read(os.path.join(d, "order.txt")).split(), ["one"])

    def test_it_refuses_an_action_it_cannot_run(self) -> None:
        self.assertEqual(run_job(self.template([{"uses": "some-org/pay-action@v1"}, {"run": "true"}]), tempfile.mkdtemp()), 2)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--run"] and len(sys.argv) == 3:
        sys.exit(run_job(os.path.join(ROOT, sys.argv[2])))
    unittest.main()
