// Two loopback servers for D1 and G1, no chain and no facilitator calls.
//
// startDiscoveryServer: a facilitator's Bazaar discovery API with a fixed three-item catalogue on Solana devnet and
// Base Sepolia. GET /discovery/resources (type, network, scheme, payTo, limit, offset) and GET /discovery/search
// (query, network, limit). DISCOVERY_FAULT values, each a faulty build D1 must catch:
//   v1_items        items without x402Version or lastUpdated, and accepts without maxTimeoutSeconds
//   ignore_filters  ignores limit and the network filter: every item, every time
//
// startA2aAgent: an agent with one paid skill and the HTTP route it mirrors. GET /generate answers 402 with a
// PAYMENT-REQUIRED header built by @x402/core's resource server; POST /a2a answers message/send with an input-required
// task carrying the same PaymentRequired (specs/transports-v2/a2a.md). A2A_FAULT values, each a faulty build G1 must
// catch:
//   stale_price     the A2A requirements come from a separate, older price, not the route's
//   not_input_required  the task is answered "failed" with the requirements only in its text
import http from "node:http";
import type { AddressInfo } from "node:net";
import { HTTPFacilitatorClient, x402HTTPResourceServer, x402ResourceServer } from "@x402/core/server";
import type { HTTPAdapter } from "@x402/core/server";
import { ExactEvmScheme } from "@x402/evm/exact/server";

export const DEVNET = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1";
export const BASE_SEPOLIA = "eip155:84532";
export const DISCOVERY_FAULTS = ["v1_items", "ignore_filters"] as const;
export type DiscoveryFault = "" | (typeof DISCOVERY_FAULTS)[number];
export const A2A_FAULTS = ["stale_price", "not_input_required"] as const;
export type A2aFault = "" | (typeof A2A_FAULTS)[number];

const evm = (amount: string) => ({ scheme: "exact", network: BASE_SEPOLIA, amount, maxTimeoutSeconds: 60,
  asset: "0x036CbD53842c5426634e7929541eC2318f3dCF7e", payTo: "0x209693Bc6afc0C5328bA36FaF03C514EF312287C",
  extra: { name: "USDC", version: "2" } });
const svm = (amount: string) => ({ scheme: "exact", network: DEVNET, amount, maxTimeoutSeconds: 60,
  asset: "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU", payTo: "11111111111111111111111111111112",
  extra: { feePayer: "11111111111111111111111111111111" } });

const CATALOG = [
  { resource: "https://weather.example/forecast", type: "http", x402Version: 2, accepts: [evm("10000")],
    lastUpdated: "2026-10-24T09:00:00.000Z", description: "Weather forecast", extensions: { bazaar: {} } },
  { resource: "https://maps.example/route", type: "http", x402Version: 2, accepts: [svm("20000")],
    lastUpdated: "2026-10-24T10:00:00.000Z", description: "Route planning" },
  { resource: "mcp://tool/weather_alerts", type: "mcp", x402Version: 2, accepts: [evm("5000"), svm("5000")],
    lastUpdated: "2026-10-24T11:00:00.000Z", description: "Weather alerts tool" },
];

export interface Loopback { base: string; close(): Promise<void> }

const listen = async (server: http.Server, port: number): Promise<Loopback> => {
  await new Promise<void>((ok) => server.listen(port, "127.0.0.1", ok));
  return { base: `http://127.0.0.1:${(server.address() as AddressInfo).port}`,
    close: () => new Promise((ok) => { server.closeAllConnections(); server.close(() => ok()); }) };
};

export async function startDiscoveryServer(fault: DiscoveryFault = "", port = 0): Promise<Loopback> {
  const server = http.createServer((rq, res) => {
    const url = new URL(rq.url ?? "/", "http://127.0.0.1");
    const send = (code: number, body: unknown) => {
      res.writeHead(code, { "content-type": "application/json" });
      res.end(JSON.stringify(body));
    };
    const q = url.searchParams;
    const shape = (it: (typeof CATALOG)[number]) => fault === "v1_items"
      ? { resource: it.resource, type: it.type, accepts: it.accepts.map(({ maxTimeoutSeconds: _m, ...a }) => a) }
      : it;
    let items = CATALOG.slice();
    const filter = fault !== "ignore_filters";
    if (filter) {
      const net = q.get("network"), type = q.get("type"), scheme = q.get("scheme"), payTo = q.get("payTo");
      if (net) items = items.filter((i) => i.accepts.some((a) => a.network === net));
      if (scheme) items = items.filter((i) => i.accepts.some((a) => a.scheme === scheme));
      if (payTo) items = items.filter((i) => i.accepts.some((a) => a.payTo === payTo));
      if (type) items = items.filter((i) => i.type === type);
    }
    const limit = Math.min(100, Math.max(1, Number(q.get("limit") ?? 20) || 20));
    const offset = Math.max(0, Number(q.get("offset") ?? 0) || 0);
    if (rq.method === "GET" && url.pathname === "/discovery/resources") {
      const page = filter ? items.slice(offset, offset + limit) : items;
      return send(200, { x402Version: 2, items: page.map(shape), pagination: { limit, offset, total: items.length } });
    }
    if (rq.method === "GET" && url.pathname === "/discovery/search") {
      const words = (q.get("query") ?? "").toLowerCase().split(/\s+/).filter(Boolean);
      let hits = items.filter((i) => words.some((w) => `${i.description} ${i.resource}`.toLowerCase().includes(w)));
      if (filter) hits = hits.slice(0, limit);
      return send(200, { x402Version: 2, resources: hits.map(shape), partialResults: false,
        pagination: { limit, cursor: null } });
    }
    send(404, { error: "not found" });
  });
  return listen(server, port);
}

export async function startA2aAgent(facilitatorUrl: string, fault: A2aFault = "", port = 0): Promise<Loopback> {
  const rs = new x402ResourceServer(new HTTPFacilitatorClient({ url: facilitatorUrl, timeoutMs: 3000 }));
  rs.register(BASE_SEPOLIA, new ExactEvmScheme());
  const price = { asset: "0x036CbD53842c5426634e7929541eC2318f3dCF7e", amount: "48240", extra: { name: "USDC", version: "2" } };
  const accepts = { scheme: "exact", network: BASE_SEPOLIA, payTo: "0x209693Bc6afc0C5328bA36FaF03C514EF312287C", price };
  const resource = { description: "Generate an image", mimeType: "image/png" };
  const app = new x402HTTPResourceServer(rs, { "GET /generate": { accepts, ...resource } } as any);
  await app.initialize();
  let base = "";
  const required = async () => {
    const reqs = await rs.buildPaymentRequirements({ ...accepts, network: BASE_SEPOLIA } as any);
    const stale = fault === "stale_price" ? reqs.map((r) => ({ ...r, amount: "40000" })) : reqs;
    return rs.createPaymentRequiredResponse(stale, { url: `${base}/generate`, ...resource },
      "Payment required to access this resource");
  };
  let tasks = 0;
  const server = http.createServer(async (rq, res) => {
    const url = new URL(rq.url ?? "/", "http://127.0.0.1");
    const send = (code: number, headers: Record<string, string>, body: unknown) => {
      res.writeHead(code, { "content-type": "application/json", ...headers });
      res.end(JSON.stringify(body));
    };
    try {
      if (url.pathname === "/generate") {
        const adapter: HTTPAdapter = {
          getHeader: (n) => { const v = rq.headers[n.toLowerCase()]; return Array.isArray(v) ? v[0] : v; },
          getMethod: () => rq.method ?? "GET", getPath: () => url.pathname, getUrl: () => url.toString(),
          getAcceptHeader: () => String(rq.headers.accept ?? "application/json"),
          getUserAgent: () => String(rq.headers["user-agent"] ?? ""),
        };
        const paymentHeader = adapter.getHeader("payment-signature");
        const r = await app.processHTTPRequest({ adapter, path: url.pathname, method: adapter.getMethod(), paymentHeader });
        if (r.type === "payment-error") return send(r.response.status, r.response.headers, r.response.body);
        return send(400, {}, { error: "this example only answers the unpaid request" });
      }
      if (url.pathname === "/a2a" && rq.method === "POST") {
        let data = "";
        for await (const c of rq) data += c;
        const msg = JSON.parse(data);
        if (msg.method !== "message/send") return send(200, {}, { jsonrpc: "2.0", id: msg.id, error: { code: -32601, message: "method not found" } });
        const pr = await required();
        const id = `task-${++tasks}`;
        const text = "Payment is required to generate the image.";
        if (fault === "not_input_required") {
          return send(200, {}, { jsonrpc: "2.0", id: msg.id, result: { kind: "task", id, status: { state: "failed",
            message: { kind: "message", role: "agent", parts: [{ kind: "text", text: `${text} ${JSON.stringify(pr)}` }] } } } });
        }
        return send(200, {}, { jsonrpc: "2.0", id: msg.id, result: { kind: "task", id, status: { state: "input-required",
          message: { kind: "message", role: "agent", parts: [{ kind: "text", text }],
            metadata: { "x402.payment.status": "payment-required", "x402.payment.required": pr } } } } });
      }
      send(404, {}, { error: "not found" });
    } catch (e) {
      send(500, {}, { error: String(e).slice(0, 200) });
    }
  });
  const l = await listen(server, port);
  base = l.base;
  return l;
}
