#!/usr/bin/env node
// x402conf-svm probe --resource <url> [--port 4402] [--start "<command>"] [--network auto|<CAIP-2>] [--out file] [--share]
// x402conf-svm resource --url <url> [--out file] [--share]   (P1-P7, one unpaid GET)
// x402conf-svm live --url <url> [--operator-permission REF] [--min-interval 5] [--max-requests N] [--out file]
//                   (P1-P7, R24 and, on loopback or with --operator-permission, R16a; unpaid, paced)
// x402conf-svm mcp --url <mcp endpoint> --tool <name> [--arguments JSON] [--no-initialize] [--min-interval 5]
//                  [--max-requests N] [--out file]   (X1, P3-P5 and P7 on one unpaid tools/call, paced)
// Starts the facilitator double on 127.0.0.1:<port>, optionally starts your resource server with
// X402_FACILITATOR_URL pointing at it, waits for the resource to answer, runs R0-R10, and with the binding options
// R11 (payment-to-request binding), and with --crash R14 (a crash between /settle and the response). Every result carries its profile, spec basis and fix link (evidence v2).
// Exit codes: 0 all pass; 1 a check failed; 2 usage error, or the run could not be completed (port taken, server
// exited or never answered); 3 unsupported (the server offers no network the probe can grade).
import { readFileSync, writeFileSync } from "node:fs";
import { NETWORKS, PortInUseError, startDouble, type Network } from "./double.js";
import { probe, type Result } from "./probe.js";
import { anonymise, funnelFooter, shareUrl } from "./corpus.js";
import { makeReport, VIAS, type Kind, type Via } from "./report.js";
import { check402, checkPaymentRequired, fetch402 } from "./resource.js";
import { createPacedFetch, DEFAULT_MIN_INTERVAL_MS, RequestBudgetExceeded, type PacedFetch } from "./pace.js";
import { headNeedsPermission, probeUnpaidHead } from "./head-unpaid.js";
import { probeMalformedHeader } from "./header.js";
import { checkMcpSeller } from "./mcp-seller.js";
import { probeBinding, type BindingTargets } from "./binding.js";
import { probeRetry } from "./retry.js";
import { EVIDENCE_FORMAT, label } from "./catalog.js";
import { provenance } from "./provenance.js";
import { MOCK_FAULTS, startMockResource } from "./mock-server.js";
import { commandControl, probeCrash, SpawnedServer, type ServerControl } from "./crash.js";
type Labelled = Result & { profile: string; basis: string; fix: string };

export const VERSION: string = JSON.parse(readFileSync(new URL("../../package.json", import.meta.url), "utf8")).version;

const USAGE = `x402conf-svm ${VERSION}: resource-server checks R0-R11, R14 and R20 for x402 V2 servers (Solana devnet, Base Sepolia)

usage:
  x402conf-svm probe --resource <url> [binding options] [--retry] [--port 4402] [--start "<command>"]
                     [--network auto|${NETWORKS.join("|")}] [--out file] [--share]
                     [--crash] [--crash-kill "<command>" --crash-restart "<command>"]
  x402conf-svm probe <binding options> [--port 4402] [--start "<command>"] [--out file] [--share]
  x402conf-svm resource --url <url> [--min-interval 5] [--max-requests N] [--out file] [--share]
  x402conf-svm live --url <url> [--operator-permission REF] [--min-interval 5] [--max-requests N] [--out file]
  x402conf-svm mcp --url <mcp endpoint> --tool <name> [--arguments '<json>'] [--no-initialize]
                   [--min-interval 5] [--max-requests N] [--out file]
  x402conf-svm demo [--fault ${MOCK_FAULTS.join("|")}] [--out file]
  x402conf-svm --help | --version

  demo              run R0-R10 against a bundled mock resource server and facilitator double on loopback: no project,
                    no wallet, no chain, well under a minute. --fault shows a failing run and its fix hints

  --resource        your paid route, e.g. http://127.0.0.1:4020/paid (R0-R10)
  binding options (R11; give at least --resource or one of these):
  --cheap, --expensive  two paid routes at different prices (R11 control, R11a, R11b)
  --by-method       a paid URL priced differently for GET and POST (R11c)
  --by-query        two paid URLs that differ only in the query, comma-separated (R11d)
  --param           a paid parameterised route with {id} for the parameter, e.g. http://host/items/{id}/premium (R11e)
  --siwx-cheap, --siwx-expensive  two paid routes at different prices that declare sign-in-with-x (R11f, EVM)
  --crash     also run R14 (needs --resource): kill your server after /settle succeeds and before its response, start
              it again and present the same payment. With --start the probe kills and restarts that command itself
  --crash-kill, --crash-restart  for a server --start did not launch: a command that kills it hard and returns once
              it is gone, and one that starts it again in the background and returns (R14)
  --retry     also run R20 on --resource: the client times out before /settle answers and retries, with a fresh
              payment under the same idempotency key (R20a) and with the same signed payment (R20b); the request
              must be paid once and the retry must get the earlier result. R20c grades the fresh-payment retry for
              safety only: a 409, or a 4xx naming the id, passes it as long as the retry is never settled
  --port      loopback port for the facilitator double (default 4402)
  --start     command that starts your server; it gets X402_FACILITATOR_URL and must use it as its facilitator
  --network   which offered network to pay on (default auto: the first of ${NETWORKS.join(", ")})
  --out       also write the results JSON here (written on errors too)
  --url       (resource) a paid URL; one unpaid GET checks its 402 answer (P1-P7), on any network
              (live) a paid URL on a server you may test: one unpaid GET (P1-P7), one unpaid HEAD (R16a) and one GET per
              malformed PAYMENT-SIGNATURE (R24, five values): 7 requests. Nothing is paid or signed. HEAD is not a
              GET: off loopback R16a runs only with --operator-permission, and is skipped without it
  --operator-permission  (live) a reference to the operator's written permission for the unpaid HEAD off loopback,
              for example the matrix row's consent issue URL; recorded in the results
              (mcp) an MCP server over Streamable HTTP, e.g. https://host/mcp: one unpaid tools/call of --tool (X1, and
              P3-P5 and P7 on the PaymentRequired in it), after initialize unless --no-initialize. This POSTs JSON-RPC:
              run it only against a server whose operator agreed. Nothing is paid or signed
  --tool      (mcp) the paid tool to call
  --arguments (mcp) the tool's arguments as a JSON object (default {})
  --no-initialize  (mcp) call the tool without initialize, for a server that needs no session: 1 request, not 3
  --min-interval  (resource, live, mcp) at least this many seconds between requests to a non-loopback target (default 5);
              every request is logged on stderr
  --max-requests  (resource, live, mcp) send at most this many requests; a check that would need more is reported skipped
  --share     opt-in: also write an anonymised corpus case next to --out (or ./x402-conformance-case.json) and print
              a link to a pre-filled GitHub issue. Nothing is sent; you review the case and submit it yourself.

Every run's JSON has the same check IDs and report fields as the Python CLI, the Action, the test matchers, the MCP
server and the Docker image. X402CONF_VIA names the entry point in the report and User-Agent (no telemetry).
exit codes: 0 all pass, 1 a check failed, 2 usage error or the run could not complete,
            3 unsupported (the server offers no network the probe grades)`;

const BINDING = ["cheap", "expensive", "by-method", "by-query", "param", "siwx-cheap", "siwx-expensive"];
const FLAGS = new Set(["--resource", "--port", "--start", "--out", "--network", "--url", "--crash-kill", "--crash-restart",
  "--min-interval", "--max-requests", "--tool", "--arguments", "--operator-permission",
  ...BINDING.map((b) => `--${b}`)]);
const BOOL = new Set(["--share", "--crash", "--retry", "--no-initialize"]);

function bindingTargets(o: Record<string, string>): BindingTargets | string | null {
  if (!BINDING.some((b) => o[b])) return null;
  if (!!o.cheap !== !!o.expensive) return "--cheap and --expensive go together";
  if (!!o["siwx-cheap"] !== !!o["siwx-expensive"]) return "--siwx-cheap and --siwx-expensive go together";
  if (o.param && !o.param.includes("{id}")) return "--param needs {id} where the parameter goes";
  const q = o["by-query"]?.split(",");
  if (q && q.length !== 2) return "--by-query takes two URLs, comma-separated";
  return { cheap: o.cheap, expensive: o.expensive, byMethod: o["by-method"], parameterised: o.param,
    byQuery: q as [string, string] | undefined,
    siwx: o["siwx-cheap"] ? { cheap: o["siwx-cheap"], expensive: o["siwx-expensive"] } : undefined };
}

class RunError extends Error {}

function parse(argv: string[]): Record<string, string> | number {
  if (argv.includes("--help") || argv.includes("-h")) { console.log(USAGE); return 0; }
  if (argv.includes("--version") || argv.includes("-V")) { console.log(VERSION); return 0; }
  if (!["probe", "resource", "live", "mcp"].includes(argv[0])) { console.error(USAGE); return 2; }
  const o: Record<string, string> = { cmd: argv[0] };
  for (let i = 1; i < argv.length; i += 2) {
    const k = argv[i], v = argv[i + 1];
    if (BOOL.has(k)) { o[k.slice(2)] = "1"; i -= 1; continue; }
    if (!FLAGS.has(k) || v === undefined || v.startsWith("--")) {
      console.error(`x402conf-svm: unknown or incomplete option ${k}\n\n${USAGE}`);
      return 2;
    }
    o[k.slice(2)] = v;
  }
  if (o["min-interval"] !== undefined && !(Number(o["min-interval"]) >= 0)) {
    console.error("x402conf-svm: --min-interval must be 0 or more seconds"); return 2;
  }
  if (o["max-requests"] !== undefined && !/^[1-9]\d*$/.test(o["max-requests"])) {
    console.error("x402conf-svm: --max-requests must be a whole number, at least 1"); return 2;
  }
  if (o.cmd === "probe" && (o["min-interval"] || o["max-requests"])) {
    console.error("x402conf-svm: --min-interval and --max-requests go with resource, live or mcp (probe runs on loopback)");
    return 2;
  }
  if (o.cmd !== "mcp" && (o.tool || o.arguments || o["no-initialize"])) {
    console.error(`x402conf-svm: --tool, --arguments and --no-initialize go with mcp\n\n${USAGE}`); return 2;
  }
  if (o.cmd === "mcp") {
    if (!o.url || !o.tool || o.share || o.resource || o.start || o.port || o.network || o.crash || o.retry ||
        o["crash-kill"] || o["crash-restart"] || BINDING.some((b) => o[b])) {
      console.error("x402conf-svm: mcp takes --url and --tool (and optionally --arguments, --no-initialize, " +
        `--min-interval, --max-requests, --out)\n\n${USAGE}`);
      return 2;
    }
    let a: unknown;
    try { a = JSON.parse(o.arguments ?? "{}"); } catch { a = null; }
    if (!a || typeof a !== "object" || Array.isArray(a)) {
      console.error("x402conf-svm: --arguments must be a JSON object"); return 2;
    }
    return o;
  }
  if (o["operator-permission"] !== undefined && o.cmd !== "live") {
    console.error(`x402conf-svm: --operator-permission goes with live\n\n${USAGE}`); return 2;
  }
  if (o.cmd === "resource" || o.cmd === "live") {
    if (o.cmd === "live" && o.share) { console.error(`x402conf-svm: live takes no --share\n\n${USAGE}`); return 2; }
    if (!o.url || o.resource || o.start || o.port || o.network || o.crash || o["crash-kill"] || o["crash-restart"] ||
        BINDING.some((b) => o[b])) {
      console.error(`x402conf-svm: ${o.cmd} takes --url (and optionally --min-interval, --max-requests, --out` +
        `${o.cmd === "resource" ? ", --share" : ""})\n\n${USAGE}`);
      return 2;
    }
    return o;
  }
  if (o.url) { console.error(`x402conf-svm: probe takes --resource, not --url\n\n${USAGE}`); return 2; }
  const b = bindingTargets(o);
  if (typeof b === "string") { console.error(`x402conf-svm: ${b}`); return 2; }
  if (!o.resource && !b) { console.error(`x402conf-svm: give --resource or a binding option\n\n${USAGE}`); return 2; }
  if (o.retry && !o.resource) { console.error(`x402conf-svm: --retry needs --resource\n\n${USAGE}`); return 2; }
  if (o.network && o.network !== "auto" && !(NETWORKS as readonly string[]).includes(o.network)) {
    console.error(`x402conf-svm: --network must be auto or one of ${NETWORKS.join(", ")}`);
    return 2;
  }
  if (o.port && !/^\d+$/.test(o.port)) { console.error("x402conf-svm: --port must be a number"); return 2; }
  const crashUsage = crashProblem(o);
  if (crashUsage) { console.error(`x402conf-svm: ${crashUsage}`); return 2; }
  return o;
}

function crashProblem(o: Record<string, string>): string | null {
  const kill = o["crash-kill"], restart = o["crash-restart"];
  if ((kill || restart) && !o.crash) return "--crash-kill and --crash-restart go with --crash";
  if (!o.crash) return null;
  if (!o.resource) return "--crash needs --resource (the paid route R14 pays for)";
  if (!!kill !== !!restart) return "--crash-kill and --crash-restart go together";
  if (kill && o.start) return "give --start or --crash-kill and --crash-restart, not both";
  if (!kill && !o.start) return "--crash needs --start (the probe restarts that command) or --crash-kill and --crash-restart";
  return null;
}

async function answers(url: string, ms: number): Promise<boolean> {
  try { await fetch(url, { signal: AbortSignal.timeout(ms) }); return true; } catch { return false; }
}

function via(): Via {
  const v = process.env.X402CONF_VIA as Via | undefined;
  return v && VIAS.includes(v) ? v : "cli-ts";
}

// Writes --out, and with --share the anonymised case; prints the JSON, then the funnel footer on stderr.
function finish(o: Record<string, string>, kind: Kind, target: string, results: Result[] | ReturnType<typeof makeReport>["results"],
    doc: Record<string, unknown>): void {
  const report = makeReport(kind, target, results, via(), doc.error as string | undefined);
  Object.assign(doc, { schema: report.schema, via: report.via, kind, provenance: report.provenance, summary: report.summary, links: report.links });
  const text = JSON.stringify(doc, null, 1);
  if (o.out) writeFileSync(o.out, text + "\n");
  console.log(text);
  if (o.share) {
    const c = anonymise(report);
    const path = o.out ? o.out.replace(/(\.json)?$/, ".case.json") : "x402-conformance-case.json";
    writeFileSync(path, JSON.stringify(c, null, 1) + "\n");
    const link = shareUrl(c);
    console.error(link ? `x402conf-svm: anonymised case written to ${path}. Review it, then submit it here (nothing was sent):\n${link}`
      : `x402conf-svm: nothing failed, so there is no case to share (${path} records the passing run).`);
  }
  console.error(funnelFooter(report));
}

function pacedFetch(o: Record<string, string>): PacedFetch {
  return createPacedFetch({ minIntervalMs: o["min-interval"] !== undefined ? Number(o["min-interval"]) * 1000
    : DEFAULT_MIN_INTERVAL_MS, maxRequests: o["max-requests"] ? Number(o["max-requests"]) : undefined });
}

const pacing = (o: Record<string, string>, f: PacedFetch) => ({
  min_interval_s: o["min-interval"] !== undefined ? Number(o["min-interval"]) : DEFAULT_MIN_INTERVAL_MS / 1000,
  max_requests: o["max-requests"] ? Number(o["max-requests"]) : null, sent: f.requests.length, requests: f.requests });

async function resourceMain(o: Record<string, string>): Promise<number> {
  const f = pacedFetch(o);
  const report = await checkPaymentRequired(o.url, { via: via(), fetch: f });
  const doc: Record<string, unknown> = { tool: `x402-conformance-svm ${VERSION}`, run_at: report.run_at, target: o.url,
    mode: "resource-GET-only", checks: report.results, pacing: pacing(o, f) };
  finish(o, "resource-402", o.url, report.results, doc);
  return report.summary.failed ? 1 : 0;
}

/** live: P1-P7 from one unpaid GET, then R16a (one HEAD, on loopback or with --operator-permission) and R24 (five
 * malformed headers) on the same URL, every request paced and logged. The first GET is shared, so R16a and R24 do not
 * send their own. Never pays or signs. */
async function liveMain(o: Record<string, string>): Promise<number> {
  const f = pacedFetch(o);
  const doc: Record<string, unknown> = { tool: `x402-conformance-svm ${VERSION}`, evidence: EVIDENCE_FORMAT, provenance: provenance(VERSION),
    run_at: new Date().toISOString(), target: o.url, mode: "live-unpaid",
    ...(o["operator-permission"] ? { operator_permission: o["operator-permission"] } : {}) };
  let results: Result[] = [];
  const skipped: string[] = [];
  const head = !headNeedsPermission(o.url, o["operator-permission"]);
  try {
    const answer = await fetch402(o.url, { via: via(), fetch: f });
    results = check402(answer) as Result[];
    if (answer.status === 402) {
      if (head) results.push(...await probeUnpaidHead(o.url, { fetch: f, unpaidGetStatus: answer.status }));
      else skipped.push("R16a: an unpaid HEAD is not a GET; off loopback it needs --operator-permission");
      results.push(...await probeMalformedHeader(o.url, { calls: [] }, { fetch: f, unpaidGetStatus: answer.status }));
    } else {
      skipped.push("R16a and R24: the unpaid GET was not answered 402");
    }
  } catch (e) {
    if (!(e instanceof RequestBudgetExceeded)) throw e;
    skipped.push(e.message);
  }
  doc.checks = results.map(label);
  doc.pacing = pacing(o, f);
  if (skipped.length) doc.skipped = skipped;
  finish(o, "resource-402", o.url, results, doc);
  return results.some((r) => !r.pass && r.status === "fail" && (r as any).severity !== "warning") ? 1 : 0;
}

/** mcp: one unpaid tools/call (after initialize unless --no-initialize), paced and logged; X1, then P3-P5 and P7 on
 * the PaymentRequired in the tool result. Never pays or signs. */
async function mcpMain(o: Record<string, string>): Promise<number> {
  const f = pacedFetch(o);
  const doc: Record<string, unknown> = { tool: `x402-conformance-svm ${VERSION}`, evidence: EVIDENCE_FORMAT, provenance: provenance(VERSION),
    run_at: new Date().toISOString(), target: o.url, mcp_tool: o.tool, mode: "mcp-unpaid" };
  let results: Result[] = [];
  const skipped: string[] = [];
  try {
    results = await checkMcpSeller({ url: o.url, tool: o.tool, arguments: JSON.parse(o.arguments ?? "{}") },
      { fetch: f as typeof fetch, initialize: !o["no-initialize"] });
  } catch (e) {
    if (!(e instanceof RequestBudgetExceeded)) throw e;
    skipped.push(e.message);
  }
  doc.checks = results.map(label);
  doc.pacing = pacing(o, f);
  if (skipped.length) doc.skipped = skipped;
  finish(o, "resource-402", o.url, results, doc);
  return results.some((r) => !r.pass && r.status === "fail" && (r as any).severity !== "warning") ? 1 : 0;
}

/** One line per check, a fix link under each failure. */
export function table(results: Labelled[]): string {
  const lines = results.map((r) => `  ${r.pass ? "pass" : r.status === "unsupported" ? "n/a " : "FAIL"}  ${r.check}` +
    (r.pass ? "" : `\n        fix: ${r.fix}`));
  const failed = results.filter((r) => !r.pass).length;
  return lines.join("\n") + `\n\n${results.length - failed}/${results.length} checks pass`;
}

async function demo(argv: string[]): Promise<number> {
  const o: Record<string, string> = {};
  for (let i = 0; i < argv.length; i += 2) {
    if (!["--fault", "--out"].includes(argv[i]) || argv[i + 1] === undefined) {
      console.error(`x402conf-svm: unknown or incomplete option ${argv[i]}\n\n${USAGE}`);
      return 2;
    }
    o[argv[i].slice(2)] = argv[i + 1];
  }
  if (o.fault && !(MOCK_FAULTS as readonly string[]).includes(o.fault)) {
    console.error(`x402conf-svm: --fault must be one of ${MOCK_FAULTS.join(", ")}`);
    return 2;
  }
  const t0 = Date.now();
  const double = await startDouble(0);
  const mock = await startMockResource(double.url, o.fault ?? "");
  let results: Labelled[];
  try {
    results = (await probe(mock.url, double, { network: "auto", deadlineMs: 10_000 })).map(label);
  } finally {
    await mock.close();
    await double.close();
  }
  const secs = ((Date.now() - t0) / 1000).toFixed(1);
  if (o.out) {
    writeFileSync(o.out, JSON.stringify({ tool: `x402-conformance-svm ${VERSION}`, evidence: EVIDENCE_FORMAT, provenance: provenance(VERSION),
      versions: { "x402-conformance-svm": VERSION, node: process.versions.node }, run_at: new Date().toISOString(),
      resource: "demo://bundled-mock" + (o.fault ? `?fault=${o.fault}` : ""), demo: true, seconds: Number(secs),
      results }, null, 1) + "\n");
  }
  console.log(`x402conf-svm ${VERSION} demo: a bundled mock resource server${o.fault ? ` (fault: ${o.fault})` : ""} ` +
    "behind a facilitator double on loopback. No wallet, no chain.\n");
  console.log(table(results) + ` in ${secs} s\n`);
  console.log("Next, point it at your own server (it gets X402_FACILITATOR_URL and must use it):\n" +
    "  npx x402-conformance-svm probe --resource http://127.0.0.1:4020/paid --start \"node server.js\"");
  return results.every((r) => r.pass) ? 0 : 1;
}

async function main(): Promise<number> {
  if (process.argv[2] === "demo") return demo(process.argv.slice(3));
  const o = parse(process.argv.slice(2));
  if (typeof o === "number") return o;
  if (o.cmd === "resource") return resourceMain(o);
  if (o.cmd === "live") return liveMain(o);
  if (o.cmd === "mcp") return mcpMain(o);
  const binding = bindingTargets(o) as BindingTargets | null;
  const resource = o.resource ?? binding?.cheap ?? binding?.byMethod ?? binding?.byQuery?.[0] ?? binding?.siwx?.cheap
    ?? binding?.parameterised?.replace("{id}", "1") ?? "";
  const doc: Record<string, unknown> = { tool: `x402-conformance-svm ${VERSION}`, evidence: EVIDENCE_FORMAT, provenance: provenance(VERSION),
    versions: { "x402-conformance-svm": VERSION, node: process.versions.node }, run_at: new Date().toISOString(),
    resource: o.resource ?? null, ...(binding ? { binding } : {}) };
  let results: Result[] = [];
  let server: SpawnedServer | null = null;
  const exited = () => server?.unexpectedExit ?? null;
  let double: Awaited<ReturnType<typeof startDouble>> | null = null;
  try {
    if (o.start && await answers(resource, 1500)) {
      throw new RunError(`something is already answering at ${resource} before --start ran; refusing to probe a server ` +
        "this run did not start. Stop it or use a free port.");
    }
    try {
      double = await startDouble(Number(o.port ?? "4402"));
    } catch (e) {
      throw new RunError(e instanceof PortInUseError ? e.message : `facilitator double failed to start: ${e}`);
    }
    doc.facilitator_double = double.url;
    const env = { ...process.env, X402_FACILITATOR_URL: double.url };
    if (o.start) {
      server = new SpawnedServer(o.start, env);
      server.start();
    }
    let up = false;
    for (let i = 0; i < 60 && !up; i++) {
      if (exited()) throw new RunError(`${exited()} before it answered at ${resource}`);
      up = await answers(resource, 2000);
      if (!up) await new Promise((ok) => setTimeout(ok, 1000));
    }
    if (exited()) throw new RunError(`${exited()} before it answered at ${resource}`);
    if (!up) throw new RunError(`no answer from ${resource} within 60 s`);
    const net = o.network as Network | "auto" | undefined;
    if (o.resource) results = await probe(o.resource, double, { network: net, via: via() });
    if (binding) {
      const offered = results.find((r) => r.check.startsWith("R0"))?.detail as any;
      const bnet = (o.network && o.network !== "auto" ? o.network : offered?.network) as string | undefined;
      results = results.concat(await probeBinding(binding, double, bnet));
    }
    if (o.retry && o.resource) {
      const offered = results.find((r) => r.check.startsWith("R0"))?.detail as any;
      const rnet = (o.network && o.network !== "auto" ? o.network : offered?.network) as string | undefined;
      results = results.concat(await probeRetry(o.resource, double, { network: rnet }));
    }
    if (exited()) throw new RunError(`${exited()} during the probe; the results are not trustworthy`);
    // R14 runs last: it kills and restarts the server. Only on a server R1 showed is wired to the double.
    if (o.crash && o.resource && results.some((r) => r.check.startsWith("R1 ") && r.pass)) {
      const control: ServerControl = server ?? commandControl(o["crash-kill"], o["crash-restart"], env);
      results = results.concat(await probeCrash(o.resource, double, control, { network: net, via: via() }));
      if (exited()) throw new RunError(`${exited()} after the R14 restart; the results are not trustworthy`);
    }
  } catch (e) {
    doc.error = e instanceof RunError ? e.message : `the probe crashed: ${e instanceof Error ? e.message : String(e)}`;
  } finally {
    server?.stop();
    await double?.close();
  }
  doc.results = results.map(label);
  finish(o, "resource-server", resource, doc.results as Labelled[], doc);
  if (doc.error) { console.error(`x402conf-svm: ${doc.error}`); return 2; }
  if (results.some((r) => r.status === "unsupported")) return 3;
  return results.every((r) => r.pass) ? 0 : 1;
}

main().then((c) => process.exit(c), (e) => { console.error(e); process.exit(2); });
