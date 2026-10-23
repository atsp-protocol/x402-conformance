# Contributing

Thanks for helping. This project is experimental. Review happens in the open, through issues, pull requests and
[Discussions](https://github.com/atsp-protocol/x402-conformance/discussions).

- **Questions, ideas and results.** Start in Discussions: how to run it against your stack, a check you'd like, or a
  result you want to share. Good ideas become check proposals.
- **A check flagged something you believe is right?** Open a false positive report and quote the spec text. False
  positives get fixed first.
- **Want your facilitator in the results?** Use the "Add my facilitator to the results" issue form.

- **New checks.** Open an issue with the "check proposal" template. Quote the exact x402 spec text and its section. Every check needs a test that fails against a faulty double and passes against the reference.
- **[Proofline](https://github.com/Optitransfer/proofline).** Scope and acceptance criteria live in `proofline.json`. A pull request that adds work outside every task's scope fails the `vv` job. Contract changes are proposed in a PR, and the owner re-signs them.
- **Before you push,** run the local checks:

      pip install ruff==0.7.4 mypy==1.13.0
      ruff check . && mypy && PYTHONPATH=src python -m unittest discover -s tests
      (cd ts && npm ci && npm test)
      (cd ts/mcp && npm ci && npm test)
      (cd lean && lake build) && python3 tools/lean_axioms.py
      python3 tools/interdeps.py && python3 tools/interdeps.py --drift   # regenerate docs/INTERDEPENDENCY.md, then check the docs match the code
      python3 tools/vv.py verify --pre-merge     # on a branch; plain `verify` is the strict run on main

  CI runs the Python tests on 3.10, 3.12 and 3.13 and the TypeScript tests on Node 20, 22 and 24.

- Never commit keys, tokens or wallet material. Devnet keypairs are throwaway, live outside the repository and are never committed.
- Contributions are accepted under Apache-2.0, the licence of this repository.
- By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
