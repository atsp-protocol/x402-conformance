// A resource server for R15, no settlement when the paid handler fails, on @x402/core's x402HTTPResourceServer with
// the exact scheme on Solana devnet or Base Sepolia. Four paid GET routes ($0.01 each):
//   /ok      the handler answers 200 (the control)
//   /fail    the handler answers 500
//   /moved   the handler answers 302 with a Location
//   /throws  the handler throws
// The control runs the handler first and settles only when it answered 2xx, so a failed, redirected or thrown request
// is never charged (V2 6.1: in the authorization flow funds move only after the resource completes successfully).
// DELIVERY_FAULT shows what R15 catches:
//   settle_first      settles once /verify passes, then runs the handler (serve-after-settle)
//   settle_below_400  runs the handler first but settles anything below 400, so a redirect is charged
import http from "node:http";
import type { AddressInfo } from "node:net";
import { HTTPFacilitatorClient, x402HTTPResourceServer, x402ResourceServer } from "@x402/core/server";
import type { HTTPAdapter } from "@x402/core/server";
import { ExactSvmScheme } from "@x402/svm/exact/server";
import { ExactEvmScheme } from "@x402/evm/exact/server";

export const DEVNET = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1";
export const BASE_SEPOLIA = "eip155:84532";
export const DELIVERY_FAULTS = ["settle_first", "settle_below_400"] as const;
export type DeliveryFault = "" | (typeof DELIVERY_FAULTS)[number];

interface Out { status: number; headers: Record<string, string>; body: unknown }

const HANDLERS: Record<string, () => Out> = {
  "/ok": () => ({ status: 200, headers: {}, body: { content: "paid content" } }),
  "/fail": () => ({ status: 500, headers: {}, body: { error: "the handler failed" } }),
  "/moved": () => ({ status: 302, headers: { location: "/ok" }, body: { moved: "/ok" } }),
  "/throws": () => { throw new Error("the handler threw"); },
};

export interface DeliveryServer { base: string; close(): Promise<void>; handled: Record<string, number> }

export async function startDeliveryServer(facilitatorUrl: string, fault: DeliveryFault = "", network = DEVNET,
    port = 0): Promise<DeliveryServer> {
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
  for (const p of Object.keys(HANDLERS)) routes[`GET ${p}`] = { accepts, description: "delivery example" };
  const app = new x402HTTPResourceServer(rs, routes as any);
  await app.initialize();
  const handled: Record<string, number> = {};
  const run = (path: string): Out => {
    handled[path] = (handled[path] ?? 0) + 1;
    try { return HANDLERS[path](); } catch (e) { return { status: 500, headers: {}, body: { error: String(e).slice(0, 100) } }; }
  };
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
      const settle = async () => {
        try { return await app.processSettlement(r.paymentPayload, r.paymentRequirements, r.declaredExtensions); } catch { return null; }
      };
      if (fault === "settle_first") {
        const s = await settle();
        if (!s?.success) return send({ status: 402, headers: {}, body: { error: "settlement failed" } });
        const o = run(url.pathname);
        return send({ ...o, headers: { ...o.headers, ...s.headers } });
      }
      const o = run(url.pathname);
      const charge = fault === "settle_below_400" ? o.status < 400 : o.status >= 200 && o.status < 300;
      if (!charge) return send(o);
      const s = await settle();
      if (!s?.success) return send({ status: 402, headers: {}, body: { error: "settlement failed" } });
      return send({ ...o, headers: { ...o.headers, ...s.headers } });
    } catch (e) {
      send({ status: 500, headers: {}, body: { error: String(e).slice(0, 200) } });
    }
  });
  await new Promise<void>((ok) => server.listen(port, "127.0.0.1", ok));
  const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  return { base, handled, close: () => new Promise((ok) => { server.closeAllConnections(); server.close(() => ok()); }) };
}
