// Paid MCP tools (specs/transports-v2/mcp.md). The probe speaks JSON-RPC to an MCP server over Streamable HTTP
// (POST, a JSON or an event-stream answer) and calls one paid tool.
//
//   X1  called without a payment, the tool answers a tool result with isError true, the PaymentRequired object in
//       structuredContent and the same object, JSON-encoded, in content[0].text; not a JSON-RPC error. Read-only: one
//       unpaid tools/call, no payment is sent.
//   X2  the R0-R10 faults for HTTP, on a paid tool call: with the server's facilitator pointed at the double, a payment
//       in _meta["x402/payment"] gets the tool's result only on a final, well-formed, first-time settle (with
//       _meta["x402/payment-response"] success=true). A /settle that never answers, an HTML 502, a 503 with a success
//       body, a non-JSON or truncated 200, settlement_pending, a failed settle and a duplicate of a settled payment
//       each get no tool result.
import type { Double, Mode } from "./double.js";
import { NETWORKS } from "./double.js";
import type { Result } from "./probe.js";
import { freshPayload } from "./retry.js";
import { RequestBudgetExceeded } from "./pace.js";

export const X1 = "X1 a paid MCP tool called without a payment answers a tool result with isError true, the "
  + "PaymentRequired object in structuredContent and the same object JSON-encoded in content[0].text";
export const X2 = "X2 a paid MCP tool call gets no tool result when /settle times out, answers broken, is pending, "
  + "fails or is a duplicate, and gets it once with x402/payment-response on a final success";

/** An MCP server reachable over Streamable HTTP, and the paid tool to call. */
export interface McpTarget { url: string; tool: string; arguments?: Record<string, unknown> }
export interface McpOptions {
  /** Network to pay on when the tool offers several; defaults to the first of NETWORKS it offers. */
  network?: string;
  /** How long one JSON-RPC request may take. A server still holding a paid call at the deadline has served nothing. */
  timeoutMs?: number;
  /** The fetch to send with, e.g. a paced one for a live server (createPacedFetch). Defaults to the global fetch. */
  fetch?: typeof fetch;
  /** X1 only: false skips initialize and notifications/initialized for a server that answers tools/call without a
   * session, so the check is one request. Defaults to true. */
  initialize?: boolean;
}

const PROTOCOL = "2025-06-18";

export interface RpcAnswer {
  status: number;
  timedOut: boolean;
  /** The JSON-RPC `result`, when the answer carried one. */
  result?: any;
  /** The JSON-RPC `error`, when the answer carried one. */
  error?: any;
  raw: string;
}

/** A Streamable HTTP MCP session: initialize once, then send requests carrying the session id the server issued. */
export class McpSession {
  private session: string | null = null;
  private next = 1;
  constructor(public url: string, private timeoutMs = 15_000, private fetchImpl: typeof fetch = fetch) {}

  private async post(body: unknown, expectAnswer: boolean): Promise<RpcAnswer> {
    const headers: Record<string, string> = { "content-type": "application/json",
      accept: "application/json, text/event-stream", "mcp-protocol-version": PROTOCOL };
    if (this.session) headers["mcp-session-id"] = this.session;
    let r: Response;
    try {
      r = await this.fetchImpl(this.url, { method: "POST", headers, body: JSON.stringify(body),
        signal: AbortSignal.timeout(this.timeoutMs) });
    } catch (e) {
      if (e instanceof RequestBudgetExceeded) throw e;
      const n = (e as Error)?.name;
      return { status: 0, timedOut: n === "TimeoutError" || n === "AbortError", raw: String(e).slice(0, 300) };
    }
    const sid = r.headers.get("mcp-session-id");
    if (sid) this.session = sid;
    let raw = "";
    try { raw = await r.text(); } catch (e) {
      const n = (e as Error)?.name;
      return { status: r.status, timedOut: n === "TimeoutError" || n === "AbortError", raw: String(e).slice(0, 300) };
    }
    if (!expectAnswer) return { status: r.status, timedOut: false, raw: raw.slice(0, 300) };
    const id = (body as any)?.id;
    const msg = parseRpc(raw, String(r.headers.get("content-type") ?? ""), id);
    return { status: r.status, timedOut: false, raw: raw.slice(0, 600),
      ...(msg && "result" in msg ? { result: msg.result } : {}), ...(msg && "error" in msg ? { error: msg.error } : {}) };
  }

  async initialize(): Promise<RpcAnswer> {
    const a = await this.post({ jsonrpc: "2.0", id: this.next++, method: "initialize", params: {
      protocolVersion: PROTOCOL, capabilities: {}, clientInfo: { name: "x402-conformance", version: "1" } } }, true);
    if (a.result) await this.post({ jsonrpc: "2.0", method: "notifications/initialized" }, false);
    return a;
  }

  /** tools/call, with `_meta` on the params when given. */
  callTool(name: string, args: Record<string, unknown> = {}, meta?: Record<string, unknown>): Promise<RpcAnswer> {
    return this.post({ jsonrpc: "2.0", id: this.next++, method: "tools/call",
      params: { name, arguments: args, ...(meta ? { _meta: meta } : {}) } }, true);
  }
}

/** The JSON-RPC message with `id` from a JSON body or an event stream of `data:` lines. */
export function parseRpc(raw: string, contentType: string, id: unknown): any {
  const pick = (m: any) => (Array.isArray(m) ? m.find((x) => x?.id === id) : m?.id === id ? m : null);
  if (contentType.includes("text/event-stream")) {
    for (const block of raw.split(/\r?\n\r?\n/)) {
      const data = block.split(/\r?\n/).filter((l) => l.startsWith("data:")).map((l) => l.slice(5).trimStart()).join("\n");
      if (!data) continue;
      try { const m = pick(JSON.parse(data)); if (m) return m; } catch { /* not JSON: skip the event */ }
    }
    return null;
  }
  try { return pick(JSON.parse(raw)); } catch { return null; }
}

const isObj = (v: unknown): v is Record<string, any> => !!v && typeof v === "object" && !Array.isArray(v);
const canon = (v: unknown): string => JSON.stringify(v, (_k, x) =>
  isObj(x) ? Object.fromEntries(Object.keys(x).sort().map((k) => [k, x[k]])) : x);
const REQUIRED_FIELDS = ["scheme", "network", "amount", "asset", "payTo"] as const;

/** What is wrong with a payment-required tool result, per specs/transports-v2/mcp.md; empty when nothing is. */
export function paymentRequiredProblems(a: RpcAnswer): string[] {
  if (a.timedOut || a.status === 0) return [`no answer (${a.raw || "timed out"})`];
  if (a.error) return [`answered a JSON-RPC error (${JSON.stringify(a.error).slice(0, 160)}), not a tool result with isError`];
  const r = a.result;
  if (!isObj(r)) return [`HTTP ${a.status} with no JSON-RPC result`];
  const out: string[] = [];
  if (r.isError !== true) out.push("isError is not true");
  const sc = r.structuredContent;
  if (!isObj(sc)) out.push("structuredContent is missing: it MUST carry the PaymentRequired object");
  else {
    if (sc.x402Version !== 2) out.push(`structuredContent.x402Version is ${JSON.stringify(sc.x402Version)}, not 2`);
    if (!isObj(sc.resource) || typeof sc.resource.url !== "string" || !sc.resource.url) {
      out.push("structuredContent.resource.url is missing");
    }
    if (!Array.isArray(sc.accepts) || sc.accepts.length === 0) out.push("structuredContent.accepts is empty or missing");
    else {
      sc.accepts.forEach((x: any, i: number) => {
        const miss = REQUIRED_FIELDS.filter((f) => typeof x?.[f] !== "string" || !x[f]);
        if (miss.length) out.push(`accepts[${i}] lacks ${miss.join(", ")}`);
        if (typeof x?.maxTimeoutSeconds !== "number") out.push(`accepts[${i}].maxTimeoutSeconds is not a number`);
      });
    }
  }
  const c0 = Array.isArray(r.content) ? r.content[0] : undefined;
  if (!isObj(c0) || c0.type !== "text" || typeof c0.text !== "string") {
    out.push("content[0] is not a text item: it MUST carry the PaymentRequired object as JSON");
  } else {
    let parsed: unknown;
    try { parsed = JSON.parse(c0.text); } catch { parsed = undefined; }
    if (parsed === undefined) out.push("content[0].text is not JSON");
    else if (isObj(sc) && canon(parsed) !== canon(sc)) out.push("content[0].text is not the same object as structuredContent");
  }
  return out;
}

/** Runs X1: one unpaid call of the paid tool. Sends no payment. */
export async function checkMcpPaymentRequired(target: McpTarget, opts: McpOptions = {}): Promise<Result[]> {
  return (await unpaidToolCall(target, opts)).results;
}

/** X1 and the unpaid answer it graded, so a caller can grade the offer in it too. */
export async function unpaidToolCall(target: McpTarget, opts: McpOptions = {}):
    Promise<{ results: Result[]; answer: RpcAnswer | null }> {
  const s = new McpSession(target.url, opts.timeoutMs ?? 15_000, opts.fetch ?? fetch);
  if (opts.initialize !== false) {
    const init = await s.initialize();
    if (!init.result) {
      return { answer: null, results: [{ check: X1, pass: false, status: "fail", detail: {
        error: "the MCP initialize request got no result", status: init.status, answer: init.error ?? init.raw } }] };
    }
  }
  const a = await s.callTool(target.tool, target.arguments ?? {});
  const problems = paymentRequiredProblems(a);
  const pass = problems.length === 0;
  return { answer: a, results: [{ check: X1, pass, status: pass ? "pass" : "fail", detail: { tool: target.tool,
    status: a.status, initialized: opts.initialize !== false, is_error: a.result?.isError ?? null,
    accepts: a.result?.structuredContent?.accepts?.length ?? 0,
    ...(pass ? {} : { error: problems.join("; "), answer: a.error ?? a.result ?? a.raw }) } }] };
}

/** The fault cases X2 runs, in order, each with a fresh payment; "duplicate" resends the reference case's payment. */
export const X2_CASES: readonly (Mode | "duplicate")[] = ["reference", "duplicate", "settle_timeout", "settle_502",
  "settle_503", "settle_non_json", "settle_truncated", "settle_pending", "settle_failed"];

const settleCount = (d: Double) => d.calls.filter((c) => c.path === "/settle").length;

/** Runs X2 against an MCP server whose facilitator URL is the double's. */
export async function probeMcpTransport(target: McpTarget, double: Double, opts: McpOptions = {}): Promise<Result[]> {
  const timeoutMs = opts.timeoutMs ?? 15_000;
  const s = new McpSession(target.url, timeoutMs, opts.fetch ?? fetch);
  const init = await s.initialize();
  const unpaid = init.result ? await s.callTool(target.tool, target.arguments ?? {}) : init;
  const sc = unpaid.result?.structuredContent ?? (() => {
    try { return JSON.parse(unpaid.result?.content?.[0]?.text ?? ""); } catch { return null; }
  })();
  const want: readonly string[] = opts.network ? [opts.network] : NETWORKS;
  let accepted: any;
  for (const n of want) {
    accepted = sc?.accepts?.find((x: any) => x?.scheme === "exact" && x?.network === n);
    if (accepted) break;
  }
  if (unpaid.result?.isError !== true || !accepted) {
    return [{ check: X2, pass: false, status: "unsupported", detail: { error: "the unpaid tool call did not answer a "
      + `payment-required tool result with an exact offer on ${want.join(" or ")}`, answer: unpaid.error ?? unpaid.result ?? unpaid.raw } }];
  }
  const cases: Record<string, unknown> = {};
  const errors: string[] = [];
  let first: Record<string, unknown> | null = null;
  for (const c of X2_CASES) {
    const payload: Record<string, unknown> = c === "duplicate" && first ? first : freshPayload(accepted);
    if (c === "reference") first = payload;
    double.mode = c === "duplicate" ? "reference" : c;
    const before = { settles: settleCount(double), ok: double.successes.length };
    const a = await s.callTool(target.tool, target.arguments ?? {}, { "x402/payment": {
      x402Version: 2, resource: sc.resource, accepted, payload } });
    await new Promise((ok) => setTimeout(ok, 100));
    const served = !!a.result && a.result.isError !== true;
    const pr = a.result?._meta?.["x402/payment-response"];
    const row = { served, timed_out: a.timedOut, rpc_error: a.error?.code ?? null, is_error: a.result?.isError ?? null,
      settle_calls: settleCount(double) - before.settles, charged: double.successes.length - before.ok,
      payment_response: pr ?? null };
    cases[c] = row;
    if (c === "reference") {
      if (!served) errors.push(`reference: a settled payment got no tool result (${JSON.stringify(a.error ?? a.result ?? a.raw).slice(0, 160)})`);
      else if (row.settle_calls < 1) errors.push("reference: the tool result came back but the server never called /settle");
      else if (pr?.success !== true || typeof pr?.transaction !== "string" || !pr.transaction) {
        errors.push("reference: the tool result has no _meta[\"x402/payment-response\"] with success true and the transaction");
      }
    } else if (served) {
      errors.push(`${c}: the tool result was returned`);
    }
  }
  const pass = errors.length === 0;
  return [{ check: X2, pass, status: pass ? "pass" : "fail", detail: { tool: target.tool, network: accepted.network,
    cases, ...(pass ? {} : { error: errors.join("; ") }) } }];
}
