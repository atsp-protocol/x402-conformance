// A resource server for R16, a paid HEAD is never settled, on @x402/core's x402HTTPResourceServer with the exact
// scheme on Solana devnet or Base Sepolia. It serves one paid route, GET /paid ($0.01).
// The control matches HEAD against the GET route (so HEAD is never a way round the paywall) and, when a HEAD carries
// a payment, answers 402 asking the client to retry as GET, without calling /verify or /settle: a HEAD response
// carries no content (RFC 9110 9.3.2), so there is nothing to deliver for the payment.
// HEAD_FAULT shows what R16 catches:
//   head_settles  a HEAD carrying a payment is processed as a GET: verified, settled and answered 200 with no body
import http from "node:http";
import type { AddressInfo } from "node:net";
import { HTTPFacilitatorClient, x402HTTPResourceServer, x402ResourceServer } from "@x402/core/server";
import type { HTTPAdapter } from "@x402/core/server";
import { ExactSvmScheme } from "@x402/svm/exact/server";
import { ExactEvmScheme } from "@x402/evm/exact/server";

export const DEVNET = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1";
export const BASE_SEPOLIA = "eip155:84532";
export const HEAD_FAULTS = ["head_settles"] as const;
export type HeadFault = "" | (typeof HEAD_FAULTS)[number];

export interface HeadServer { url: string; handled: { GET: number; HEAD: number }; close(): Promise<void> }

export async function startHeadServer(facilitatorUrl: string, fault: HeadFault = "", network = DEVNET, port = 0): Promise<HeadServer> {
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
  const handled = { GET: 0, HEAD: 0 };
  const server = http.createServer(async (rq, res) => {
    const url = new URL(rq.url ?? "/", "http://127.0.0.1");
    const head = rq.method === "HEAD";
    // HEAD is matched as GET, so the route's price and paywall apply to it.
    const method = head ? "GET" : rq.method ?? "GET";
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
    try {
      const paymentHeader = adapter.getHeader("payment-signature") ?? adapter.getHeader("x-payment");
      if (head && paymentHeader && fault !== "head_settles") {
        // Refuse before /verify: nothing is delivered for a HEAD, so nothing may be charged.
        const unpaid = await app.processHTTPRequest({ adapter: { ...adapter, getHeader: (n) => /payment/i.test(n) ? undefined : adapter.getHeader(n) },
          path: url.pathname, method, paymentHeader: undefined });
        const h = unpaid.type === "payment-error" ? unpaid.response.headers : {};
        return send(402, h, { error: "a HEAD request is not settled; retry as GET to pay" });
      }
      const r = await app.processHTTPRequest({ adapter, path: url.pathname, method, paymentHeader });
      if (r.type === "no-payment-required") return send(404, {}, { error: "not found" });
      if (r.type === "payment-error") return send(r.response.status, r.response.headers, r.response.body);
      const s = await app.processSettlement(r.paymentPayload, r.paymentRequirements, r.declaredExtensions).catch(() => null);
      if (!s?.success) return send(402, {}, { error: "settlement failed" });
      handled[head ? "HEAD" : "GET"]++;
      return send(200, s.headers, { content: "paid content" });
    } catch (e) {
      send(500, {}, { error: String(e).slice(0, 200) });
    }
  });
  await new Promise<void>((ok) => server.listen(port, "127.0.0.1", ok));
  const url = `http://127.0.0.1:${(server.address() as AddressInfo).port}/paid`;
  return { url, handled, close: () => new Promise((ok) => { server.closeAllConnections(); server.close(() => ok()); }) };
}
