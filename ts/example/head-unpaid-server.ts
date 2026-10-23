// A resource server for R16a, an unpaid HEAD gets the same 402 as GET, on @x402/core's x402HTTPResourceServer with
// the exact scheme on Solana devnet or Base Sepolia. It serves one paid route, GET /paid ($0.01), and counts how often
// its protected handler runs.
// The control matches HEAD against the GET route, so an unpaid HEAD is answered 402 with PAYMENT-REQUIRED and the
// handler never runs.
// UNPAID_HEAD_FAULT shows what R16a catches:
//   head_bypass  the paywall matches routes by the exact method, so HEAD /paid matches no paid route and the handler
//                runs for free (200, headers only)
import http from "node:http";
import type { AddressInfo } from "node:net";
import { HTTPFacilitatorClient, x402HTTPResourceServer, x402ResourceServer } from "@x402/core/server";
import type { HTTPAdapter } from "@x402/core/server";
import { ExactSvmScheme } from "@x402/svm/exact/server";
import { ExactEvmScheme } from "@x402/evm/exact/server";

export const DEVNET = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1";
export const BASE_SEPOLIA = "eip155:84532";
export const UNPAID_HEAD_FAULTS = ["head_bypass"] as const;
export type UnpaidHeadFault = "" | (typeof UNPAID_HEAD_FAULTS)[number];

export interface UnpaidHeadServer { url: string; handled: number; close(): Promise<void> }

export async function startUnpaidHeadServer(facilitatorUrl: string, fault: UnpaidHeadFault = "", network = DEVNET,
    port = 0): Promise<UnpaidHeadServer> {
  const rs = new x402ResourceServer(new HTTPFacilitatorClient({ url: facilitatorUrl, timeoutMs: 3000 }));
  const evm = network === BASE_SEPOLIA;
  if (evm) rs.register(BASE_SEPOLIA, new ExactEvmScheme());
  else rs.register(network as `${string}:${string}`, new ExactSvmScheme());
  const accepts = evm
    ? { scheme: "exact", network: BASE_SEPOLIA, payTo: "0x209693Bc6afc0C5328bA36FaF03C514EF312287C",
      price: { asset: "0x036CbD53842c5426634e7929541eC2318f3dCF7e", amount: "10000", extra: { name: "USDC", version: "2" } } }
    : { scheme: "exact", network, payTo: "11111111111111111111111111111112",
      price: { asset: "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU", amount: "10000" } };
  const app = new x402HTTPResourceServer(rs, { "GET /paid": { accepts: accepts as any, description: "head example" } });
  await app.initialize();
  const srv: UnpaidHeadServer = { url: "", handled: 0, close: async () => {} };
  const server = http.createServer(async (rq, res) => {
    const url = new URL(rq.url ?? "/", "http://127.0.0.1");
    const head = rq.method === "HEAD";
    const method = head && fault !== "head_bypass" ? "GET" : rq.method ?? "GET";
    const adapter: HTTPAdapter = {
      getHeader: (n) => { const v = rq.headers[n.toLowerCase()]; return Array.isArray(v) ? v[0] : v; },
      getMethod: () => method,
      getPath: () => url.pathname,
      getUrl: () => url.toString(),
      getAcceptHeader: () => String(rq.headers.accept ?? "application/json"),
      getUserAgent: () => String(rq.headers["user-agent"] ?? ""),
    };
    const send = (status: number, headers: Record<string, string>, body: unknown) => {
      res.writeHead(status, { "content-type": "application/json", ...headers });
      res.end(head ? undefined : JSON.stringify(body ?? {}));
    };
    const handler = (headers: Record<string, string>) => { srv.handled++; send(200, headers, { content: "paid content" }); };
    try {
      const paymentHeader = adapter.getHeader("payment-signature") ?? adapter.getHeader("x-payment");
      const r = await app.processHTTPRequest({ adapter, path: url.pathname, method, paymentHeader });
      if (r.type === "no-payment-required") {
        // The express-style router serves HEAD from the GET handler.
        return url.pathname === "/paid" ? handler({}) : send(404, {}, { error: "not found" });
      }
      if (r.type === "payment-error") return send(r.response.status, r.response.headers, r.response.body);
      if (head) return send(402, {}, { error: "a HEAD request is not settled; retry as GET to pay" });
      const s = await app.processSettlement(r.paymentPayload, r.paymentRequirements, r.declaredExtensions).catch(() => null);
      if (!s?.success) return send(402, {}, { error: "settlement failed" });
      return handler(s.headers);
    } catch (e) {
      send(500, {}, { error: String(e).slice(0, 200) });
    }
  });
  await new Promise<void>((ok) => server.listen(port, "127.0.0.1", ok));
  srv.url = `http://127.0.0.1:${(server.address() as AddressInfo).port}/paid`;
  srv.close = () => new Promise((ok) => { server.closeAllConnections(); server.close(() => ok()); });
  return srv;
}
