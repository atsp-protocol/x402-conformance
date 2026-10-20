# Contributing

Thanks for helping. This project is experimental. Review happens in the open, through issues and pull requests.

- **New checks.** Open an issue with the "check proposal" template. Quote the exact x402 spec text and its section. Every check needs a test that fails against a faulty double and passes against the reference.
- **[Proofline](https://github.com/Optitransfer/proofline).** Scope and acceptance criteria live in `proofline.json`. A pull request that adds work outside every task's scope fails the `vv` job. Contract changes are proposed in a PR, and the owner re-signs them.
- **Before you push,** run the local checks:

      pip install ruff==0.7.4 mypy==1.13.0
      ruff check . && mypy && PYTHONPATH=src python -m unittest discover -s tests
      (cd lean && lake build && lake env lean Axioms.lean)
      python3 tools/vv.py verify

- Never commit keys, tokens or wallet material. Devnet keypairs are throwaway, live outside the repository and are never committed.
- Contributions are accepted under Apache-2.0, the licence of this repository.
- By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
