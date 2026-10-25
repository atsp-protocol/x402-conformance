# Roadmap

**Where it stands.** 1.6.0 is the current release (2026-10-24), and it is still marked experimental. S0 to S4 check
a facilitator's `GET /supported`; S5 and F1 to F14 run against fault-injected facilitator doubles (and F1 to F6 over
real `/verify` and `/settle` on Solana devnet); P1 to P7 check any paid URL's 402 answer with one unpaid GET; R0 to R10,
R14 and R20 put a misbehaving facilitator in front of your own paid route on Solana devnet or Base Sepolia from the CLI
and the Action, R11 and R11a to R11f check payment-to-request binding on that route, and R12, R13, R15 to R19, R16a and
R22 to R24 run from code; C1 to C3 grade a client; and
the Lean models cover the credit rule, nonces, timeouts, `settlement_pending` and concurrent settles. There are no
public users yet. [RELEASES.md](RELEASES.md) lists every release and what it added.

**What 1.6.0 shipped, and what is next.** 1.5.0 (2026-10-23) added thirteen checks (S5, F12, R12, R13, R15, R16, R16a,
R22, R23, R24, C1, C2 and C3), the generated interdependency map with the docs-versus-code gate, the n-replica Lean
models (XC-24) and the R20 corpus case (XC-22). 1.6.0 closes the release task XC-48: R17 to R19 (XC-18), the
implementation matrix (XC-19), the framework quickstarts (XC-26), docs examples run by CI (XC-27), the compatibility
matrix (XC-28), the mutation matrix with the false-positive register (XC-29), and two facilitator checks built from a
public reviewer's comment, F13 for asset substitution (XC-49) and F14 for network substitution (XC-50); each new check
has a passing control and a faulty build it catches. Next are XC-32 to XC-37 under
[Later](#later-breadth-once-the-depth-is-there) and the release gate below.

**Where it's going.** Having many checks is not the same as covering the security boundary that matters. The question
a seller actually needs answered is: *does this payment authorise this request, is what was bought actually
delivered, and does my stack recover safely when the payment and the HTTP exchange disagree?* The next two releases
are about answering that with evidence, in three adversarial test families, in this order:

1. **Payment-to-request binding** (v1.4): a payment for one route, price, recipient or method never unlocks another.
2. **Concurrency and idempotency** (v1.5): one payment is one grant, across parallel requests, several replicas and a
   crash between settling and serving.
3. **Payment versus delivery** (v1.5): a settled payment never ends in nothing delivered, and a failed delivery never
   ends in a settled payment, with an explicit outcome for timeouts, `HEAD`, redirects, errors and caches.

This is an open-source code project: the checks, the doubles, the CLIs and the Action. The aim is a suite that
x402 developers actually run, in every repo and on every change, so adoption is built into the code alongside the
checks ([Adoption track](#adoption-track-built-into-the-code)).

Everything on this page is my proposal. It's open for review in issues and Discussions, and dates are targets, not
promises.

## How I decide what goes in

A check is added only when it meets all of these. This is the quality bar, and it applies to every item below.

- **A spec basis or a named failure class.** Either it quotes the x402 text it rests on, or it names a reproduced,
  public failure class and says plainly that the spec is silent.
- **A legitimate control that passes.** A stock, correctly configured implementation (the reference facilitator, a
  stock `@x402/express` server and so on) runs green.
- **A deliberately faulty implementation that it catches.** Each check ships with at least one faulty build that
  reproduces the failure, and CI proves the check fails against it. A check that can't fail isn't a check.
- **Reproducible evidence.** Pinned versions, lockfile hashes, the raw exchange and a hash of the results, so anyone
  can rerun it and get the same answer.
- **No financial risk.** Loopback doubles, local chains and testnets only. The suite never signs a real payment,
  never pays and never touches mainnet.

### Three profiles, reported separately

From v1.4, every check carries one of three classifications, and results, SARIF and the job summary report them
separately. Passing one profile says nothing about the others.

| profile | what it means | example |
|---|---|---|
| **normative** | The x402 spec, a transport spec or an extension spec says MUST or REQUIRED, and the check quotes it | `/verify` must not commit payment state (V2 §7.1) |
| **security profile** | The spec is silent or permissive, but a public, reproduced failure shows that a seller loses money or a buyer pays for nothing | a paid route must not be reachable through an encoded path separator |
| **resilience** | Interoperability and recovery under real-world limits and faults | a `PAYMENT-REQUIRED` header small enough for common HTTP clients to read |

A security-profile or resilience failure is not a spec violation, and the report says so.

## v1.4: binding and a trustworthy oracle (1.4.0 released 2026-10-22; the v1.4 parts of A4, A7 and A8 moved to 1.6.0)

### P0. The suite's own oracle fails closed

The reference verifier in `mock.py` parses amounts with Python's `int()`. On malformed input it raises
(`ValueError`, `TypeError`, `OverflowError`) instead of returning a rejection, and it is lenient where x402 is not:
it accepts surrounding whitespace, non-ASCII digits, booleans and floats (truncated), and it does not reject a
negative or zero price in the requirements. An oracle that crashes or accepts what a strict verifier would refuse makes
every check that depends on it weaker.

- **Change:** one strict atomic-unit parser (`^(0|[1-9][0-9]{0,77})$` as a JSON string, fitting uint256) used by every
  double, the harness and the TypeScript probe; any other input is a clean `invalid_payload` or
  `invalid_payment_requirements`, never an exception. A requirement amount must be positive.
- **Spec basis:** V2 §5.1.2, `amount` is a string in atomic token units.
- **Control:** every existing vector still passes. **Faulty build:** a `lenient_amounts` double using `int()`.
- **Test:** a table of malformed amounts (`"abc"`, `null`, `"1e6"`, `" 10 "`, full-width digits, `true`, `1.5`,
  `"-5"`, a 79-digit number) on both the payload and the requirements: the reference returns a rejection for every
  one, and the faulty double is caught.
- **Profile:** normative.

### P0. R11: a payment for one route never unlocks another (real routes, end to end)

F10 proves cross-request replay is refused at the facilitator boundary, but only on the in-process double, and the
resource substitution it tests is not what happens on the wire: F10 adds a `resource` field to `PaymentRequirements`,
and V2 `PaymentRequirements` has no such field. In V2 the resource travels separately, as `PaymentPayload.resource`,
which is optional and set by the client (§5.2.2), so a facilitator can't bind a payment to a route at all. The binding
has to happen in the resource server, and that's where it needs to be tested.

R11 runs against a real resource server with **two routes at different prices**, behind the facilitator double, and
grades each substitution separately. The double accepts any well-formed payment, so every rejection it sees has to come
from the server's own matching.

| sub-check | the attempt | must happen | profile |
|---|---|---|---|
| R11a | a payment built for the cheap route's `accepts` presented on the expensive route | 402, and no `/settle` | normative (V2 §5.2.2: `accepted` is the requirements chosen; the server matches it against its own) |
| R11b | the payment's recipient (`payTo`), asset or network altered | 402 before any `/settle` | normative (V2 §5.1.2, §9 recipient and amount mismatch codes) |
| R11c | a payment for `GET` presented with another method on a route priced differently by method | 402, and no `/settle` | security profile |
| R11d | the same path with a different query string, on a route priced by query or by dynamic price | priced for the request actually made | security profile |
| R11e | an unpaid request to a parameterised paid route with an encoded separator or dot segment (`%2F`, `%5C`, `%2e%2e`, double encoding) | 402, not content | security profile: the payment middleware and the web framework must agree on the path. Public reports show this mismatch in more than one x402 implementation |
| R11f | with the sign-in-with-x extension: pay the cheap route while `PaymentPayload.resource.url` names the expensive one, then present only a SIWX header on the expensive route | 402: the access record belongs to the route that was priced and settled | security profile, SIWX spec ("has previously paid for the requested resource"). Upstream: [x402#3838](https://github.com/x402-foundation/x402/issues/3838), open, fix proposed in [x402#3840](https://github.com/x402-foundation/x402/pull/3840) |
| control | a correct payment on each route | served once, with `PAYMENT-RESPONSE` | – |

- **Faulty builds** (modes of `ts/example/binding-server.ts`): `trust_client` verifies and settles against the
  requirements the client says it accepted, and fails R11a to R11d; `decoded_match` matches paid routes on the decoded
  path while Express routes on the raw one, and fails R11e; `refuse_paid` never serves a paid request, and fails the
  R11 control. For R11f, the stock `@x402/extensions` 2.28.0 sign-in-with-x hook records access under the payload's
  `resource.url`, and fails. The stock `@x402/express` server passes.
- **F10 is narrowed** to what a facilitator can actually enforce (amount, asset, recipient and network in the
  requirements set a transaction was verified under), and its docs say resource binding is R11's job.
- **R11f's expectation** is pinned to the upstream outcome. If upstream settles on a different rule, R11f follows the
  spec and the change is recorded in the changelog.

### P1. Cheap normative checks the spec already supports

| check | what | spec basis | faulty build | where |
|---|---|---|---|---|
| F5, extended | a `settlement_pending` answer carries a non-empty `network` as well as the `transaction` F5 already requires, and a faulty double that drops them proves F5 can fail | V2 §9: "MUST carry a non-empty `transaction` … and `network`" | a double that returns pending with no hash or network | offline, devnet, and the probe's double |
| F11 | `/verify` is read-only: verifying twice, then settling, still settles once, and verify alone consumes nothing | V2 §7.1: `/verify` "MUST NOT commit payment state" | a double whose verify burns the nonce | offline, devnet |
| P6 | the encoded `PAYMENT-REQUIRED` header fits common client limits: warning above 8 KB, error above 16 KB | resilience: the spec sets no budget. Upstream [x402#3803](https://github.com/x402-foundation/x402/issues/3803), open: Node's fetch fails above 16 KB of headers and aiohttp above about 8 KB | a fixture with a large discovery extension | `resource`, read-only |
| P7 | a 402 whose resolved payment flow isn't `authorization` declares `extra.paymentFlow` | V2 §6.1: it "MUST be present" | a fixture that omits it | `resource`, read-only |

### P1. Evidence and test credibility

- **Every result carries** its profile, spec basis, upstream reference, the faulty builds that check is known to
  catch, the versions under test and a lockfile hash. `report` adds the profile to SARIF and the JUnit names.
- **A credibility gate in CI:** a test fails the build if any check has no passing control or no faulty build it
  catches. The mutation matrix (check × faulty build) is published on the project page.
- **False positives:** each one gets a public issue, a fix or a documented exception, and a regression test.
- **README and SPEC.md** list F10, F11, P6, P7 and R11 with the profile of each.

**v1.4 is done when** R11a to R11f catch their faulty builds and the stock server passes on Solana devnet and Base
Sepolia, the oracle survives the malformed-amount table, the extended F5, F11, P6 and P7 ship with controls and faulty builds, and
the credibility gate is green, and A1, A2, A3, A5, A6 (seeded) and the v1.4 parts of A4, A7 and A8 ship with it.

## v1.5: concurrency, delivery and an implementation matrix (1.5.0 released 2026-10-23 with R12, R13, R15, R16, R16a, R22 to R24 and the n-replica Lean models; R17 to R19 and the matrix released in 1.6.0)

### P0. One payment, one grant

R2 today presents the same payment twice, one after the other. Real failures happen in parallel and across
processes: a public study ([Five Attacks on x402](https://arxiv.org/abs/2605.11781)) reports one payment reused for
hundreds of grants where the server did not record the payment identity atomically before releasing the resource.

| check | the attempt | must happen | profile |
|---|---|---|---|
| R12 | the same payment-identifier id sent as eight parallel requests to one server (the `parallel` option, at least 2), each with a fresh payment | at most one successful `/settle`, at least one request served, and every served answer names that settlement | security profile; **delivered**: `probeParallel`, Solana devnet and Base Sepolia |
| R13 | the same payment-identifier id sent to two replicas, to one, then the other, then both at once, with a fresh payment each time | charged at most once in all, and every served answer names that settlement | resilience: no spec text requires a record shared across replicas; **delivered**: `probeReplicas`, Solana devnet and Base Sepolia |
| R14 | the server is killed after `/settle` succeeds and before the response is written, restarted, and the payment presented again | no second settlement, no second charge, and a defined outcome: delivered once via an idempotency record, or refused with the transaction surfaced for reconciliation | resilience; **delivered**: `x402conf-svm probe --crash`, Solana devnet and Base Sepolia |
| R20 | the client times out before `/settle` answers and retries the same request. R20a: the retry carries a fresh payment and the same idempotency key (the `payment-identifier` id, or the server's documented request key). R20b: the retry reuses the same signed payment | R20a: no second charge; the server returns the earlier result or settlement reference. R20b: `/settle` refuses the duplicate and the original result comes back; a client that re-signs a fresh payment for the same request without a key is flagged | security profile. A retry after a timeout, reported publicly by a user, paid twice for one request; **delivered**: `x402conf-svm probe --retry`, Solana devnet and Base Sepolia |

- **Faulty builds:** a per-process in-memory cache (fails R13), a check-then-set without atomicity (fails R12 under
  parallel load), a server that settles again after a restart (fails R14), a server that settles both the original and
  a fresh retry payment or keys its record by payment instead of by request (fails R20a), and a client that re-signs on
  timeout (fails R20b).
- **R14 delivered.** The probe kills the server at two points (while `/settle` is answering, and as the response
  starts), restarts it and presents the same payment. The control is `ts/example/crash-server.ts`, with a durable
  record; its `memory_record`, `record_after_settle` and `refuse_silent` builds each fail (`ts/test/delivery.test.ts`).
  The contract task for it is XC-21.
- **Lean:** extend the settlement model to n replicas, and prove that a shared atomic check-and-set admits at most one
  grant while partitioned caches admit more. As with today's models, this proves the rule, not anyone's code.
  **Delivered** in 1.5.0: `lean/X402Conformance/Replicas.lean` (XC-24).

### P1. Payment versus delivery

V2 §6.1 says that in the default `authorization` flow "funds move only after it completes successfully". That makes
most of this family normative.

| check | the attempt | must happen | profile |
|---|---|---|---|
| R15 | the paid handler fails (5xx), redirects (3xx) or throws | no `/settle`; nothing is charged | normative (V2 §6.1); **delivered**: `probeDelivery` |
| R16 | `HEAD` on a paid `GET` route, carrying a payment | not settled: a 402 telling the client to retry as `GET`, and zero `/settle` calls | security profile (RFC 9110 §9.3.2: a `HEAD` response carries no content). Upstream [x402#3810](https://github.com/x402-foundation/x402/issues/3810), open, fix proposed in [x402#3813](https://github.com/x402-foundation/x402/pull/3813); **delivered**: `probeHead` (R16) and `probeUnpaidHead` (R16a, an unpaid `HEAD` gets the same 402 as `GET`) |
| R17 | a paid response, then an unpaid request for the same URL through a loopback caching proxy | the unpaid request gets 402; paid responses are marked `Cache-Control: private, no-store` or vary on the payment header | security profile ([Five Attacks on x402](https://arxiv.org/abs/2605.11781), cache leakage); **delivered** in 1.6.0: `probeCacheLeak` |
| R18 | `settlement_pending`, then success on the retry; pending until the deadline; success after the server timed out | the outcome is explicit and reconcilable: served once after the payment is final, or refused with the transaction hash surfaced, never served twice | resilience. The Base timeout race in [x402#1062](https://github.com/x402-foundation/x402/issues/1062) is closed upstream through `settlement_pending` and one automatic settle retry; R8 already covers "not served while pending", and R18 covers the recovery path; **delivered** in 1.6.0: `probePending` |
| R19 | for routes using an `upfront` or `escrow` flow | the resource never executes before a check has run, and an unsupported flow is rejected | normative (V2 §6.1: "at least one check … MUST run before the resource executes"; servers "MUST reject unsupported" combinations); **delivered** in 1.6.0: `probeFlows` |
### Built beyond this plan

| check | what | profile | contract task |
|---|---|---|---|
| S5 | every kind `/supported` advertises gets a structured `/verify` answer | normative | XC-47, proposed |
| F12 | `/verify` rejects an unsupported network or an asset with no token contract | security profile | XC-46, done |
| F13 | `/verify` rejects a payment in a different asset at the quoted amount and recipient | security profile | XC-49, done in 1.6.0 |
| F14 | `/verify` rejects a payment authorized for another network when amount, recipient and asset match | security profile | XC-50, done in 1.6.0 |
| R16a | an unpaid `HEAD` on a paid `GET` route gets the same 402 as `GET` | security profile | XC-39, done |
| R22 | the paid response keeps the handler's 2xx status and headers | normative | XC-40, done |
| R23 | a client abort during settle is recoverable | security profile | XC-41, done |
| R24 | a malformed payment header gets a 4xx, never a 5xx | resilience | XC-42, done |
| C1 | a client never treats a 402 as success | security profile | XC-43, done |
| C2 | a client pays an offer within its own policy | security profile | XC-44, done |
| C3 | a client pays V2 and never falls back to V1 when a V2 offer is present | security profile | XC-45, done |

### P1. Implementation matrix

The probe speaks HTTP, so it can grade any stack. v1.5 runs it in CI against the stock example servers I can build
and pin: TypeScript (`@x402/express`, `@x402/hono`, `@x402/next`), Python (FastAPI, Flask) and Go (gin), at pinned SDK
versions, on Solana devnet and Base Sepolia. The matrix is published in [MATRIX.md](MATRIX.md) with one row per stack and
version. A failing row on a stock server becomes a coordinated report to the maintainers first, under
[SECURITY.md](../SECURITY.md), and a public row only once it's fixed or the disclosure window has passed. A server
that can't start (for example, a Go server registering a scheme for `eip155:*`, upstream
[x402#3861](https://github.com/x402-foundation/x402/issues/3861)) is reported as a setup failure with the reason, not
as a pass or a security failure.

**v1.5 is done when** R12 to R20 catch their faulty builds, the stock TypeScript server passes them, and the matrix has
at least five stack-and-version rows with pinned, hashed evidence, regenerated in CI (A7), and the FastAPI, Flask and
Go quickstarts (A4) are green.

## XC-51: self-hosted open-source facilitators as matrix columns (proposed)

| task | acceptance |
|---|---|
| XC-51 `x402conf devnet --facilitator http://127.0.0.1:<port>` on Base Sepolia (`eip155:84532`): the F checks that need only `/verify`, over real `/verify` against any loopback facilitator, with throwaway keys and no `/settle` | each launchable self-hosted facilitator in [MATRIX.md](MATRIX.md#self-hosted-open-source-facilitators) has an evidence folder with `run.json` and `SHA256SUMS`; a failing row says "under disclosure" until SECURITY.md's window clears; nothing off loopback is called |

## Later: breadth, once the depth is there

Each of these lands only when it can be tested as thoroughly as `exact` is today.

- **The MCP transport** (`specs/transports-v2/mcp.md`): a read-only check of a paid tool's payment-required answer,
  then fault injection on paid tool calls. The upstream Python MCP tests are not run by CI today
  ([x402#3793](https://github.com/x402-foundation/x402/issues/3793)), so independent coverage here is useful.
- **Settlement preemption** for caller-unbound settlement (Permit2 on EVM), from the same study.
- **The `upto` and `batch-settlement` schemes**, then A2A and discovery (Bazaar) checks.
- **SIWX normative checks**: domain and `uri` origin from the server's configuration, never from `Host`; nonce
  uniqueness; `issuedAt` and expiry windows.

## Adoption track: built into the code

A check only protects anyone if it gets run. These items make the suite fast to try, easy to keep in CI and easy to
contribute to. The v1.4 items ship with v1.4, because they decide whether anyone runs R11.

| id | what | done when | release |
|---|---|---|---|
| A1 | **Zero-config one-liners.** `npx -y x402-conformance-svm demo` and `pipx run --spec x402-conformance x402conf demo` start a local mock target (a bundled x402 V2 resource server on `@x402/core` behind the facilitator double on loopback for the Node demo; a bundled mock facilitator and paid route for the Python demo), run the checks and print the results | under 60 s on a laptop or a GitHub-hosted runner, with no wallet, keys, funds or network beyond the package download; tested in CI | v1.4 |
| A2 | **A 3-line GitHub Action**, with a PR summary comment and SARIF | `uses:` plus `resource-url` and `start` is a complete job; an opt-in sticky comment on the pull request lists what failed, with the fix hint for each; SARIF lands in code scanning as it does today | v1.4 |
| A3 | **Friendly failure messages.** Every failed check prints one line saying what failed, the likely cause and the fix, with a link to its [FIXES.md](FIXES.md) entry | a test fails the build if any check id has no fix hint | v1.4 |
| A4 | **Framework adapters and quickstarts.** A minimal paid route plus the workflow file, per framework, each run in CI: Express, Hono and Next first; FastAPI, Flask and Go next | each quickstart goes from clone to a first result in under 5 minutes, and its CI job is green | Express, Hono, Next in v1.4; FastAPI, Flask, Go in v1.5 |
| A5 | **Copy-paste badge.** `x402conf report --badge` writes a shields.io endpoint file from your results, next to the static "tested with" badge | the badge reflects the last run and still says "tested with", never "certified" | v1.4 |
| A6 | **A public, versioned regression corpus.** One directory per case under `corpus/`: the scenario, the check, the profile, the spec basis or upstream issue, a passing control, a faulty build and the expected outcome, at pinned versions | a case template and an issue form let anyone propose a case; each release tags the corpus (`corpus-v1.4`); a contributed case lands with its control and faulty build, like any check | seeded in v1.4 with one case, `corpus/cases/2026-10-22-R14-x402-core.json` (R14); open to contributions from v1.4 |
| A7 | **A compatibility matrix regenerated in CI.** The stock servers, at pinned SDK versions, run on a schedule and on every release; the matrix in [MATRIX.md](MATRIX.md) and a JSON copy are rebuilt from those runs, never edited by hand | each row links to the run that produced it; failing rows on stock servers go to maintainers privately first under [SECURITY.md](../SECURITY.md) | TypeScript rows in v1.4; Python and Go rows in v1.5 |
| A8 | **Docs examples.** Copy-paste examples for each framework and for GitHub Actions, GitLab CI and a plain `make` target | every example is run by CI, so none of them can rot | v1.4 for the A4 frameworks; v1.5 for the rest |

## The release gate

v1.4 and v1.5 ship as soon as their own criteria pass, still marked experimental. The experimental label comes off,
and I describe the suite as a dependable x402 safety gate, only when all six of these hold:

- [x] **Resource binding.** A real protected route rejects resource, amount, recipient and method substitution (R11, 1.4.0).
- [x] **Concurrency.** Parallel replay, multi-replica and retry tests can't double-grant or double-charge (R12, R13, R20; 1.5.0).
- [x] **Delivery recovery.** Timeout, late settlement, failed response, redirect, `HEAD` and retry scenarios have
  explicit, tested outcomes (R14 to R18; 1.6.0).
- [x] **Test credibility.** Every check catches at least one faulty build and passes a legitimate control, and CI
  enforces it.
- [ ] **Safe, reproducible evidence.** Pinned versions, clear scope, raw results, hashes and documented
  false-positive handling.
- [ ] **Public validation.** At least three independent teams have run it and published results or actionable issues.

Before that point the test definitions are frozen for one release, run against independent implementations, and the
evidence is published.

## Scope

**In scope:** open-source code under Apache-2.0: every check and its spec mapping, the faulty builds, the facilitator
double, the Python and TypeScript CLIs, the GitHub Action, the evidence format, the regression corpus, the
compatibility matrix, the Lean models and every result I publish. All of it runs on your machine or your CI.

**Not on the roadmap:**
- **Certification.** A pass is evidence about one property on one day. The badge says "tested with", and I won't
  offer a certification scheme without agreed criteria and independent governance.
- **Hosted services or live dashboards.** The suite is code you run; results stay in your repo and your CI. The one
  exception is the static scoreboard on the Pages site (proposed XC-52), generated only from committed, hashed evidence,
  with no overall score and no certification wording.
- **Shallow checks** added to raise the count. Each check has to meet the bar above.
- **Mainnet probes** or anything else that submits a real payment or creates financial risk.
- **Every chain, SDK and extension at once.** Depth on payment-to-resource safety comes first.

## How I'll measure it

Adoption is the goal, so the first four measures are about use. The last three keep the checks trustworthy while it
grows.

| measure | v1.4 | v1.5 | release gate |
|---|---|---|---|
| external public repos using the Action (GitHub code search for `atsp-protocol/x402-conformance@`) | 3 | 10 | 25 |
| package downloads per month (PyPI `x402-conformance` plus npm `x402-conformance-svm`) | 500 | 2,000 | 5,000 |
| corpus cases contributed from outside this repo | 1 | 5 | 15 |
| upstream fixes that cite a check or a corpus case | 2 | 4 | 6 |
| checks with a passing control and a caught faulty build | 100% | 100% | 100% |
| time from the A1 one-liner to a first result | under 60 s | under 60 s | under 60 s |
| median time from a false-positive report to a fix or a documented exception | 7 days | 7 days | 7 days |

I count a user, a team or a repo only when it's public or they've said so publicly.

## Programme milestones

These were my original proposal for taking the suite from a working tool to a standard people rely on. Every milestone
is a Proofline task in `proofline.json` (XC-M1 to XC-M6), with acceptance criteria that CI verifies. The v1.4 and v1.5
work above, the checks built beyond the plan and the 1.5.0 and 1.6.0 release tasks are signed into `proofline.json` as
XC-08 to XC-46 and XC-48 (XC-38 was never used). XC-47 (S5) is proposed in
[proposals/contract-addendum-s5.json](proposals/contract-addendum-s5.json) and becomes binding only once I sign it.

| id | deliverable | acceptance (summary) | status |
|---|---|---|---|
| M1 | **Devnet runner.** F1 to F6 run over real x402 V2 `/verify` and `/settle` against a facilitator on Solana devnet that I host myself, using throwaway devnet keypairs | `x402conf devnet` exits 0 against the self-hosted reference facilitator; each F check also fails against a fault-injected build; the devnet evidence is committed with hashes | devnet run done (1.1.0), [evidence/devnet](../evidence/devnet): F1, F2, F3, F5 and F6 pass, every fault-injected build is caught, and F4 fails on the reference facilitator (memo not tracked across transactions), so the exit-0 criterion is not met yet |
| M2 | **Facilitator matrix.** Results pages for at least 3 facilitators that offer Solana devnet, run only with each operator's permission | `evidence/matrix/` holds at least 3 facilitator reports; any failures go through the 90-day disclosure in [SECURITY.md](../SECURITY.md) first | open: no operator has been asked yet |
| M3 | **Lean models extended.** Timeouts, `settlement_pending` reconciliation, and concurrent settles over a shared cache | New theorems build in CI with only standard axioms; each theorem is linked to its F check in [SPEC.md](SPEC.md) | done (1.0.0) |
| M4 | **Drop-in CI action.** A GitHub Action plus a TypeScript runner for resource servers built on `@x402/svm` (and, since 1.3.0, `@x402/evm`) | The action runs F1 to F6 in another repo's CI, and an example repo is green | done (1.0.0) |
| M5 | **Maintenance for 6 months.** Issues, spec updates and fixes | Monthly: open issues are triaged within 7 days and CI stays green on the current spec | ongoing since 1.0.0 |
| M6 | **Adoption.** Real projects relying on it | At least 3 external repos run the suite in CI; at least 5 facilitators have published results | open: needs real users |

Review is open and public, through issues, pull requests and Discussions in this repo.

— Ryan Gillespie, Optitransfer
