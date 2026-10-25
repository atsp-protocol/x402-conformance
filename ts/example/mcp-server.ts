// A paid MCP tool over Streamable HTTP (JSON answers), for the MCP transport checks X1 and X2. One paid tool,
// `forecast`, behind the facilitator at `facilitatorUrl`; `echo` is free. JSON-RPC methods: initialize,
// notifications/initialized, tools/list and tools/call. A session id is issued on initialize.
//
// The control follows specs/transports-v2/mcp.md: an unpaid call answers isError with the PaymentRequired object in
// structuredContent and as JSON in content[0].text; a paid call is verified, the tool runs, the payment is settled,
// and the tool's result goes back only when the settle succeeded, with _meta["x402/payment-response"]. When the settle
// fails the answer is the payment error alone, never the tool's content.
//
// MCP_FAULT values, each a faulty build a check must catch:
//   text_only        X1: the payment-required result has content[0].text but no structuredContent
//   rpc_error        X1: an unpaid call is answered with a JSON-RPC error instead of a tool result
//   serve_on_failure X2: the tool's result goes back even when the settle failed or never answered
//   result_first     X2: the tool's result goes back after /verify; the settle runs afterwards and its outcome is ignored
import http from "node:http";
import type { AddressInfo } from "node:net";
import { randomBytes } from "node:crypto";
import { HTTPFacilitatorClient, x402ResourceServer } from "@x402/core/server";
import { ExactSvmScheme } from "@x402/svm/exact/server";
import { ExactEvmScheme } from "@x402/evm/exact/server";

export const DEVNET = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1";
export const BASE_SEPOLIA = "eip155:84532";
export const MCP_FAULTS = ["text_only", "rpc_error", "serve_on_failure", "result_first"] as const;
export type McpFault = "" | (typeof MCP_FAULTS)[number];
export const PAID_TOOL = "forecast";
export const TOOL_OUTPUT = "forecast: clear skies";

export interface McpServer { url: string; executed: number; close(): Promise<void> }

const TOOLS = [
  { name: PAID_TOOL, description: "A paid tool: a short forecast", inputSchema: { type: "object", properties: {} } },
  { name: "echo", description: "A free tool", inputSchema: { type: "object", properties: { text: { type: "string" } } } },
];

/** sessionless: answer tools/call without initialize or a session id, as some hosted MCP servers do. */
export async function startMcpServer(facilitatorUrl: string, fault: McpFault = "", network = DEVNET,
    port = 0, opts: { sessionless?: boolean } = {}): Promise<McpServer> {
  const rs = new x402ResourceServer(new HTTPFacilitatorClient({ url: facilitatorUrl, timeoutMs: 3000 }));
  const evm = network === BASE_SEPOLIA;
  if (evm) rs.register(BASE_SEPOLIA, new ExactEvmScheme());
  else rs.register(network as `${string}:${string}`, new ExactSvmScheme());
  await rs.initialize();
  const requirements = await rs.buildPaymentRequirements(evm
    ? { scheme: "exact", network: BASE_SEPOLIA, payTo: "0x209693Bc6afc0C5328bA36FaF03C514EF312287C",
      price: { asset: "0x036CbD53842c5426634e7929541eC2318f3dCF7e", amount: "10000", extra: { name: "USDC", version: "2" } } }
    : { scheme: "exact", network: network as `${string}:${string}`, payTo: "11111111111111111111111111111112",
      price: { asset: "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU", amount: "10000" } });
  const resource = { url: `mcp://tool/${PAID_TOOL}`, description: "A short forecast", mimeType: "application/json" };
  const sessions = new Set<string>();
  const state: McpServer = { url: "", executed: 0, close: async () => {} };

  const paymentError = async (error: string) => {
    const pr = await rs.createPaymentRequiredResponse(requirements, resource, error);
    const text = JSON.stringify(pr);
    if (fault === "text_only") return { isError: true, content: [{ type: "text", text }] };
    return { isError: true, structuredContent: pr, content: [{ type: "text", text }] };
  };
  const runTool = () => { state.executed++; return { content: [{ type: "text", text: TOOL_OUTPUT }] }; };

  async function callTool(params: any): Promise<{ result?: unknown; error?: unknown }> {
    if (params?.name === "echo") return { result: { content: [{ type: "text", text: String(params?.arguments?.text ?? "") }] } };
    if (params?.name !== PAID_TOOL) return { error: { code: -32602, message: `unknown tool ${params?.name}` } };
    const payment = params?._meta?.["x402/payment"];
    if (!payment) {
      if (fault === "rpc_error") return { error: { code: -32402, message: "Payment required" } };
      return { result: await paymentError("Payment required to access this resource") };
    }
    const req = rs.findMatchingRequirements(requirements, payment);
    if (!req) return { result: await paymentError("The payment does not match an offered requirement") };
    let verified: any;
    try { verified = await rs.verifyPayment(payment, req); } catch (e) { verified = { isValid: false, invalidReason: String(e) }; }
    if (!verified?.isValid) return { result: await paymentError(`Payment invalid: ${verified?.invalidReason ?? "unknown"}`) };
    const out = runTool();
    if (fault === "result_first") {
      void rs.settlePayment(payment, req).catch(() => undefined);
      return { result: out };
    }
    let settled: any = null;
    try { settled = await rs.settlePayment(payment, req); } catch { settled = null; }
    if (!settled?.success) {
      if (fault === "serve_on_failure") return { result: out };
      return { result: await paymentError(`Settlement failed${settled?.errorReason ? `: ${settled.errorReason}` : ""}`) };
    }
    return { result: { ...out, _meta: { "x402/payment-response": { success: true, transaction: settled.transaction,
      network: settled.network, payer: settled.payer } } } };
  }

  const server = http.createServer(async (rq, res) => {
    const send = (code: number, body?: unknown, headers: Record<string, string> = {}) => {
      res.writeHead(code, { ...(body === undefined ? {} : { "content-type": "application/json" }), ...headers });
      res.end(body === undefined ? undefined : JSON.stringify(body));
    };
    if (rq.method !== "POST") return send(405, { error: "POST only" });
    let data = "";
    for await (const c of rq) data += c;
    let msg: any;
    try { msg = JSON.parse(data); } catch { return send(400, { jsonrpc: "2.0", id: null, error: { code: -32700, message: "parse error" } }); }
    const reply = (r: { result?: unknown; error?: unknown }, headers: Record<string, string> = {}) =>
      send(200, { jsonrpc: "2.0", id: msg.id, ...r }, headers);
    if (msg.id === undefined) return send(202);
    if (msg.method === "initialize") {
      const sid = randomBytes(12).toString("hex");
      sessions.add(sid);
      return reply({ result: { protocolVersion: msg.params?.protocolVersion ?? "2025-06-18",
        capabilities: { tools: {} }, serverInfo: { name: "x402-conformance paid tool example", version: "1" } } },
      { "mcp-session-id": sid });
    }
    const sid = String(rq.headers["mcp-session-id"] ?? "");
    if (!opts.sessionless && !sessions.has(sid)) return send(404, { jsonrpc: "2.0", id: msg.id, error: { code: -32001, message: "unknown session" } });
    if (msg.method === "tools/list") return reply({ result: { tools: TOOLS } });
    if (msg.method === "tools/call") {
      try { return reply(await callTool(msg.params)); }
      catch (e) { return reply({ error: { code: -32603, message: String(e).slice(0, 200) } }); }
    }
    return reply({ error: { code: -32601, message: `method not found: ${msg.method}` } });
  });
  await new Promise<void>((ok) => server.listen(port, "127.0.0.1", ok));
  state.url = `http://127.0.0.1:${(server.address() as AddressInfo).port}/mcp`;
  state.close = () => new Promise((ok) => { server.closeAllConnections(); server.close(() => ok()); });
  return state;
}
