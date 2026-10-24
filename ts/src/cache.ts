// R17, cache leakage. A shared cache on loopback sits between the probe and the paid route. The probe pays through it,
// then sends an unpaid GET for the same URL through it. The unpaid request must get 402: a paid response has to be
// marked Cache-Control: private or no-store, or Vary on the payment header, so no shared cache can hand it to the
// next caller. The cache does what RFC 9111 lets a shared cache do: it stores a 200 unless the response forbids it,
// with heuristic freshness when there is no Cache-Control at all, keyed by the URL and the request headers Vary names.
import http from "node:http";
import type { AddressInfo, Socket } from "node:net";
import { decodePaymentRequiredHeader, encodePaymentSignatureHeader } from "@x402/core/http";
import type { Double } from "./double.js";
import type { Result } from "./probe.js";
import { freshPayload } from "./retry.js";

export const R17 = "R17 an unpaid request for a paid URL through a shared cache gets 402: paid responses are private or "
  + "no-store, or vary on the payment header";

export interface CacheOptions { network?: string; timeoutMs?: number }

interface Entry { status: number; headers: Record<string, string>; body: Buffer; vary: Record<string, string> }

const PAYMENT_HEADERS = ["payment-signature", "x-payment"];

function directives(cacheControl: string | null): Set<string> {
  return new Set((cacheControl ?? "").toLowerCase().split(",").map((d) => d.trim().split("=")[0]).filter(Boolean));
}

/** Whether a response is marked so that a shared cache must not serve it to another caller. */
export function markedPrivate(headers: Headers): { marked: boolean; cache_control: string | null; vary: string | null } {
  const cc = headers.get("cache-control");
  const vary = headers.get("vary");
  const d = directives(cc);
  const varies = (vary ?? "").toLowerCase().split(",").map((v) => v.trim());
  const marked = d.has("no-store") || d.has("private") || varies.includes("*")
    || PAYMENT_HEADERS.some((h) => varies.includes(h));
  return { marked, cache_control: cc, vary };
}

/** A shared cache on loopback in front of `target`. */
async function startCache(target: URL) {
  const entries = new Map<string, Entry[]>();
  const sockets = new Set<Socket>();
  const server = http.createServer(async (rq, rs) => {
    const key = `${rq.method} ${rq.url}`;
    const hit = (entries.get(key) ?? []).find((e) =>
      Object.entries(e.vary).every(([h, v]) => (rq.headers[h] === undefined ? "" : String(rq.headers[h])) === v));
    if (hit) {
      rs.writeHead(hit.status, { ...hit.headers, "x-cache": "HIT" });
      return rs.end(hit.body);
    }
    const headers: Record<string, string> = {};
    for (const [k, v] of Object.entries(rq.headers)) if (typeof v === "string" && k !== "host" && k !== "connection") headers[k] = v;
    try {
      const up = await fetch(new URL(rq.url ?? "/", target), { method: rq.method, headers, redirect: "manual" });
      const body = Buffer.from(await up.arrayBuffer());
      const out: Record<string, string> = {};
      up.headers.forEach((v, k) => { if (k !== "content-length" && k !== "transfer-encoding") out[k] = v; });
      const d = directives(up.headers.get("cache-control"));
      const varyNames = (up.headers.get("vary") ?? "").toLowerCase().split(",").map((v) => v.trim()).filter(Boolean);
      const storable = rq.method === "GET" && up.status === 200 && !d.has("no-store") && !d.has("private")
        && !varyNames.includes("*");
      if (storable) {
        const vary: Record<string, string> = {};
        for (const h of varyNames) vary[h] = rq.headers[h] === undefined ? "" : String(rq.headers[h]);
        entries.set(key, [...(entries.get(key) ?? []), { status: up.status, headers: out, body, vary }]);
      }
      rs.writeHead(up.status, { ...out, "x-cache": "MISS" });
      rs.end(body);
    } catch (e) {
      rs.writeHead(502, { "content-type": "text/plain" });
      rs.end(String(e));
    }
  });
  server.on("connection", (s: Socket) => { sockets.add(s); s.on("close", () => sockets.delete(s)); });
  await new Promise<void>((ok) => server.listen(0, "127.0.0.1", ok));
  const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  return { base, close: () => new Promise<void>((ok) => { for (const s of sockets) s.destroy(); server.close(() => ok()); }) };
}

const res = (pass: boolean, status: Result["status"], detail: unknown): Result => ({ check: R17, pass, status, detail });

/** R17 against `url`, a paid GET route on a server wired to `double`. */
export async function probeCacheLeak(url: string, double: Double, opts: CacheOptions = {}): Promise<Result[]> {
  const t = opts.timeoutMs ?? 15_000;
  const target = new URL(url);
  const cache = await startCache(target);
  const front = `${cache.base}${target.pathname}${target.search}`;
  try {
    const first = await fetch(front, { signal: AbortSignal.timeout(t) }).catch(() => null);
    await first?.arrayBuffer().catch(() => null);
    const h = first?.headers.get("payment-required");
    let required: any = null;
    try { required = h ? decodePaymentRequiredHeader(h) : null; } catch { required = null; }
    const accepted = required?.accepts?.find((a: any) => a.scheme === "exact" && (!opts.network || a.network === opts.network));
    if (first?.status !== 402 || !accepted) {
      return [res(false, "unsupported", { unpaid_status: first?.status ?? null,
        error: "the route did not answer an unpaid request with 402 and an exact offer, so nothing was graded" })];
    }
    double.mode = "reference";
    const before = double.successes.length;
    const sig = encodePaymentSignatureHeader({ x402Version: 2, resource: required.resource, accepted,
      payload: freshPayload(accepted) } as any);
    const paid = await fetch(front, { headers: { "PAYMENT-SIGNATURE": sig }, signal: AbortSignal.timeout(t) });
    await paid.arrayBuffer();
    const mark = markedPrivate(paid.headers);
    const served = paid.status >= 200 && paid.status < 300;
    const after = await fetch(front, { signal: AbortSignal.timeout(t) });
    const body = await after.text();
    const fromCache = after.headers.get("x-cache") === "HIT";
    const leaked = after.status >= 200 && after.status < 300;
    const pass = served && mark.marked && after.status === 402;
    const error = !served ? `the paid request was not served (${paid.status}), so the cache had nothing to leak`
      : leaked ? `an unpaid request for the same URL got ${after.status}${fromCache ? " from the cache" : ""}: the paid response leaked`
        : !mark.marked ? "the paid response is not marked private or no-store and does not vary on the payment header, so a "
          + "shared cache may store it"
          : after.status !== 402 ? `the unpaid request after the paid one got ${after.status}, not 402` : undefined;
    return [res(pass, pass ? "pass" : "fail", { network: accepted.network, charged: double.successes.length - before,
      paid: { status: paid.status, ...mark },
      unpaid_after: { status: after.status, from_cache: fromCache, ...(leaked ? { body: body.slice(0, 120) } : {}) },
      ...(error ? { error } : {}) })];
  } finally { await cache.close(); }
}
