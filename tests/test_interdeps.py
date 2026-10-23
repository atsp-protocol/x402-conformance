"""tools/interdeps.py: the committed map is current and the docs match the code, and each kind of drift is caught.

Every negative test copies the tracked tree to a temporary directory, breaks one thing and runs the tool with
--root on the copy, so the checker is shown to fail on exactly what it claims to catch."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "tools", "interdeps.py")
NEW_CHECK = '    "R98": {"profile": "resilience", "basis": "x"},\n'


def run(*args: str, root: str = ROOT) -> tuple[int, str]:
    p = subprocess.run([sys.executable, TOOL, "--root", root, *args], capture_output=True, text=True, timeout=120)
    return p.returncode, p.stdout + p.stderr


def edit(root: str, path: str, old: str, new: str) -> None:
    f = os.path.join(root, path)
    with open(f, encoding="utf-8") as h:
        text = h.read()
    assert old in text, f"{old!r} not in {path}"
    with open(f, "w", encoding="utf-8") as h:
        h.write(text.replace(old, new, 1))


def append(root: str, path: str, text: str) -> None:
    with open(os.path.join(root, path), "a", encoding="utf-8") as h:
        h.write(text)


class Interdeps(unittest.TestCase):
    copy: str
    tmp: tempfile.TemporaryDirectory[str]

    @classmethod
    def setUpClass(cls) -> None:
        files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        cls.tmp = tempfile.TemporaryDirectory()
        cls.src = os.path.join(cls.tmp.name, "src-tree")
        for f in files.splitlines():
            if not os.path.isfile(os.path.join(ROOT, f)):
                continue
            os.makedirs(os.path.dirname(os.path.join(cls.src, f)) or cls.src, exist_ok=True)
            shutil.copy2(os.path.join(ROOT, f), os.path.join(cls.src, f))
        # the copy holds the working tree, so the map the tool writes there is the one to compare against
        rc, out = run(root=cls.src)
        assert rc == 0, out

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def setUp(self) -> None:
        self.copy = tempfile.mkdtemp(dir=self.tmp.name)
        os.rmdir(self.copy)
        shutil.copytree(self.src, self.copy)

    # ---------------- the real tree ----------------
    def test_committed_map_is_current(self) -> None:
        rc, out = run("--check")
        self.assertEqual(rc, 0, out)

    def test_no_drift_in_the_tree(self) -> None:
        rc, out = run("--drift")
        self.assertEqual(rc, 0, out)

    def test_versions_match_the_python_package(self) -> None:
        with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as h:
            m = re.search(r'^version\s*=\s*"([^"]+)"', h.read(), re.M)
        assert m
        rc, out = run("--versions", m.group(1))
        self.assertEqual(rc, 0, out)

    def test_map_has_a_mermaid_graph_every_task_and_every_built_check(self) -> None:
        with open(os.path.join(ROOT, "docs", "INTERDEPENDENCY.md"), encoding="utf-8") as h:
            text = h.read()
        self.assertRegex(text, r"(?m)^```mermaid$")
        with open(os.path.join(ROOT, "proofline.json"), encoding="utf-8") as h:
            for t in json.load(h)["tasks"]:
                self.assertIn(f"| {t['id']} ", text)
        sys.path.insert(0, os.path.join(ROOT, "src"))
        from x402conf import spec as S

        for c in S.CATALOG:
            self.assertRegex(text, rf"(?m)^\| {re.escape(c)} \| built \|")

    def test_the_build_is_deterministic(self) -> None:
        run(root=self.copy)
        with open(os.path.join(self.copy, "docs", "INTERDEPENDENCY.md"), encoding="utf-8") as h:
            first = h.read()
        run(root=self.copy)
        with open(os.path.join(self.copy, "docs", "INTERDEPENDENCY.md"), encoding="utf-8") as h:
            self.assertEqual(h.read(), first)

    # ---------------- the control: an untouched copy passes ----------------
    def test_control_an_untouched_copy_passes(self) -> None:
        for args in (("--check",), ("--drift",)):
            rc, out = run(*args, root=self.copy)
            self.assertEqual(rc, 0, f"{args}: {out}")

    # ---------------- a stale map ----------------
    def test_a_hand_edited_map_is_stale(self) -> None:
        append(self.copy, "docs/INTERDEPENDENCY.md", "\nan edit by hand\n")
        rc, out = run("--check", root=self.copy)
        self.assertEqual(rc, 1, out)
        self.assertIn("stale", out)

    def test_a_new_file_in_a_component_keeps_the_map_current(self) -> None:
        # Two pull requests that each add a file must not stale each other's committed map.
        append(self.copy, "docs/proposals/contract-addendum-zz-probe.json", "{}\n")
        rc, out = run("--check", root=self.copy)
        self.assertEqual(rc, 0, out)

    def test_a_new_check_without_regenerating_the_map_is_stale(self) -> None:
        edit(self.copy, "src/x402conf/spec.py", '    "R14": {', NEW_CHECK + '    "R14": {')
        rc, out = run("--check", root=self.copy)
        self.assertEqual(rc, 1, out)

    def test_a_new_contract_task_without_regenerating_the_map_is_stale(self) -> None:
        f = os.path.join(self.copy, "proofline.json")
        with open(f, encoding="utf-8") as h:
            c = json.load(h)
        c["tasks"].append({"id": "XC-99", "title": "a task added later", "phase": "implement", "criteria": []})
        with open(f, "w", encoding="utf-8") as h:
            json.dump(c, h)
        rc, out = run("--check", root=self.copy)
        self.assertEqual(rc, 1, out)

    # ---------------- check ids ----------------
    def test_a_doc_naming_an_unknown_check_id_is_drift(self) -> None:
        append(self.copy, "docs/USING.md", "\nR99 checks something that does not exist.\n")
        rc, out = run("--drift", root=self.copy)
        self.assertEqual(rc, 1, out)
        self.assertIn("check id R99 is named in docs/USING.md but is neither built nor planned", out)

    def test_a_built_check_no_doc_names_is_drift(self) -> None:
        edit(self.copy, "src/x402conf/spec.py", '    "R14": {', NEW_CHECK + '    "R14": {')
        rc, out = run("--drift", root=self.copy)
        self.assertEqual(rc, 1, out)
        self.assertIn("check id R98 is built but no doc names it", out)

    def test_a_planned_check_named_by_a_task_is_not_drift(self) -> None:
        # R12 and R13 are planned by XC-17's title; naming them in a doc is fine
        append(self.copy, "docs/USING.md", "\nR12 and R13 are planned.\n")
        rc, out = run("--drift", root=self.copy)
        self.assertEqual(rc, 0, out)

    # ---------------- CLI flags ----------------
    def test_a_doc_naming_a_flag_the_cli_lacks_is_drift(self) -> None:
        append(self.copy, "README.md", "\n```\nx402conf live https://f.example --no-such-flag\n```\n")
        rc, out = run("--drift", root=self.copy)
        self.assertEqual(rc, 1, out)
        self.assertIn("x402conf flag --no-such-flag is in README.md but not in the code", out)

    def test_a_doc_naming_a_flag_the_node_cli_lacks_is_drift(self) -> None:
        append(self.copy, "ts/README.md", "\n`npx x402-conformance-svm probe --resource http://x/paid --turbo`\n")
        rc, out = run("--drift", root=self.copy)
        self.assertEqual(rc, 1, out)
        self.assertIn("x402conf-svm flag --turbo is in ts/README.md but not in the code", out)

    def test_a_flag_no_doc_names_is_drift(self) -> None:
        edit(self.copy, "src/x402conf/cli.py", 'rp.add_argument("--dir"',
             'rp.add_argument("--undocumented-switch", action="store_true")\n    rp.add_argument("--dir"')
        rc, out = run("--drift", root=self.copy)
        self.assertEqual(rc, 1, out)
        self.assertIn("x402conf flag --undocumented-switch is in the code but no doc names it", out)

    def test_a_node_cli_flag_no_doc_names_is_drift(self) -> None:
        edit(self.copy, "ts/src/cli.ts", 'const BOOL = new Set(["--share",', 'const BOOL = new Set(["--quietly", "--share",')
        rc, out = run("--drift", root=self.copy)
        self.assertEqual(rc, 1, out)
        self.assertIn("x402conf-svm flag --quietly is in the code but no doc names it", out)

    # ---------------- Action inputs ----------------
    def test_a_doc_using_an_input_the_action_lacks_is_drift(self) -> None:
        append(self.copy, "docs/USING.md", "\n```yaml\n      - uses: atsp-protocol/x402-conformance@v1\n"
                                           "        with:\n          resource-url: http://127.0.0.1:4020/paid\n"
                                           "          no-such-input: yes\n```\n")
        rc, out = run("--drift", root=self.copy)
        self.assertEqual(rc, 1, out)
        self.assertIn("Action input no-such-input is in docs/USING.md but not in action.yml", out)
        self.assertNotIn("Action input resource-url is in", out)

    def test_an_input_no_doc_names_is_drift(self) -> None:
        edit(self.copy, "action.yml", "\n  crash:\n",
             "\n  undocumented-input:\n    description: x\n    required: false\n    default: \"\"\n  crash:\n")
        rc, out = run("--drift", root=self.copy)
        self.assertEqual(rc, 1, out)
        self.assertIn("Action input undocumented-input is in action.yml but no doc names it", out)

    # ---------------- versions ----------------
    def test_versions_that_disagree_are_drift(self) -> None:
        f = os.path.join(self.copy, "ts", "mcp", "package.json")
        with open(f, encoding="utf-8") as h:
            p = json.load(h)
        p["version"] = "0.0.1"
        with open(f, "w", encoding="utf-8") as h:
            json.dump(p, h)
        rc, out = run("--drift", root=self.copy)
        self.assertEqual(rc, 1, out)
        self.assertIn("package versions disagree", out)
        self.assertIn("ts/mcp/package.json=0.0.1", out)

    def test_versions_other_than_the_one_asked_for_fail(self) -> None:
        rc, out = run("--versions", "0.0.0", root=self.copy)
        self.assertEqual(rc, 1, out)
        self.assertIn("not 0.0.0", out)

    # ---------------- files, components and the PR gate ----------------
    def test_every_tracked_file_is_in_a_component(self) -> None:
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import interdeps as I

        self.assertEqual(I.coverage(ROOT), [])

    def test_a_file_no_component_covers_fails_the_check(self) -> None:
        append(self.copy, "stray.txt", "x\n")
        run(root=self.copy)
        rc, out = run("--check", root=self.copy)
        self.assertEqual(rc, 1, out)
        self.assertIn("stray.txt: no component covers it", out)

    def test_the_gate_fails_only_on_direct_downstream_docs_contracts_and_tests(self) -> None:
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import interdeps as I

        g = I.gate(["src/x402conf/spec.py"], "")
        self.assertEqual(g["changed"], ["catalog"])
        self.assertEqual(g["missing"], ["changelog", "docs", "interdeps-map", "py-tests", "readme", "vv-doc"])
        self.assertIn("ts-catalog", g["review"])  # code downstream: review only
        self.assertIn("ts-tests", g["review"])  # two steps out: review only
        self.assertEqual(I.gate(["docs/USING.md"], "")["missing"], ["interdeps-map", "readme", "site"])
        self.assertNotIn("catalog", I.gate(["docs/USING.md"], "")["missing"])  # upstream never fails
        self.assertEqual(I.gate(["README.md"], "Interdeps-Ack: interdeps-map, site - wording only")["missing"], [])

    def test_an_ack_needs_a_reason_and_a_known_component(self) -> None:
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import interdeps as I

        self.assertEqual(I.acks("Interdeps-Ack: docs\nInterdeps-Ack: docs -\n"), {})
        self.assertEqual(I.gate(["README.md"], "Interdeps-Ack: site, nope - checked")["unknown_acks"], ["nope"])

    def test_the_gate_reads_the_diff_and_the_pr_body(self) -> None:
        def git(*a: str) -> None:
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a],
                           cwd=self.copy, check=True, capture_output=True)

        git("init", "-q", "-b", "main")
        git("add", "-A")
        git("commit", "-q", "-m", "base")
        append(self.copy, "README.md", "\nmore\n")
        git("commit", "-q", "-am", "readme")
        rc, out = run("--gate", "--base", "HEAD~1", root=self.copy)
        self.assertEqual(rc, 1, out)
        self.assertIn("MISSING interdeps-map", out)
        env = dict(os.environ, PR_BODY="Interdeps-Ack: interdeps-map, site - wording only")
        p = subprocess.run([sys.executable, TOOL, "--root", self.copy, "--gate", "--base", "HEAD~1"],
                           capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
