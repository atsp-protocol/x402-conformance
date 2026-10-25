// A resource server for U1-U3, the upto scheme, on @x402/core's x402HTTPResourceServer with the stock upto scheme
// servers (@x402/evm UptoEvmScheme for Permit2 on Base Sepolia, @x402/svm UptoSvmScheme for the payment channel on
// Solana devnet). One metered paid GET route, /metered, with a maximum of 10000 atomic units at 10 units per unit of
// work; ?units=N says how much work the request does. The control meters the work, caps the charge at the authorised
// maximum, settles it through setSettlementOverrides' amount after the handler runs, and returns the SDK's
// PAYMENT-RESPONSE. UPTO_FAULT shows what U1-U3 catch:
//   no_cap        charges the metered amount even when it is above the maximum the client signed (U1)
//   report_max    settles the metered amount but reports the authorised maximum in PAYMENT-RESPONSE (U2)
//   upfront_flow  writes its own 402 whose upto offer declares extra.paymentFlow "upfront" (U3); the SDK refuses to
//                 build that offer, so this build edits the PAYMENT-REQUIRED header the SDK wrote
import http from "node:http";
import type { AddressInfo } from "node:net";
import { HTTPFacilitatorClient, x402HTTPResourceServer, x402ResourceServer } from "@x402/core/server";
import type { HTTPAdapter } from "@x402/core/server";
import { decodePaymentRequiredHeader, decodePaymentResponseHeader, encodePaymentRequiredHeader,
  encodePaymentResponseHeader } from "@x402/core/http";
import { UptoEvmScheme } from "@x402/evm/upto/server";
import { UptoSvmScheme } from "@x402/svm/upto/server";

export const DEVNET = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1";
export const BASE_SEPOLIA = "eip155:84532";
export const UPTO_FAULTS = ["no_cap", "report_max", "upfront_flow"] as const;
export type UptoFault = "" | (typeof UPTO_FAULTS)[number];
export const UPTO_MAX = 10000n;
export const UNIT_PRICE = 10n;

export interface UptoServer { base: string; close(): Promise<void>; handled: number }

export async function startUptoServer(facilitatorUrl: string, fault: UptoFault = "", network = DEVNET,
    port = 0): Promise<UptoServer> {
  const rs = new x402ResourceServer(new HTTPFacilitatorClient({ url: facilitatorUrl, timeoutMs: 3000 }));
  const evm = network === BASE_SEPOLIA;
  if (evm) rs.register(BASE_SEPOLIA, new UptoEvmScheme());
  else rs.register(network as `${string}:${string}`, new UptoSvmScheme());
  const extra: Record<string, unknown> = { ...(evm ? { name: "USDC", version: "2" } : { withdrawDelay: 3600,
    tokenProgram: "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA" }),
  };
  const accepts = evm
    ? { scheme: "upto", network: BASE_SEPOLIA, payTo: "0x209693Bc6afc0C5328bA36FaF03C514EF312287C",
      price: { asset: "0x036CbD53842c5426634e7929541eC2318f3dCF7e", amount: String(UPTO_MAX), extra } }
    : { scheme: "upto", network, payTo: "11111111111111111111111111111112",
      price: { asset: "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU", amount: String(UPTO_MAX), extra } };
  const app = new x402HTTPResourceServer(rs, { "GET /metered": { accepts, description: "upto example" } } as any);
  await app.initialize();
  const state: UptoServer = { base: "", handled: 0, close: async () => {} };
  const server = http.createServer(async (rq, res) => {
    const url = new URL(rq.url ?? "/", "http://127.0.0.1");
    const send = (status: number, headers: Record<string, string>, body: unknown) => {
      res.writeHead(status, { "content-type": "application/json", ...headers });
      res.end(JSON.stringify(body));
    };
    if (url.pathname !== "/metered") return send(404, {}, { error: "not found" });
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
      const r: any = await app.processHTTPRequest({ adapter, path: url.pathname, method: adapter.getMethod(), paymentHeader });
      if (r.type === "no-payment-required") return send(404, {}, { error: "not found" });
      if (r.type === "payment-error") {
        const headers: Record<string, string> = { ...r.response.headers };
        const k = Object.keys(headers).find((h) => h.toLowerCase() === "payment-required");
        if (fault === "upfront_flow" && k) {
          const pr: any = decodePaymentRequiredHeader(headers[k]);
          pr.accepts = pr.accepts.map((a: any) => ({ ...a, extra: { ...(a.extra ?? {}), paymentFlow: "upfront" } }));
          headers[k] = encodePaymentRequiredHeader(pr);
        }
        return send(r.response.status, headers, r.response.body);
      }
      // The handler runs first; the charge is known only afterwards.
      state.handled++;
      const units = BigInt(/^[0-9]{1,9}$/.test(url.searchParams.get("units") ?? "") ? url.searchParams.get("units")! : "1");
      const metered = units * UNIT_PRICE;
      const max = BigInt(r.paymentRequirements.amount);
      const charge = fault === "no_cap" || metered <= max ? metered : max;
      const s: any = await app.processSettlement(r.paymentPayload, r.paymentRequirements, r.declaredExtensions, undefined,
        { amount: String(charge) }, r.beforeHandlerSettlement);
      if (!s?.success) return send(402, {}, { error: String(s?.errorReason ?? "settlement failed") });
      const headers: Record<string, string> = { ...(s.headers ?? {}) };
      if (fault === "report_max") {
        const k = Object.keys(headers).find((h) => h.toLowerCase() === "payment-response");
        if (k) headers[k] = encodePaymentResponseHeader({ ...decodePaymentResponseHeader(headers[k]), amount: String(max) } as any);
      }
      return send(200, headers, { content: "metered content", units: String(units) });
    } catch (e) {
      send(500, {}, { error: String(e).slice(0, 200) });
    }
  });
  await new Promise<void>((ok) => server.listen(port, "127.0.0.1", ok));
  state.base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  state.close = () => new Promise((ok) => { server.closeAllConnections(); server.close(() => ok()); });
  return state;
}
