// C3, a client offered V2 keeps V2. A recording proxy in front of a paid route makes the route's 402 offer both
// versions: the route's own V2 PAYMENT-REQUIRED header, and a V1 PaymentRequired JSON body (V1 5.1) for the same offer,
// with the V1 network name, maxAmountRequired, resource and description. The client passes when it pays with
// PAYMENT-SIGNATURE at x402Version 2. It fails when it pays with X-PAYMENT or at x402Version 1, or never pays. Only a V2
// payment is forwarded to the route, so a V1 payment never reaches /settle.
import http from "node:http";
import type { AddressInfo } from "node:net";
import { decodePaymentRequiredHeader, decodePaymentSignatureHeader } from "@x402/core/http";
import { BASE_SEPOLIA, DEVNET, type Double } from "./double.js";
import type { Result } from "./probe.js";
import { notApplicable, type ClientSigningOptions } from "./client-offers.js";

export const C3 = "C3 client: when a 402 offers V2 and V1, the client pays with V2 and never falls back to V1";

/** V1 network names for the V2 networks the suite runs on (V1 used names, not CAIP-2). */
export const V1_NAMES: Record<string, string> = { [DEVNET]: "solana-devnet", [BASE_SEPOLIA]: "base-sepolia" };

/** A client under test: it fetches `url`, pays the 402 by its own policy and returns the final response. */
export type VersionClient = (url: string) => Promise<Response>;

/** The V2 PaymentRequired `required` as a V1 PaymentRequired body: the same offer in V1 fields. */
export function v1Body(required: any): Record<string, unknown> {
  const r = required?.resource ?? {};
  return { x402Version: 1, error: "X-PAYMENT header is required",
    accepts: (required?.accepts ?? []).map((a: any) => ({ scheme: a.scheme, network: V1_NAMES[a.network] ?? a.network,
      maxAmountRequired: a.amount, asset: a.asset, payTo: a.payTo, resource: String(r.url ?? ""),
      description: String(r.description ?? ""), mimeType: String(r.mimeType ?? "application/json"),
      maxTimeoutSeconds: a.maxTimeoutSeconds, extra: a.extra ?? {} })) };
}

const res = (pass: boolean, detail: unknown): Result => ({ check: C3, pass, status: pass ? "pass" : "fail", detail });

/** C3. Puts a recording proxy in front of `url` (a paid route behind `double`) that adds a V1 body to each 402 with a
 * V2 offer, runs the client through it, and reads which version the client paid with. */
export async function checkClientKeepsV2(client: VersionClient, url: string, double: Double, opts: ClientSigningOptions = {}): Promise<Result> {
  const target = new URL(url);
  const paid: { header: "PAYMENT-SIGNATURE" | "X-PAYMENT"; x402Version: number | null; forwarded: boolean }[] = [];
  const offered = { v2_header: false, v1_body: false };
  const version = (h: string): number | null => {
    try {
      const v = (decodePaymentSignatureHeader(h) as any)?.x402Version;
      return typeof v === "number" ? v : null;
    } catch { return null; }
  };
  const proxy = http.createServer(async (rq, rs) => {
    const headers: Record<string, string> = {};
    for (const [k, v] of Object.entries(rq.headers)) if (typeof v === "string" && k !== "host") headers[k] = v;
    const sig = headers["payment-signature"];
    const xp = headers["x-payment"];
    if (sig !== undefined) paid.push({ header: "PAYMENT-SIGNATURE", x402Version: version(sig), forwarded: false });
    if (xp !== undefined) paid.push({ header: "X-PAYMENT", x402Version: version(xp), forwarded: false });
    if (sig !== undefined || xp !== undefined) {
      // Only a V2 payment goes to the route. Anything else is refused here, with no new offer, so it is never settled.
      if (xp !== undefined || paid[paid.length - 1].x402Version !== 2) {
        rs.writeHead(402, { "content-type": "application/json" });
        rs.end(JSON.stringify({ error: "not forwarded: the suite forwards only a V2 payment when a V2 offer is present" }));
        return;
      }
      paid[paid.length - 1].forwarded = true;
    }
    try {
      const up = await fetch(new URL(rq.url ?? "/", target), { headers });
      const out: Record<string, string> = {};
      up.headers.forEach((v, k) => { if (k !== "content-length" && k !== "transfer-encoding") out[k] = v; });
      let body: Buffer = Buffer.from(await up.arrayBuffer());
      const h = up.headers.get("payment-required");
      let required: any = null;
      try { required = up.status === 402 && h ? decodePaymentRequiredHeader(h) : null; } catch { required = null; }
      if (Array.isArray(required?.accepts) && required.accepts.length) {
        offered.v2_header = true;
        offered.v1_body = true;
        body = Buffer.from(JSON.stringify(v1Body(required)));
        out["content-type"] = "application/json";
      }
      rs.writeHead(up.status, out);
      rs.end(body);
    } catch (e) {
      if (!rs.headersSent) rs.writeHead(502);
      rs.end(String(e));
    }
  });
  await new Promise<void>((ok) => proxy.listen(0, "127.0.0.1", ok));
  const front = `http://127.0.0.1:${(proxy.address() as AddressInfo).port}${target.pathname}${target.search}`;
  double.mode = "reference";
  double.settleDelayMs = 0;
  const before = double.successes.length;
  let finalStatus = 0;
  let thrown: string | undefined;
  try {
    const r = await client(front);
    finalStatus = r.status;
    await r.text().catch(() => "");
  } catch (e) { thrown = String(e); }
  await new Promise<void>((ok) => { proxy.closeAllConnections(); proxy.close(() => ok()); });
  if (opts.signsPayments === false && paid.length === 0 && offered.v2_header) return notApplicable(C3, finalStatus, thrown);
  const v1 = paid.find((p) => p.header === "X-PAYMENT" || p.x402Version !== 2);
  const v2 = paid.find((p) => p.header === "PAYMENT-SIGNATURE" && p.x402Version === 2);
  const shown = v1 ?? v2;
  let error: string | undefined;
  if (!offered.v2_header) error = "the route did not answer 402 with a V2 offer in PAYMENT-REQUIRED, so nothing was graded";
  else if (v1) error = `the client paid with ${v1.header} at x402Version ${v1.x402Version ?? "unknown"} although a V2 `
    + "offer was present";
  else if (!v2) error = thrown ?? "the client never paid";
  return res(!error, { offered, header: shown?.header ?? null, x402_version: shown?.x402Version ?? null,
    paid_requests: paid.length, forwarded: paid.filter((p) => p.forwarded).length, final_status: finalStatus,
    successful_settles: double.successes.length - before, ...(error ? { error } : {}) });
}
