# The x402 failure corpus

Every failure the suite has found in a real stack, or reproduced on a stock SDK build, that someone chose to share. Each case is an anonymised
`x402-conformance.case/1` file: the check IDs, the status of every check, the shape of the failing answer, the tool
version, the entry point it came through (`via`) and the stack its submitter named. No URLs, hosts, IPs, addresses or
transaction data.

## How a case gets here

1. A run fails, in any entry point: the CLIs, the Action, the vitest or jest matchers, node:test, pytest, the MCP server,
   the agent tools or the Docker image. They report the same check IDs under `schema: x402-conformance.report/1`
   ([report.schema.json](report.schema.json)). The JSON that `x402conf-svm probe` prints and writes with `--out` lacks
   the schema's required `version` and `target`, and the JSON of `x402conf-svm resource` lacks `version` and names its
   results `checks`, so neither validates against it; the case that `--share` writes is built from the full report.
2. Its owner opts in: `--share` on `x402conf resource`, `x402conf-svm probe` and `x402conf-svm resource`, `--x402-share`
   with pytest, `X402_SHARE=true` for the Docker image's `ci` run, `saveReport(report, { share: true })` in tests, or
   the `x402_share_case` tool (MCP, the AI SDK and LangChain). The CLIs, pytest and the image write the anonymised case
   ([case.schema.json](case.schema.json)) and print a link to the pre-filled
   [corpus case form](https://github.com/atsp-protocol/x402-conformance/issues/new?template=corpus-case.yml);
   `saveReport` returns the case path and the link, and `x402_share_case` returns both in its answer. The Action has no
   share input. Nothing is ever sent automatically.
3. I reproduce it. A case is accepted once it reproduces against a deliberately faulty double or a pinned version of the
   named stack, and it's committed in `cases/` as `<date>-<check ids>-<stack>.json` with a regression block that
   proves the suite catches it. The format is in [TEMPLATE.md](TEMPLATE.md).

## Why it matters

A check is only as good as the failures it has caught. The corpus is the record of failures real x402 stacks have shown or stock builds have reproduced,
and every accepted case becomes a test that every later run of the suite carries.

## Cases

- [2026-10-22-R14-x402-core.json](cases/2026-10-22-R14-x402-core.json): R14, recorded with `x402conf-svm` 1.3.1. A
  `node:http` server on `@x402/core` 2.28.0 (Solana devnet) whose idempotency record is a Map in memory settles the same
  payment again after a crash and a restart. I added it with the R14 check in pull request #17. It reproduces on
  [ts/example/crash-server.ts](../ts/example/crash-server.ts) with `CRASH_FAULT=memory_record`, on `@x402/core` and
  `@x402/svm` 2.28.0, and the control and the faulty run are tests in [ts/test/delivery.test.ts](../ts/test/delivery.test.ts).
- [2026-10-23-R20-express.json](cases/2026-10-23-R20-express.json): R20a and R20b, recorded with `x402conf-svm` 1.4.0
  from `probe --retry --share` against a stock `@x402/express` 2.28.0 server (Solana devnet) with no idempotency
  record, which settles a fresh-payment retry a second time. It reproduces on
  [ts/example/retry-server.ts](../ts/example/retry-server.ts) with `RETRY_FAULT=settle_both`; the control is the same
  server with an idempotency record (pull request #19).
