"""tools/doc_examples.py: the tree's marked examples run (XC-27-AC01 is the same run), and a deliberately broken
example of each kind is detected. The negatives use a temporary root that holds copies of the docs and links to the
build, so they add nothing to the tree and never run the real examples twice."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import doc_examples as D  # noqa: E402

BROKEN = ROOT / "examples" / "broken-for-the-test" / "README.md"   # never created in the tree, only in the copy


def temp_root() -> str:
    """A root with copies of the small inputs and links to src, ts/dist, ts/node_modules and ts/src."""
    tmp = tempfile.mkdtemp(prefix="doc-examples-")
    for rel in ("README.md", "action.yml", "docs", "examples", "ts/ci/gitlab"):
        src = ROOT / rel
        dst = Path(tmp) / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    for rel in ("src", "ts/dist", "ts/node_modules", "ts/src"):
        dst = Path(tmp) / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if (ROOT / rel).exists():
            os.symlink(ROOT / rel, dst)
    return tmp


class DocExamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = temp_root()
        cls.broken = Path(cls.tmp) / "examples" / "broken-for-the-test" / "README.md"
        cls.broken.parent.mkdir(parents=True)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp)

    def broken_run(self, text: str) -> list[str]:
        """Writes one README with the given example, runs only it, and returns the problems."""
        self.broken.write_text(text, encoding="utf-8")
        _, problems = D.run(self.tmp, "examples/broken-for-the-test/README.md")
        return problems

    # ---------------- the real tree ----------------
    def test_the_tree_marks_examples_of_every_kind_that_runs_offline(self):
        kinds = {e.kind for e in D.examples(str(ROOT))}
        self.assertTrue({"cli", "gitlab", "python", "ts", "json"} <= kinds, kinds)

    def test_an_unmarked_fence_is_not_an_example(self):
        # docs/USING.md's docker block has no marker, so it is never run (it would need docker).
        self.assertFalse(any("docker run" in "\n".join(e.body) for e in D.examples(str(ROOT))))

    def test_list_names_every_marked_example(self):
        exs = D.examples(str(ROOT))
        self.assertTrue(all(e.file and e.line > 0 and e.kind in D.KINDS for e in exs))
        self.assertFalse([p for e in exs for p in e.problems], "a marker without a fence, or an unknown kind")

    # ---------------- controls on the copy ----------------
    def test_a_good_example_of_each_checked_kind_passes(self):
        text = """# t
<!-- runnable: cli -->
```
true
false   # exits 1
```
<!-- runnable: actions -->
```yaml
jobs:
  x402:
    steps:
      - uses: atsp-protocol/x402-conformance@v1
        with:
          resource-url: http://127.0.0.1:4020/paid
          start: node server.js
```
<!-- runnable: gitlab -->
```yaml
include:
  - remote: https://raw.githubusercontent.com/atsp-protocol/x402-conformance/v1/ts/ci/gitlab/x402-conformance.gitlab-ci.yml
x402-conformance:
  variables:
    X402_RESOURCE_URL: http://127.0.0.1:4020/paid
```
<!-- runnable: python -->
```python
x = 1
```
<!-- runnable: json -->
```json
{"a": 1}
```
"""
        self.assertEqual(self.broken_run(text), [])

    # ---------------- each kind can fail ----------------
    def test_a_cli_line_that_exits_wrong_is_caught(self):
        problems = self.broken_run("<!-- runnable: cli -->\n```\ntrue\nexit 3\n```\n")
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("examples/broken-for-the-test/README.md:2: `exit 3` exited 3, expected 0", problems[0])

    def test_a_cli_line_expected_to_fail_that_passes_is_caught(self):
        problems = self.broken_run("<!-- runnable: cli -->\n```\ntrue   # exits 1\n```\n")
        self.assertTrue(any("exited 0, expected 1" in p for p in problems), problems)

    def test_an_actions_input_the_action_lacks_is_caught(self):
        text = """<!-- runnable: actions -->
```yaml
- uses: atsp-protocol/x402-conformance@v1
  with:
    resource-url: http://127.0.0.1:4020/paid
    resource-urll: typo
```
"""
        problems = self.broken_run(text)
        self.assertTrue(any("gives input `resource-urll`, which action.yml does not declare" in p for p in problems), problems)

    def test_a_gitlab_variable_the_template_does_not_read_is_caught(self):
        text = """<!-- runnable: gitlab -->
```yaml
include:
  - remote: https://raw.githubusercontent.com/atsp-protocol/x402-conformance/v1/ts/ci/gitlab/x402-conformance.gitlab-ci.yml
x402-conformance:
  variables:
    X402_RESOURCE_URL: http://127.0.0.1:4020/paid
    X402_RESOURCE_URLS: nope
```
"""
        problems = self.broken_run(text)
        self.assertTrue(any("sets `X402_RESOURCE_URLS`, which neither the template nor the ci entry point reads" in p
                            for p in problems), problems)

    def test_a_gitlab_include_of_an_untracked_template_is_caught(self):
        text = "<!-- runnable: gitlab -->\n```yaml\ninclude:\n  - remote: https://example.invalid/other.yml\n```\n"
        problems = self.broken_run(text)
        self.assertTrue(any("does not name the tracked template" in p for p in problems), problems)

    def test_invalid_yaml_is_caught(self):
        problems = self.broken_run("<!-- runnable: actions -->\n```yaml\njobs: [\n```\n")
        self.assertTrue(any("not valid YAML" in p for p in problems), problems)

    def test_an_unparsable_python_block_is_caught(self):
        problems = self.broken_run("<!-- runnable: python -->\n```python\ndef broken(:\n    pass\n```\n")
        self.assertTrue(any("not valid Python" in p for p in problems), problems)

    def test_an_unparsable_ts_block_is_caught(self):
        # With the compiler installed the broken block is a syntax problem; without it the tool reports that the
        # marked example could not be checked. Either way the run fails and names the block: no skip, so the whole
        # suite stays "none skipped" wherever it runs.
        problems = self.broken_run("<!-- runnable: ts -->\n```ts\nconst x: = ;\n```\n")
        if (ROOT / "ts" / "node_modules" / "typescript").is_dir():
            self.assertTrue(any("not valid TypeScript" in p for p in problems), problems)
        else:
            self.assertTrue(any("has no typescript" in p for p in problems), problems)

    def test_invalid_json_is_caught(self):
        problems = self.broken_run("<!-- runnable: json -->\n```json\n{\"a\": }\n```\n")
        self.assertTrue(any("not valid JSON" in p for p in problems), problems)

    def test_a_marker_without_a_fence_is_caught(self):
        problems = self.broken_run("<!-- runnable: cli -->\n\nnot a fence\n")
        self.assertTrue(any("is not followed by a fenced block" in p for p in problems), problems)

    def test_an_unknown_kind_is_caught(self):
        problems = self.broken_run("<!-- runnable: bash -->\n```\ntrue\n```\n")
        self.assertTrue(any("unknown kind 'bash'" in p for p in problems), problems)

    def test_substitution_rewrites_the_published_command(self):
        text = ('<!-- runnable: cli subst="published-tool=true;other=false" -->\n```\npublished-tool demo\n```\n')
        self.assertEqual(self.broken_run(text), [])
        text = ('<!-- runnable: cli subst="published-tool=false" -->\n```\npublished-tool demo\n```\n')
        self.assertTrue(any("exited 1, expected 0" in p for p in self.broken_run(text)))

    def test_run_exits_1_on_a_problem_and_0_without(self):
        self.broken.write_text("<!-- runnable: cli -->\n```\nfalse\n```\n", encoding="utf-8")
        self.assertEqual(D.main(["--run", "--root", self.tmp, "--only", "examples/broken-for-the-test/README.md"]), 1)
        self.broken.write_text("<!-- runnable: cli -->\n```\ntrue\n```\n", encoding="utf-8")
        self.assertEqual(D.main(["--run", "--root", self.tmp, "--only", "examples/broken-for-the-test/README.md"]), 0)
        self.broken.write_text("no examples here\n", encoding="utf-8")
        self.assertEqual(D.main(["--run", "--root", self.tmp, "--only", "examples/broken-for-the-test/README.md"]), 1,
                         "a run that finds nothing to run is a failure, not a pass")


if __name__ == "__main__":
    unittest.main()
