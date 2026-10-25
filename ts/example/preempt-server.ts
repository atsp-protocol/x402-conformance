// A resource server for R21, settlement preemption, on @x402/core's x402HTTPResourceServer with the exact scheme on
// Base Sepolia. One paid GET route, /paid ($0.01), whose offer declares extra.assetTransferMethod "permit2", plus /free.
// The control serves only when its own /settle succeeded and refuses with the facilitator's reason otherwise.
// PREEMPT_FAULT shows what R21 catches:
//   nonce_used_is_paid   reads permit2_invalid_nonce as "already paid" and serves: it grants on a settlement a third
//                        party made, and grants a spent payment again
//   serve_before_settle  serves once /verify passes and settles afterwards, whatever the settle answers
import http from "node:http";
import type { AddressInfo } from "node:net";
import { HTTPFacilitatorClient, x402HTTPResourceServer, x402ResourceServer } from "@x402/core/server";
import type { HTTPAdapter } from "@x402/core/server";
import { ExactEvmScheme } from "@x402/evm/exact/server";

export const BASE_SEPOLIA = "eip155:84532";
export const PREEMPT_FAULTS = ["nonce_used_is_paid", "serve_before_settle"] as const;
export type PreemptFault = "" | (typeof PREEMPT_FAULTS)[number];

export interface PreemptServer { base: string; close(): Promise<void>; handled: number }

export async function startPreemptServer(facilitatorUrl: string, fault: PreemptFault = "", method = "permit2",
    port = 0): Promise<PreemptServer> {
  const rs = new x402ResourceServer(new HTTPFacilitatorClient({ url: facilitatorUrl, timeoutMs: 3000 }));
  rs.register(BASE_SEPOLIA, new ExactEvmScheme());
  const accepts = { scheme: "exact", network: BASE_SEPOLIA, payTo: "0x209693Bc6afc0C5328bA36FaF03C514EF312287C",
    price: { asset: "0x036CbD53842c5426634e7929541eC2318f3dCF7e", amount: "10000",
      extra: { name: "USDC", version: "2", assetTransferMethod: method } } };
  const app = new x402HTTPResourceServer(rs, { "GET /paid": { accepts, description: "permit2 example" } } as any);
  await app.initialize();
  const state: PreemptServer = { base: "", handled: 0, close: async () => {} };
  const server = http.createServer(async (rq, res) => {
    const url = new URL(rq.url ?? "/", "http://127.0.0.1");
    const send = (status: number, headers: Record<string, string>, body: unknown) => {
      res.writeHead(status, { "content-type": "application/json", ...headers });
      res.end(JSON.stringify(body));
    };
    if (url.pathname === "/free") return send(200, {}, { content: "free" });
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
      const content = () => { state.handled++; return { content: "paid content", serial: state.handled }; };
      if (fault === "serve_before_settle") {
        void app.processSettlement(r.paymentPayload, r.paymentRequirements, r.declaredExtensions).catch(() => undefined);
        return send(200, {}, content());
      }
      let settled: any = null;
      try { settled = await app.processSettlement(r.paymentPayload, r.paymentRequirements, r.declaredExtensions); }
      catch { settled = null; }
      if (settled?.success) return send(200, settled.headers ?? {}, content());
      if (fault === "nonce_used_is_paid" && settled?.errorReason === "permit2_invalid_nonce") return send(200, {}, content());
      return send(402, settled?.headers ?? {}, { error: "settlement failed", reason: settled?.errorReason ?? null });
    } catch (e) {
      send(500, {}, { error: String(e).slice(0, 200) });
    }
  });
  await new Promise<void>((ok) => server.listen(port, "127.0.0.1", ok));
  state.base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  state.close = () => new Promise((ok) => { server.closeAllConnections(); server.close(() => ok()); });
  return state;
}
