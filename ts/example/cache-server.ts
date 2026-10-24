// A resource server for R17, cache leakage, on @x402/core's x402HTTPResourceServer with the exact scheme on Solana
// devnet or Base Sepolia. One paid GET route, /paid ($0.01), and /free, which is not paid. The control marks every paid
// response Cache-Control: private, no-store, so a shared cache in front of it never hands the content to the next
// caller. CACHE_FAULT shows what R17 catches:
//   cache_public      the paid response says Cache-Control: public, max-age=60
//   no_cache_headers  the paid response says nothing about caching, so a shared cache may store it heuristically
import http from "node:http";
import type { AddressInfo } from "node:net";
import { HTTPFacilitatorClient, x402HTTPResourceServer, x402ResourceServer } from "@x402/core/server";
import type { HTTPAdapter } from "@x402/core/server";
import { ExactSvmScheme } from "@x402/svm/exact/server";
import { ExactEvmScheme } from "@x402/evm/exact/server";

export const DEVNET = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1";
export const BASE_SEPOLIA = "eip155:84532";
export const CACHE_FAULTS = ["cache_public", "no_cache_headers"] as const;
export type CacheFault = "" | (typeof CACHE_FAULTS)[number];

export interface CacheServer { base: string; url: string; close(): Promise<void>; handled: number }

export async function startCacheServer(facilitatorUrl: string, fault: CacheFault = "", network = DEVNET,
    port = 0): Promise<CacheServer> {
  const rs = new x402ResourceServer(new HTTPFacilitatorClient({ url: facilitatorUrl, timeoutMs: 3000 }));
  const evm = network === BASE_SEPOLIA;
  if (evm) rs.register(BASE_SEPOLIA, new ExactEvmScheme());
  else rs.register(network as `${string}:${string}`, new ExactSvmScheme());
  const accepts = evm
    ? { scheme: "exact", network: BASE_SEPOLIA, payTo: "0x209693Bc6afc0C5328bA36FaF03C514EF312287C",
      price: { asset: "0x036CbD53842c5426634e7929541eC2318f3dCF7e", amount: "10000", extra: { name: "USDC", version: "2" } } }
    : { scheme: "exact", network, payTo: "11111111111111111111111111111112",
      price: { asset: "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU", amount: "10000" } };
  const app = new x402HTTPResourceServer(rs, { "GET /paid": { accepts, description: "cache example" } } as any);
  await app.initialize();
  const caching: Record<string, string> = fault === "cache_public" ? { "cache-control": "public, max-age=60" }
    : fault === "no_cache_headers" ? {} : { "cache-control": "private, no-store" };
  const out = { handled: 0 };
  const server = http.createServer(async (rq, res) => {
    const url = new URL(rq.url ?? "/", "http://127.0.0.1");
    const send = (status: number, headers: Record<string, string>, body: unknown) => {
      res.writeHead(status, { "content-type": "application/json", ...headers });
      res.end(JSON.stringify(body));
    };
    if (url.pathname === "/free") return send(200, caching, { content: "free" });
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
      out.handled++;
      const s = await app.processSettlement(r.paymentPayload, r.paymentRequirements, r.declaredExtensions);
      if (!s?.success) return send(402, {}, { error: "settlement failed" });
      return send(200, { ...s.headers, ...caching }, { content: "paid content", serial: out.handled });
    } catch (e) {
      send(500, {}, { error: String(e).slice(0, 200) });
    }
  });
  await new Promise<void>((ok) => server.listen(port, "127.0.0.1", ok));
  const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  return { base, url: `${base}/paid`, get handled() { return out.handled; },
    close: () => new Promise((ok) => { server.closeAllConnections(); server.close(() => ok()); }) };
}
