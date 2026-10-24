// A resource server for R18, a pending, late or unanswered settlement, on @x402/core's x402HTTPResourceServer with the
// exact scheme on Solana devnet or Base Sepolia. One paid GET route, /paid ($0.01), and /free. The control answers a
// settlement_pending with 402 that names the transaction and asks the client to retry the same payment, answers a
// lost settle with 402 that names the payment, serves once when the facilitator reports success, and replays that
// result from its record when the facilitator then reports a duplicate. PENDING_FAULT shows what R18 catches:
//   serve_on_pending  treats settlement_pending as success and serves the content
//   swallow_pending   answers a pending, lost or duplicate settlement with a bare 402 that names nothing
import http from "node:http";
import type { AddressInfo } from "node:net";
import { HTTPFacilitatorClient, x402HTTPResourceServer, x402ResourceServer } from "@x402/core/server";
import type { HTTPAdapter } from "@x402/core/server";
import { ExactSvmScheme } from "@x402/svm/exact/server";
import { ExactEvmScheme } from "@x402/evm/exact/server";
import { paymentRef } from "../src/crash.js";

export const DEVNET = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1";
export const BASE_SEPOLIA = "eip155:84532";
export const PENDING_FAULTS = ["serve_on_pending", "swallow_pending"] as const;
export type PendingFault = "" | (typeof PENDING_FAULTS)[number];

export interface PendingServer { base: string; url: string; close(): Promise<void>; served: number }

interface Delivered { headers: Record<string, string>; body: unknown }

export async function startPendingServer(facilitatorUrl: string, fault: PendingFault = "", network = DEVNET,
    port = 0): Promise<PendingServer> {
  const rs = new x402ResourceServer(new HTTPFacilitatorClient({ url: facilitatorUrl, timeoutMs: 3000 }));
  const evm = network === BASE_SEPOLIA;
  if (evm) rs.register(BASE_SEPOLIA, new ExactEvmScheme());
  else rs.register(network as `${string}:${string}`, new ExactSvmScheme());
  const accepts = evm
    ? { scheme: "exact", network: BASE_SEPOLIA, payTo: "0x209693Bc6afc0C5328bA36FaF03C514EF312287C",
      price: { asset: "0x036CbD53842c5426634e7929541eC2318f3dCF7e", amount: "10000", extra: { name: "USDC", version: "2" } } }
    : { scheme: "exact", network, payTo: "11111111111111111111111111111112",
      price: { asset: "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU", amount: "10000" } };
  const app = new x402HTTPResourceServer(rs, { "GET /paid": { accepts, description: "pending example" } } as any);
  await app.initialize();
  // What each payment got, keyed by the payment itself, so a retry after success is replayed and never charged again.
  const delivered = new Map<string, Delivered>();
  const out = { served: 0 };
  const server = http.createServer(async (rq, res) => {
    const url = new URL(rq.url ?? "/", "http://127.0.0.1");
    const send = (status: number, headers: Record<string, string>, body: unknown) => {
      res.writeHead(status, { "content-type": "application/json", ...headers });
      res.end(JSON.stringify(body));
    };
    const refuse = (reason: string, surfaced: Record<string, unknown>) =>
      send(402, fault === "swallow_pending" ? {} : { "retry-after": "1" },
        fault === "swallow_pending" ? { error: "payment failed" } : { error: reason, ...surfaced, retry: "resend the same payment" });
    if (url.pathname === "/free") return send(200, {}, { content: "free" });
    if (url.pathname !== "/paid") return send(404, {}, { error: "not found" });
    const adapter: HTTPAdapter = {
      getHeader: (n) => { const v = rq.headers[n.toLowerCase()]; return Array.isArray(v) ? v[0] : v; },
      getMethod: () => rq.method ?? "GET",
      getPath: () => url.pathname,
      getUrl: () => url.toString(),
      getAcceptHeader: () => String(rq.headers.accept ?? "application/json"),
      getUserAgent: () => String(rq.headers["user-agent"] ?? ""),
    };
    try {
      const paymentHeader = adapter.getHeader("payment-signature") ?? adapter.getHeader("x-payment");
      const r = await app.processHTTPRequest({ adapter, path: url.pathname, method: adapter.getMethod(), paymentHeader });
      if (r.type === "no-payment-required") return send(404, {}, { error: "not found" });
      if (r.type === "payment-error") return send(r.response.status, r.response.headers, r.response.body);
      const key = paymentRef(r.paymentPayload.payload);
      const hit = delivered.get(key);
      if (hit) return send(200, hit.headers, { ...(hit.body as object), replayed: true });
      let s: any;
      try { s = await app.processSettlement(r.paymentPayload, r.paymentRequirements, r.declaredExtensions); } catch (e) {
        s = { success: false, errorReason: `unanswered: ${String(e).slice(0, 60)}`, transaction: "" };
      }
      const reason = String(s?.errorReason ?? "");
      if (!s?.success) {
        if (fault === "serve_on_pending" && reason === "settlement_pending") {
          out.served++;
          return send(200, {}, { content: "paid content", serial: out.served, transaction: s.transaction });
        }
        if (reason === "settlement_pending") return refuse(reason, { transaction: s.transaction });
        // A duplicate with no record of a delivery, or no answer at all: name the payment so the client can reconcile.
        return refuse(reason || "settlement failed", { payment: key, ...(s?.transaction ? { transaction: s.transaction } : {}) });
      }
      out.served++;
      const body = { content: "paid content", serial: out.served, transaction: s.transaction };
      delivered.set(key, { headers: s.headers ?? {}, body });
      return send(200, s.headers ?? {}, body);
    } catch (e) {
      send(500, {}, { error: String(e).slice(0, 200) });
    }
  });
  await new Promise<void>((ok) => server.listen(port, "127.0.0.1", ok));
  const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  return { base, url: `${base}/paid`, get served() { return out.served; },
    close: () => new Promise((ok) => { server.closeAllConnections(); server.close(() => ok()); }) };
}
