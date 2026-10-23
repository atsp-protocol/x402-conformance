// A resource server for the paid-response status check. Two paid GET routes:
//   /created   the handler answers 201 with a Location
//   /accepted  the handler answers 202 with a Content-Location
// The control settles, then sends the handler's own status and headers.
// STATUS_FAULT rewrite_200 settles, then answers 200 and drops the handler's headers.
import http from "node:http";
import type { AddressInfo } from "node:net";
import { HTTPFacilitatorClient, x402HTTPResourceServer, x402ResourceServer } from "@x402/core/server";
import type { HTTPAdapter } from "@x402/core/server";
import { ExactSvmScheme } from "@x402/svm/exact/server";
import { ExactEvmScheme } from "@x402/evm/exact/server";

export const DEVNET = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1";
export const BASE_SEPOLIA = "eip155:84532";
export const STATUS_FAULTS = ["rewrite_200"] as const;
export type StatusFault = "" | (typeof STATUS_FAULTS)[number];

interface Out { status: number; headers: Record<string, string>; body: unknown }

const HANDLERS: Record<string, () => Out> = {
  "/created": () => ({ status: 201, headers: { location: "/created/1" }, body: { created: "/created/1" } }),
  "/accepted": () => ({ status: 202, headers: { "content-location": "/jobs/1" }, body: { job: "/jobs/1" } }),
};

export interface StatusServer { base: string; close(): Promise<void>; handled: Record<string, number> }

export async function startStatusServer(facilitatorUrl: string, fault: StatusFault = "", network = DEVNET,
    port = 0): Promise<StatusServer> {
  const rs = new x402ResourceServer(new HTTPFacilitatorClient({ url: facilitatorUrl, timeoutMs: 3000 }));
  const evm = network === BASE_SEPOLIA;
  if (evm) rs.register(BASE_SEPOLIA, new ExactEvmScheme());
  else rs.register(network as `${string}:${string}`, new ExactSvmScheme());
  const accepts = evm
    ? { scheme: "exact", network: BASE_SEPOLIA, payTo: "0x209693Bc6afc0C5328bA36FaF03C514EF312287C",
      price: { asset: "0x036CbD53842c5426634e7929541eC2318f3dCF7e", amount: "10000", extra: { name: "USDC", version: "2" } } }
    : { scheme: "exact", network, payTo: "11111111111111111111111111111112",
      price: { asset: "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU", amount: "10000" } };
  const routes: Record<string, unknown> = {};
  for (const p of Object.keys(HANDLERS)) routes[`GET ${p}`] = { accepts, description: "paid response status" };
  const app = new x402HTTPResourceServer(rs, routes as any);
  await app.initialize();
  const handled: Record<string, number> = {};
  const server = http.createServer(async (rq, res) => {
    const url = new URL(rq.url ?? "/", "http://127.0.0.1");
    const adapter: HTTPAdapter = {
      getHeader: (n) => { const v = rq.headers[n.toLowerCase()]; return Array.isArray(v) ? v[0] : v; },
      getMethod: () => rq.method ?? "GET",
      getPath: () => url.pathname,
      getUrl: () => url.toString(),
      getAcceptHeader: () => String(rq.headers.accept ?? "application/json"),
      getUserAgent: () => String(rq.headers["user-agent"] ?? ""),
    };
    const send = (o: Out) => {
      res.writeHead(o.status, { "content-type": "application/json", ...o.headers });
      res.end(JSON.stringify(o.body ?? {}));
    };
    try {
      const paymentHeader = adapter.getHeader("payment-signature") ?? adapter.getHeader("x-payment");
      const r = await app.processHTTPRequest({ adapter, path: url.pathname, method: adapter.getMethod(), paymentHeader });
      if (r.type === "no-payment-required") return send({ status: 404, headers: {}, body: { error: "not found" } });
      if (r.type === "payment-error") return send({ status: r.response.status, headers: r.response.headers, body: r.response.body });
      handled[url.pathname] = (handled[url.pathname] ?? 0) + 1;
      const o = HANDLERS[url.pathname]();
      let settled: { headers?: Record<string, string>; success?: boolean } | null = null;
      try { settled = await app.processSettlement(r.paymentPayload, r.paymentRequirements, r.declaredExtensions); }
      catch { settled = null; }
      if (!settled?.success) return send({ status: 402, headers: {}, body: { error: "settlement failed" } });
      if (fault === "rewrite_200") {
        return send({ status: 200, headers: { ...(settled.headers ?? {}) }, body: o.body });
      }
      return send({ status: o.status, headers: { ...o.headers, ...(settled.headers ?? {}) }, body: o.body });
    } catch (e) {
      send({ status: 500, headers: {}, body: { error: String(e).slice(0, 200) } });
    }
  });
  await new Promise<void>((ok) => server.listen(port, "127.0.0.1", ok));
  const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  return { base, handled, close: () => new Promise((ok) => { server.closeAllConnections(); server.close(() => ok()); }) };
}
