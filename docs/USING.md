# Using x402-conformance from your stack

One suite, one set of check IDs, one report format, one corpus. Every entry point below is a thin way into the same
checks: a result from the CLI, the Action, vitest, jest or node:test means the same thing and has the same shape
([report schema](../corpus/report.schema.json)). None of them pays, signs or touches mainnet, and none of
them sends anything anywhere unless you ask it to.

- **What the checks are:** [README](../README.md#what-it-catches), with the spec text behind each in [SPEC.md](SPEC.md).
- **What to do when one fails:** [FIXES.md](FIXES.md). Every failure message links to its section.
- **The corpus:** [corpus](../corpus). Failures real stacks have shown, each one a regression case.
- **Contribute a case:** add `--share` (or `share: true`). You get an anonymised case file and a link to a pre-filled
  [issue form](https://github.com/atsp-protocol/x402-conformance/issues/new?template=corpus-case.yml). You review it and
  submit it yourself; nothing is sent for you.
- **Badge**, once you pass:
  `[![Tested with x402-conformance](https://img.shields.io/badge/tested%20with-x402--conformance-2ea44f)](https://github.com/atsp-protocol/x402-conformance)`

Every entry point names itself in the report's `via` field and in the User-Agent of the requests it makes
(`x402-conformance/<version> (+https://github.com/atsp-protocol/x402-conformance; via=<entry point>)`). That's the only
identifier: no machine or user ID, and no telemetry. It lets shared cases and committed reports be counted per
ecosystem. `runConformance` without `via` reports `testing`.

| entry point | `via` | install |
|---|---|---|
| [Command line](#command-line) | `cli-py`, `cli-ts` | `pipx run --spec x402-conformance x402conf`, `npx -y x402-conformance-svm` |
| [GitHub Actions](#github-actions) | `action` | `uses: atsp-protocol/x402-conformance@v1` |
| [vitest](#vitest) | `vitest` | `npm i -D x402-conformance-svm` |
| [jest](#jest) | `jest` | `npm i -D x402-conformance-svm` |
| [node:test and other runners](#nodetest-and-other-runners) | `node-test` | `npm i -D x402-conformance-svm` |
| [Hono, Express and other servers](#hono-express-and-other-servers) | any of the above | |
| [MCP: Claude, Cursor and other MCP clients](#mcp-claude-cursor-and-other-mcp-clients) | `mcp` | `npx -y x402-conformance-mcp` |
| [Vercel AI SDK](#vercel-ai-sdk) | `ai-sdk` | `npm i x402-conformance-mcp` |
| [LangChain and LangGraph](#langchain-and-langgraph) | `langchain` | `npm i x402-conformance-mcp` |
| [pytest (FastAPI, Flask, any Python server)](#pytest-fastapi-flask-and-any-python-server) | `pytest` | `pip install x402-conformance pytest` |
| [Docker](#docker) | `docker` | `docker run ghcr.io/atsp-protocol/x402-conformance:1` |
| [GitLab CI and other CI systems](#gitlab-ci-and-other-ci-systems) | `gitlab` | `include: remote: .../ts/ci/gitlab/x402-conformance.gitlab-ci.yml` |

## Command line

```
x402conf resource https://your.api/paid                              # P1-P7, one unpaid GET (Python)
npx -y x402-conformance-svm resource --url https://your.api/paid      # the same P1-P7, in Node
npx -y x402-conformance-svm probe --resource http://127.0.0.1:4020/paid --start "node server.js" --share
npx -y x402-conformance-svm probe --resource http://127.0.0.1:4020/paid --start "node server.js" --retry  # + R20
```

`x402conf resource --share` does the same in Python: one anonymised case file per URL, and the link for each failing
one. Both CLIs produce identical cases from the same report; CI checks both against
[one fixture](../corpus/fixtures).

The Node `resource` command is a port of the Python one with the same check IDs; CI runs both on 37 answers and
fails if they ever disagree. `--share` writes the case next to `--out`, with `.json` replaced by `.case.json` (or `./x402-conformance-case.json`
without `--out`), and prints the issue link when a check failed.

## GitHub Actions

See [the README](../README.md#github-action). The Action writes the same reports, plus SARIF for code scanning and
JUnit for test summaries.

## vitest

```ts
// x402.spec.ts
import { expect, test } from "vitest";
import { checkPaymentRequired, runConformance, x402Matchers, type X402Matchers } from "x402-conformance-svm/testing";
import { startMyServer } from "./server.js"; // takes a facilitator URL, returns { url, close }

declare module "vitest" { interface Assertion<T = any> extends X402Matchers<T> {} }
expect.extend(x402Matchers);

test("my paid route never serves before settlement", async () => {
  const report = await runConformance({ via: "vitest", start: (facilitatorUrl) => startMyServer(facilitatorUrl) });
  expect(report).toPassX402Conformance();
}, 120_000);
```

`runConformance` starts the facilitator double on loopback, calls your factory with its URL, runs R0-R10 against the
route it returns and closes everything. Your factory must use that URL as the server's facilitator and offer Solana
devnet or Base Sepolia on the route. A failure prints each failed check, its detail, its fix link, and how to share
it. [ts/vitest/x402.spec.ts](../ts/vitest/x402.spec.ts) is this quickstart, run in CI against stock `@x402/hono`.

To check only the unpaid answer: `expect(await checkPaymentRequired(url)).toBeValidX402Challenge()`.

## jest

The matchers follow the `expect.extend` contract vitest and jest share, so the vitest code works unchanged with
`import { expect, test } from "@jest/globals"` and `via: "jest"`. CI runs them in vitest and node:test, not jest.

## node:test and other runners

```ts
import { test } from "node:test";
import { assertX402Conformance, runConformance, saveReport } from "x402-conformance-svm/testing";

test("x402", async () => {
  const report = await runConformance({ via: "node-test", start: (f) => startMyServer(f) });
  saveReport(report);                 // ./x402-conformance/*.json, or X402CONF_REPORT_DIR
  assertX402Conformance(report);      // throws with the same message the matchers print
});
```

`saveReport(report, { share: true, stack: { framework: "hono", sdk: "@x402/hono", sdk_version: "2.28.0" } })` also
writes the anonymised case and returns the issue link.

## Checks you call from code

Since 1.5.0, `x402-conformance-svm` also exports R12, R13, R15, R16, R16a, R22, R23 and R24 for your server and C1,
C2 and C3 for your client, as functions. The CLIs, the Action, `runConformance`, the pytest plugin and the MCP server
don't run them, so call them from your own test. Each one takes the facilitator double from `startDouble()`, except
`probeUnpaidHead`, and your server or client must use the double's `url` as its facilitator:

```ts
import { explain, makeReport, probeHead, probeMalformedHeader, probeUnpaidHead, startDouble } from "x402-conformance-svm";

const double = await startDouble(0);
const server = await startMyServer(double.url); // takes a facilitator URL, returns { url, close }
const results = [
  ...(await probeUnpaidHead(server.url)),              // R16a
  ...(await probeHead(server.url, double)),            // R16
  ...(await probeMalformedHeader(server.url, double)), // R24
];
await server.close();
await double.close();
const report = makeReport("resource-server", server.url, results, "library");
if (report.summary.failed) throw new Error(explain(report));
```

The others take the same double: `probeParallel(url, double)` (R12), `probeReplicas(urlA, urlB, double)` (R13, one
route on two replicas), `probeDelivery({ error, redirect, throws }, double)` (R15, routes that answer 5xx, redirect and
throw), `probeStatus(routes, double)` (R22, routes by name, each `{ url, status, headers? }`) and `probeAbort(url,
double)` (R23). A client check takes your client as a function that fetches a URL, pays and returns the final
`Response`, and returns one result: `checkClientHandles402(client, url, double)` (C1), `checkClientOfferPolicy(client,
url, double, { networks, maxAmount })` (C2) and `checkClientKeepsV2(client, url, double)` (C3). The
[README](../README.md#what-it-catches) says what each one checks.

## Hono, Express and other servers

Any server works if its facilitator URL comes from configuration. CI runs the stock `@x402/hono`
([example](../ts/example/hono-server.ts)) and `@x402/express` ([example](../ts/example/express-server.ts)) middleware
through `runConformance` on Solana devnet and Base Sepolia, and both pass. For a server you can't start in-process,
use the CLI's `--start` or the Action.

## MCP: Claude, Cursor and other MCP clients

```json
{ "mcpServers": { "x402-conformance": { "command": "npx", "args": ["-y", "x402-conformance-mcp"] } } }
```

Seven tools: `x402_check_payment_required` (P1-P7), `x402_demo` (P1-P7 and R0-R10 on a built-in demo server, no wallet),
`x402_start_facilitator_double`, `x402_probe_resource_server` (R0-R10, loopback only) and
`x402_stop_facilitator_double`, `x402_explain_check` (the FIXES.md section) and `x402_share_case` (an anonymised case
and the issue link; it sends nothing). Listed in the MCP registry as `io.github.atsp-protocol/x402-conformance`. CI
drives the server over real stdio with the MCP SDK client. [ts/mcp/README.md](../ts/mcp/README.md) has the details.

## Vercel AI SDK

```ts
import { x402ConformanceTools } from "x402-conformance-mcp/ai-sdk";
await generateText({ model, tools: x402ConformanceTools(), prompt: "Is the 402 answer at https://api.example.com/paid valid?" });
```

An agent gets the four read-only tools: check, demo, explain and share. A pre-flight `x402_check_payment_required`
before paying an unfamiliar endpoint is the common use. CI runs a tool call through `generateText` with a mock model.

## LangChain and LangGraph

```ts
import { x402ConformanceTools } from "x402-conformance-mcp/langchain";
const agent = createReactAgent({ llm, tools: x402ConformanceTools() });
```

The same four tools as LangChain `StructuredTool`s, which also work in LangGraph agents.

## Docker

One image with the Python CLI, the Node probe and the MCP server (Node 22, Python 3):

```
docker run --rm ghcr.io/atsp-protocol/x402-conformance:1 x402conf resource https://your.api/paid
docker run --rm -v "$PWD:/work" ghcr.io/atsp-protocol/x402-conformance:1 \
  x402conf-svm probe --resource http://127.0.0.1:4020/paid --start "node server.js"
docker run -i --rm ghcr.io/atsp-protocol/x402-conformance:1            # no arguments: the MCP server on stdio
docker run --rm ghcr.io/atsp-protocol/x402-conformance:1 help
```

The image sets `X402CONF_VIA=docker`. It's built from [ts/docker/Dockerfile](../ts/docker/Dockerfile), and CI builds
it and runs every one of these against the reference and a faulty server.

## GitLab CI and other CI systems

```yaml
include:
  - remote: https://raw.githubusercontent.com/atsp-protocol/x402-conformance/v1/ts/ci/gitlab/x402-conformance.gitlab-ci.yml
x402-conformance:
  variables:
    X402_RESOURCE_URL: http://127.0.0.1:4020/paid   # your paid route
    X402_START: node server.js                      # must use X402_FACILITATOR_URL as its facilitator
```

The job runs `x402-conformance ci` in the image and publishes JUnit to the merge request. The same command works in
any CI system that runs containers (Jenkins, CircleCI, Buildkite, Bitbucket, Drone); it reads `X402_RESOURCE_URL`,
`X402_START`, `X402_RESOURCES`, `X402_NETWORK`, `X402_PORT`, `X402_RESULTS_DIR` and `X402_SHARE`, and
`docker run ... help` lists them. Results land in `x402-conformance/` with `junit.xml` and SARIF. CI runs the
template's script inside the image, as GitLab would, against a passing and a faulty server.

## pytest: FastAPI, Flask and any Python server

Installing `x402-conformance` registers a pytest plugin, so any suite gets the `x402` fixture:

```python
def test_my_402_answer(x402):
    x402.assert_passed(x402.check_payment_required("http://127.0.0.1:8000/paid"))      # P1-P7, in Python

def test_never_serves_before_settlement(x402):
    report = x402.probe("http://127.0.0.1:4020/paid", start="uvicorn app:app --port 4020")  # R0-R10
    x402.assert_passed(report)
```

`probe` runs the Node probe (the command in `X402CONF_SVM` if it is set, else `x402conf-svm` on PATH, else
`npx -y x402-conformance-svm` at the plugin's own version), which starts the facilitator double
and your server with `X402_FACILITATOR_URL`; your app must use it as its facilitator. A failed check fails the test
with its detail and fix link. `--x402-report-dir DIR` keeps every report, and `--x402-share` writes anonymised cases
and lists the links to submit them in the terminal summary. Nothing is sent. CI runs the plugin against the stock
x402 Python SDK's FastAPI middleware ([example](../examples/python/fastapi_server.py)), which passes R0-R10 on Solana
devnet, and against a faulty server, which fails.
