// Discovery (Bazaar) and A2A.
//
//   D1  a facilitator's discovery API answers in the V2 section 8 shapes: GET /discovery/resources returns
//       { x402Version, items, pagination: { limit, offset, total } } and honours limit and the network filter;
//       GET /discovery/search returns { x402Version, resources, partialResults?, pagination? } (the bazaar extension).
//       Every item carries resource, type, x402Version, a non-empty accepts of complete PaymentRequirements and an
//       ISO 8601 lastUpdated (V2 8.3). Read-only: GET requests only. A facilitator that serves neither endpoint is
//       unsupported: the endpoints are optional.
//   G1  an A2A payment-required exchange carries the same requirements as the HTTP 402 it mirrors: message/send to the
//       agent answers a task in state input-required with x402.payment.status "payment-required" and a V2
//       PaymentRequired in x402.payment.required whose accepts equal the PAYMENT-REQUIRED offers of the HTTP route
//       (specs/transports-v2/a2a.md). No payment is sent.
import { decodePaymentRequiredHeader } from "@x402/core/http";
import type { Result } from "./probe.js";

export const D1 = "D1 /discovery/resources and /discovery/search answer in the V2 section 8 shapes, with complete "
  + "items, and honour limit and the network filter";
export const G1 = "G1 an A2A payment-required task carries the same requirements as the HTTP 402 it mirrors";

export interface DiscoveryOptions { timeoutMs?: number; query?: string }

const isObj = (v: unknown): v is Record<string, any> => !!v && typeof v === "object" && !Array.isArray(v);
const REQ = ["scheme", "network", "amount", "asset", "payTo"] as const;
const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/;

/** What is wrong with one PaymentRequirements object; empty when nothing is. */
export function requirementProblems(a: unknown, where: string): string[] {
  if (!isObj(a)) return [`${where} is not an object`];
  const out = REQ.filter((f) => typeof a[f] !== "string" || !a[f]).map((f) => `${where}.${f} is missing`);
  if (typeof a.maxTimeoutSeconds !== "number") out.push(`${where}.maxTimeoutSeconds is not a number`);
  return out;
}

/** What is wrong with one discovered resource (V2 8.3); empty when nothing is. */
export function itemProblems(it: unknown, where: string): string[] {
  if (!isObj(it)) return [`${where} is not an object`];
  const out: string[] = [];
  if (typeof it.resource !== "string" || !it.resource) out.push(`${where}.resource is missing`);
  if (typeof it.type !== "string" || !it.type) out.push(`${where}.type is missing`);
  if (typeof it.x402Version !== "number") out.push(`${where}.x402Version is not a number`);
  if (!Array.isArray(it.accepts) || it.accepts.length === 0) out.push(`${where}.accepts is empty or missing`);
  else it.accepts.forEach((a: unknown, i: number) => out.push(...requirementProblems(a, `${where}.accepts[${i}]`)));
  if (typeof it.lastUpdated !== "string" || !ISO.test(it.lastUpdated) || isNaN(Date.parse(it.lastUpdated))) {
    out.push(`${where}.lastUpdated is not an ISO 8601 timestamp`);
  }
  if (it.extensions !== undefined && !isObj(it.extensions)) out.push(`${where}.extensions is not an object`);
  return out;
}

async function getJson(url: string, timeoutMs: number) {
  try {
    const r = await fetch(url, { headers: { accept: "application/json" }, signal: AbortSignal.timeout(timeoutMs) });
    const text = await r.text();
    let body: unknown = undefined;
    try { body = JSON.parse(text); } catch { body = undefined; }
    return { status: r.status, body, text: text.slice(0, 200) };
  } catch (e) {
    return { status: 0, body: undefined, text: String(e).slice(0, 200) };
  }
}

/** Runs D1 against a facilitator's discovery API. GET only. */
export async function checkDiscovery(facilitatorUrl: string, opts: DiscoveryOptions = {}): Promise<Result[]> {
  const t = opts.timeoutMs ?? 15_000;
  const base = facilitatorUrl.replace(/\/+$/, "");
  const limit = 2;
  const list = await getJson(`${base}/discovery/resources?limit=${limit}`, t);
  const search = await getJson(`${base}/discovery/search?query=${encodeURIComponent(opts.query ?? "weather")}&limit=${limit}`, t);
  // Not served: a 4xx or 501. A 5xx is a broken endpoint, not an absent one.
  const absent = (st: number) => (st >= 400 && st < 500) || st === 501;
  if (absent(list.status) && absent(search.status)) {
    return [{ check: D1, pass: false, status: "unsupported", detail: { resources_status: list.status,
      search_status: search.status, note: "the facilitator serves no discovery endpoints; they are optional" } }];
  }
  const errors: string[] = [];
  const detail: Record<string, unknown> = { resources_status: list.status, search_status: search.status };
  // GET /discovery/resources
  const lb: any = list.body;
  if (list.status !== 200 || !isObj(lb)) errors.push(`/discovery/resources answered ${list.status} without a JSON object`);
  else {
    if (lb.x402Version !== 2) errors.push(`/discovery/resources x402Version is ${JSON.stringify(lb.x402Version)}, not 2`);
    if (!Array.isArray(lb.items)) errors.push("/discovery/resources has no items array");
    else {
      detail.items = lb.items.length;
      if (lb.items.length > limit) errors.push(`/discovery/resources returned ${lb.items.length} items for limit=${limit}`);
      lb.items.forEach((it: unknown, i: number) => errors.push(...itemProblems(it, `items[${i}]`)));
    }
    const p = lb.pagination;
    if (!isObj(p) || typeof p.limit !== "number" || typeof p.offset !== "number" || typeof p.total !== "number") {
      errors.push("/discovery/resources pagination lacks numeric limit, offset and total");
    }
    // the network filter: every item returned for ?network=N offers N
    const net = Array.isArray(lb.items) ? lb.items.find((x: any) => Array.isArray(x?.accepts))?.accepts?.[0]?.network : undefined;
    if (typeof net === "string") {
      const f = await getJson(`${base}/discovery/resources?network=${encodeURIComponent(net)}&limit=100`, t);
      const fi: any[] = Array.isArray((f.body as any)?.items) ? (f.body as any).items : [];
      const off = fi.filter((x) => !(x?.accepts ?? []).some((a: any) => a?.network === net)).length;
      detail.network_filter = { network: net, status: f.status, items: fi.length, off_network: off };
      if (f.status !== 200) errors.push(`/discovery/resources?network= answered ${f.status}`);
      else if (off) errors.push(`/discovery/resources?network=${net} returned ${off} item(s) that do not offer ${net}`);
    }
  }
  // GET /discovery/search
  const sb: any = search.body;
  if (absent(search.status)) detail.search = "not served (optional)";
  else if (search.status !== 200 || !isObj(sb)) errors.push(`/discovery/search answered ${search.status} without a JSON object`);
  else {
    if (sb.x402Version !== 2) errors.push(`/discovery/search x402Version is ${JSON.stringify(sb.x402Version)}, not 2`);
    if (!Array.isArray(sb.resources)) errors.push("/discovery/search has no resources array");
    else sb.resources.forEach((it: unknown, i: number) => errors.push(...itemProblems(it, `resources[${i}]`)));
    if (sb.partialResults !== undefined && typeof sb.partialResults !== "boolean") {
      errors.push("/discovery/search partialResults is not a boolean");
    }
    const p = sb.pagination;
    if (p !== undefined && p !== null && (!isObj(p) || typeof p.limit !== "number"
      || !(typeof p.cursor === "string" || p.cursor === null))) {
      errors.push("/discovery/search pagination is not null or { limit, cursor }");
    }
  }
  const pass = errors.length === 0;
  return [{ check: D1, pass, status: pass ? "pass" : "fail", detail: { ...detail, ...(pass ? {} : { error: errors.join("; ") }) } }];
}

const canon = (v: unknown): string => JSON.stringify(v, (_k, x) =>
  isObj(x) ? Object.fromEntries(Object.keys(x).sort().map((k) => [k, x[k]])) : x);

export interface A2aTarget {
  /** The agent's A2A JSON-RPC endpoint. */
  a2aUrl: string;
  /** The HTTP route the agent's paid skill mirrors. */
  httpUrl: string;
  /** The text to send; the agent's paid skill should answer it with payment-required. */
  text?: string;
}

/** Runs G1: one unpaid message/send and one unpaid GET. No payment is sent. */
export async function checkA2aMirrorsHttp(target: A2aTarget, opts: DiscoveryOptions = {}): Promise<Result[]> {
  const t = opts.timeoutMs ?? 15_000;
  const http = await fetch(target.httpUrl, { signal: AbortSignal.timeout(t) }).catch(() => null);
  let required: any = null;
  try { const h = http?.headers.get("payment-required"); required = h ? decodePaymentRequiredHeader(h) : null; }
  catch { required = null; }
  if (http?.status !== 402 || !Array.isArray(required?.accepts)) {
    return [{ check: G1, pass: false, status: "unsupported", detail: { http_status: http?.status ?? 0,
      error: "the HTTP route did not answer 402 with a PAYMENT-REQUIRED header to compare against" } }];
  }
  let answer: any = null, status = 0;
  try {
    const r = await fetch(target.a2aUrl, { method: "POST", headers: { "content-type": "application/json" },
      signal: AbortSignal.timeout(t), body: JSON.stringify({ jsonrpc: "2.0", id: "x402-conformance-g1",
        method: "message/send", params: { message: { kind: "message", role: "user", messageId: `g1-${Date.now()}`,
          parts: [{ kind: "text", text: target.text ?? "run the paid skill" }] } } }) });
    status = r.status;
    answer = await r.json().catch(() => null);
  } catch (e) { answer = { transport_error: String(e).slice(0, 200) }; }
  const errors: string[] = [];
  const task = answer?.result;
  const meta = task?.status?.message?.metadata;
  const pr = meta?.["x402.payment.required"];
  if (answer?.error) errors.push(`message/send answered a JSON-RPC error (${JSON.stringify(answer.error).slice(0, 120)})`);
  else if (!isObj(task) || task.kind !== "task") errors.push("message/send did not answer a task");
  else {
    if (task.status?.state !== "input-required") errors.push(`the task state is ${JSON.stringify(task.status?.state)}, not input-required`);
    if (meta?.["x402.payment.status"] !== "payment-required") errors.push("x402.payment.status is not payment-required");
    if (!isObj(pr)) errors.push("x402.payment.required is missing");
    else {
      if (pr.x402Version !== 2) errors.push(`x402.payment.required.x402Version is ${JSON.stringify(pr.x402Version)}, not 2`);
      if (!Array.isArray(pr.accepts) || pr.accepts.length === 0) errors.push("x402.payment.required.accepts is empty");
      else {
        pr.accepts.forEach((a: unknown, i: number) => errors.push(...requirementProblems(a, `accepts[${i}]`)));
        const httpSet = required.accepts.map(canon).sort();
        const a2aSet = pr.accepts.map(canon).sort();
        if (canon(httpSet) !== canon(a2aSet)) {
          errors.push("the A2A accepts differ from the HTTP 402's PAYMENT-REQUIRED accepts");
        }
      }
    }
  }
  const pass = errors.length === 0;
  return [{ check: G1, pass, status: pass ? "pass" : "fail", detail: { http_status: 402, a2a_status: status,
    state: task?.status?.state ?? null, http_accepts: required.accepts, a2a_accepts: pr?.accepts ?? null,
    ...(pass ? {} : { error: errors.join("; ") }) } }];
}
