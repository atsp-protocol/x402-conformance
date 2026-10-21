// An example resource server on @x402/core's x402HTTPResourceServer with the exact scheme on Solana devnet (@x402/svm)
// or, with EXAMPLE_NETWORK=eip155:84532, Base Sepolia (@x402/evm).
// It serves GET /paid only after processSettlement reports success. X402_FACILITATOR_URL names its facilitator.
// EXAMPLE_FAULT shows what the probe catches:
//   serve_after_verify   serves once /verify passes and settles afterwards, ignoring the outcome
//   serve_on_any_settle  calls /settle but serves whatever it answers or throws
import http from "node:http";
import type { AddressInfo } from "node:net";
import { HTTPFacilitatorClient, x402HTTPResourceServer, x402ResourceServer } from "@x402/core/server";
import type { HTTPAdapter } from "@x402/core/server";
import { ExactSvmScheme } from "@x402/svm/exact/server";
import { ExactEvmScheme } from "@x402/evm/exact/server";

export const DEVNET = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1";
export const BASE_SEPOLIA = "eip155:84532";
const DEVNET_USDC = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU";
const BASE_SEPOLIA_USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e";
const PAY_TO = "11111111111111111111111111111112";
const EVM_PAY_TO = "0x209693Bc6afc0C5328bA36FaF03C514EF312287C";

export async function startExample(facilitatorUrl: string, fault = "", port = 0, network = DEVNET):
    Promise<{ url: string; close(): Promise<void> }> {
  const rs = new x402ResourceServer(new HTTPFacilitatorClient({ url: facilitatorUrl, timeoutMs: 3000 }));
  const evm = network === BASE_SEPOLIA;
  if (evm) rs.register(BASE_SEPOLIA, new ExactEvmScheme());
  else rs.register(network as `${string}:${string}`, new ExactSvmScheme());
  const accepts = evm
    ? { scheme: "exact", network: BASE_SEPOLIA, payTo: EVM_PAY_TO,
      price: { asset: BASE_SEPOLIA_USDC, amount: "10000", extra: { name: "USDC", version: "2" } } }
    : { scheme: "exact", network, payTo: PAY_TO, price: { asset: DEVNET_USDC, amount: "10000" } };
  const app = new x402HTTPResourceServer(rs, {
    "GET /paid": { accepts: accepts as any, description: "example paid route" },
  });
  await app.initialize();
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
    const send = (status: number, headers: Record<string, string>, body: unknown) => {
      res.writeHead(status, { "content-type": "application/json", ...headers });
      res.end(typeof body === "string" ? body : JSON.stringify(body ?? {}));
    };
    try {
      const paymentHeader = adapter.getHeader("payment-signature") ?? adapter.getHeader("x-payment");
      const r = await app.processHTTPRequest({ adapter, path: url.pathname, method: adapter.getMethod(), paymentHeader });
      if (r.type === "no-payment-required") return send(200, {}, { free: true });
      if (r.type === "payment-error") return send(r.response.status, r.response.headers, r.response.body);
      if (fault === "serve_after_verify") {
        send(200, {}, { content: "paid content" });
        app.processSettlement(r.paymentPayload, r.paymentRequirements).catch(() => {});
        return;
      }
      let s;
      try {
        s = await app.processSettlement(r.paymentPayload, r.paymentRequirements, r.declaredExtensions);
      } catch (e) {
        if (fault === "serve_on_any_settle") return send(200, {}, { content: "paid content" });
        return send(402, {}, { error: "settlement failed" });
      }
      if (s.success || fault === "serve_on_any_settle") return send(200, s.headers, { content: "paid content" });
      return send(s.response.status, s.response.headers, s.response.body);
    } catch (e) {
      send(500, {}, { error: String(e).slice(0, 200) });
    }
  });
  await new Promise<void>((ok) => server.listen(port, "127.0.0.1", ok));
  return {
    url: `http://127.0.0.1:${(server.address() as AddressInfo).port}/paid`,
    close: () => new Promise((ok) => { server.closeAllConnections(); server.close(() => ok()); }),
  };
}

const isMain = process.argv[1] && import.meta.url.endsWith(process.argv[1].replace(/\\/g, "/").split("/").pop() ?? "");
if (isMain && process.env.X402_FACILITATOR_URL) {
  startExample(process.env.X402_FACILITATOR_URL, process.env.EXAMPLE_FAULT ?? "", Number(process.env.PORT ?? 4020),
    process.env.EXAMPLE_NETWORK ?? DEVNET)
    .then((s) => console.log(JSON.stringify({ listening: s.url })));
}
