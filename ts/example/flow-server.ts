// A resource server for R19, upfront and escrow flows, on @x402/core's x402HTTPResourceServer with the exact scheme on
// Solana devnet or Base Sepolia. Two paid GET routes ($0.01): /upfront, whose offer declares extra.paymentFlow
// "upfront" so the SDK settles before the handler runs, and /authorization, a plain route for the gate; plus /free.
// The control lets the SDK run the check, runs the handler only on payment-verified, and echoes the before-handler
// settlement. FLOW_FAULT shows what R19 catches:
//   execute_first    runs the handler before any facilitator call, then checks
//   accept_any_flow  rewrites the flow the client signed for to the route's own before the check, so a payment for a
//                    flow the route never offered is settled and served
import http from "node:http";
import type { AddressInfo } from "node:net";
import { HTTPFacilitatorClient, x402HTTPResourceServer, x402ResourceServer } from "@x402/core/server";
import type { HTTPAdapter } from "@x402/core/server";
import { decodePaymentSignatureHeader, encodePaymentSignatureHeader } from "@x402/core/http";
import { ExactSvmScheme } from "@x402/svm/exact/server";
import { ExactEvmScheme } from "@x402/evm/exact/server";

export const DEVNET = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1";
export const BASE_SEPOLIA = "eip155:84532";
export const FLOW_FAULTS = ["execute_first", "accept_any_flow"] as const;
export type FlowFault = "" | (typeof FLOW_FAULTS)[number];

export interface FlowServer { base: string; close(): Promise<void>; handled: Record<string, number> }

export async function startFlowServer(facilitatorUrl: string, fault: FlowFault = "", network = DEVNET,
    port = 0): Promise<FlowServer> {
  const rs = new x402ResourceServer(new HTTPFacilitatorClient({ url: facilitatorUrl, timeoutMs: 3000 }));
  const evm = network === BASE_SEPOLIA;
  if (evm) rs.register(BASE_SEPOLIA, new ExactEvmScheme());
  else rs.register(network as `${string}:${string}`, new ExactSvmScheme());
  const offer = (flow?: string) => {
    const extra = { ...(evm ? { name: "USDC", version: "2" } : {}), ...(flow ? { paymentFlow: flow } : {}) };
    return evm
      ? { scheme: "exact", network: BASE_SEPOLIA, payTo: "0x209693Bc6afc0C5328bA36FaF03C514EF312287C",
        price: { asset: "0x036CbD53842c5426634e7929541eC2318f3dCF7e", amount: "10000", extra } }
      : { scheme: "exact", network, payTo: "11111111111111111111111111111112",
        price: { asset: "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU", amount: "10000", extra } };
  };
  const routes = { "GET /upfront": { accepts: offer("upfront"), description: "upfront example" },
    "GET /authorization": { accepts: offer(), description: "authorization example" } };
  const app = new x402HTTPResourceServer(rs, routes as any);
  await app.initialize();
  const handled: Record<string, number> = { "/upfront": 0, "/authorization": 0 };
  const run = (path: string) => { handled[path] = (handled[path] ?? 0) + 1; return { content: "paid content", serial: handled[path] }; };
  const server = http.createServer(async (rq, res) => {
    const url = new URL(rq.url ?? "/", "http://127.0.0.1");
    const send = (status: number, headers: Record<string, string>, body: unknown) => {
      res.writeHead(status, { "content-type": "application/json", ...headers });
      res.end(JSON.stringify(body));
    };
    if (url.pathname === "/free") return send(200, {}, { content: "free" });
    if (!(url.pathname in handled)) return send(404, {}, { error: "not found" });
    // accept_any_flow: the flow the client signed for is rewritten to the route's own before the SDK reads the header.
    let rewritten: string | undefined;
    const incoming = rq.headers["payment-signature"];
    if (fault === "accept_any_flow" && typeof incoming === "string" && url.pathname === "/upfront") {
      try {
        const p: any = decodePaymentSignatureHeader(incoming);
        p.accepted = { ...p.accepted, extra: { ...(p.accepted?.extra ?? {}), paymentFlow: "upfront" } };
        rewritten = encodePaymentSignatureHeader(p);
      } catch { /* the SDK answers a header it cannot decode */ }
    }
    const adapter: HTTPAdapter = {
      getHeader: (n) => {
        if (rewritten && n.toLowerCase() === "payment-signature") return rewritten;
        const v = rq.headers[n.toLowerCase()];
        return Array.isArray(v) ? v[0] : v;
      },
      getMethod: () => rq.method ?? "GET",
      getPath: () => url.pathname,
      getUrl: () => url.toString(),
      getAcceptHeader: () => String(rq.headers.accept ?? "application/json"),
      getUserAgent: () => String(rq.headers["user-agent"] ?? ""),
    };
    try {
      const paymentHeader = adapter.getHeader("payment-signature") ?? adapter.getHeader("x-payment");
      const early = fault === "execute_first" && paymentHeader ? run(url.pathname) : null;
      const r: any = await app.processHTTPRequest({ adapter, path: url.pathname, method: adapter.getMethod(), paymentHeader });
      if (r.type === "no-payment-required") return send(404, {}, { error: "not found" });
      if (r.type === "payment-error") return send(r.response.status, r.response.headers, r.response.body);
      const body = early ?? run(url.pathname);
      const s = await app.processSettlement(r.paymentPayload, r.paymentRequirements, r.declaredExtensions, undefined, undefined,
        r.beforeHandlerSettlement);
      if (!s?.success) return send(402, {}, { error: String((s as any)?.errorReason ?? "settlement failed") });
      return send(200, s.headers ?? {}, body);
    } catch (e) {
      send(500, {}, { error: String(e).slice(0, 200) });
    }
  });
  await new Promise<void>((ok) => server.listen(port, "127.0.0.1", ok));
  const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  return { base, handled, close: () => new Promise((ok) => { server.closeAllConnections(); server.close(() => ok()); }) };
}
