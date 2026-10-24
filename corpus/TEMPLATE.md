# Corpus case template

An accepted case is one JSON file in `corpus/cases/`, named `<date>-<check ids>-<stack>.json`, for example
[2026-10-22-R14-x402-core.json](cases/2026-10-22-R14-x402-core.json), shown below with its results cut. It is the anonymised case the submitter shared (`x402-conformance.case/1`, see
[case.schema.json](case.schema.json)) plus a `regression` block that proves the suite catches it:

```json
{
 "schema": "x402-conformance.case/1",
 "tool_version": "1.3.1",
 "via": "cli-ts",
 "kind": "resource-server",
 "target": "loopback",
 "stack": { "framework": "node:http", "sdk": "@x402/core", "sdk_version": "2.28.0", "network": "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1", "language": "typescript" },
 "failed_ids": ["R14"],
 "results": [ "... as shared, unchanged ..." ],
 "regression": {
  "control": "ts:R14 control: a server with a durable idempotency record passes",
  "faulty": "ts:R14 catches a server whose idempotency record is in memory only",
  "expect_failed": ["R14"],
  "issue": "https://github.com/atsp-protocol/x402-conformance/pull/17",
  "reproduced_on": "ts/example/crash-server.ts on @x402/core 2.28.0 and @x402/svm 2.28.0 with CRASH_FAULT=memory_record"
 }
}
```

## The regression block

| Field | What it holds |
|---|---|
| `control` | What passes: `reference` (the Python reference facilitator double), or `ts:<test name>` for a TypeScript test that runs the stock stack and passes. |
| `faulty` | What fails, one of: `fault:<name>` (a double in `src/x402conf/mock.py` FAULTS), `guard:<name>` (a guard in `harness.GUARD_FAULTS`), `answer:<file>` (a recorded 402 answer under `corpus/answers/`, with `status`, `headers` and `body`), or `ts:<test name>` (a TypeScript test against a faulty build). |
| `expect_failed` | The check IDs the faulty build must fail. A subset of `failed_ids`. |
| `issue` | The corpus-case issue, or the pull request, it came from. |
| `reproduced_on` | The pinned version or the double it was reproduced against. |

`tests/test_offline.py` (`test_corpus_cases_are_complete_and_pass`) checks every file: that `schema` is
`x402-conformance.case/1`, that every id in `failed_ids` is a catalogue check, that `control` is set and that
`expect_failed` is a non-empty subset of `failed_ids`. For a `fault:`, `guard:` or `answer:` build it runs the build and
checks that it still fails `expect_failed`; for a `fault:` build whose `control` is `reference` it also runs the
reference and checks that it fails none of them. For a `ts:` build it checks only that the test name appears in
`ts/test/`; `npm test` in `ts/` runs that test in CI. It does not validate the file against
[case.schema.json](case.schema.json), which allows no `regression` field. A case that stops reproducing
fails CI, which is the point.

## Before a case is accepted

1. It reproduces against a deliberately faulty double or a pinned version of the named stack.
2. It contains nothing identifying: no URLs, hosts, IPs, addresses or transaction data (the anonymiser removes them;
   read it again anyway).
3. If the failure could put someone's money at risk, it goes through private disclosure first (SECURITY.md), and the
   case is added only after the fix is public.
