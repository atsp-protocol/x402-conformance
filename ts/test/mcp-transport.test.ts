// The MCP transport checks against a paid tool behind the facilitator double, on Solana devnet and Base Sepolia.
// X1: the stock control's payment-required tool result passes; a build with no structuredContent and a build that
// answers a JSON-RPC error each fail. X2: the control returns the tool's result only on a final, first-time settle;
// a build that serves when the settle failed and a build that serves before settling each fail.
import assert from "node:assert/strict";
import { test } from "node:test";
import { startDouble } from "../src/double.js";
import { checkMcpPaymentRequired, parseRpc, probeMcpTransport, X2_CASES } from "../src/mcp-transport.js";
import { BASE_SEPOLIA, DEVNET, PAID_TOOL, startMcpServer, TOOL_OUTPUT, type McpFault } from "../example/mcp-server.js";

const NETS = [["Solana devnet", DEVNET], ["Base Sepolia", BASE_SEPOLIA]] as const;

async function x1(fault: McpFault, network: string) {
  const double = await startDouble(0);
  const s = await startMcpServer(double.url, fault, network);
  try {
    const [r] = await checkMcpPaymentRequired({ url: s.url, tool: PAID_TOOL });
    return { r, d: r.detail as any, settles: double.calls.filter((c) => c.path === "/settle").length, executed: s.executed };
  } finally { await s.close(); await double.close(); }
}

async function x2(fault: McpFault, network: string) {
  const double = await startDouble(0);
  const s = await startMcpServer(double.url, fault, network);
  try {
    const [r] = await probeMcpTransport({ url: s.url, tool: PAID_TOOL }, double, { network, timeoutMs: 8000 });
    return { r, d: r.detail as any, successes: double.successes.length, executed: s.executed };
  } finally { await s.close(); await double.close(); }
}

for (const [name, net] of NETS) {
  test(`X1 control: a paid tool answers isError with PaymentRequired in structuredContent and content[0].text, ${name}`, async () => {
    const { r, d, settles, executed } = await x1("", net);
    assert.equal(r.pass, true, JSON.stringify(r, null, 1));
    assert.equal(d.is_error, true);
    assert.equal(d.accepts, 1);
    assert.equal(settles, 0);
    assert.equal(executed, 0);
  });
  test(`X1 catches a paid tool whose payment-required result has no structuredContent, ${name}`, async () => {
    const { r, d } = await x1("text_only", net);
    assert.equal(r.pass, false);
    assert.match(d.error, /structuredContent is missing/);
  });
  test(`X1 catches a paid tool that answers a JSON-RPC error instead of a tool result, ${name}`, async () => {
    const { r, d } = await x1("rpc_error", net);
    assert.equal(r.pass, false);
    assert.match(d.error, /JSON-RPC error/);
  });

  test(`X2 control: a paid tool returns its result once, only on a final first-time settle, ${name}`, async () => {
    const { r, d, successes, executed } = await x2("", net);
    assert.equal(r.pass, true, JSON.stringify(r, null, 1));
    assert.equal(d.cases.reference.served, true);
    assert.equal(d.cases.reference.payment_response.success, true);
    assert.equal(successes, 1);
    for (const c of X2_CASES.filter((x) => x !== "reference")) assert.equal(d.cases[c].served, false, c);
    assert.ok(executed >= 1);
  });
  test(`X2 catches a paid tool that returns its result when the settle failed, ${name}`, async () => {
    const { r, d } = await x2("serve_on_failure", net);
    assert.equal(r.pass, false);
    for (const c of ["duplicate", "settle_502", "settle_pending", "settle_failed"]) assert.equal(d.cases[c].served, true, c);
    assert.match(d.error, /settle_failed: the tool result was returned/);
  });
  test(`X2 catches a paid tool that returns its result before the settle, ${name}`, async () => {
    const { r, d } = await x2("result_first", net);
    assert.equal(r.pass, false);
    assert.equal(d.cases.settle_timeout.served, true);
    assert.match(d.error, /settle_timeout: the tool result was returned/);
  });
}

test("X2 parseRpc reads the answer from an event stream", () => {
  const raw = 'event: message\ndata: {"jsonrpc":"2.0","method":"notifications/progress"}\n\n'
    + `data: {"jsonrpc":"2.0","id":7,"result":{"content":[{"type":"text","text":"${TOOL_OUTPUT}"}]}}\n\n`;
  assert.equal(parseRpc(raw, "text/event-stream", 7).result.content[0].text, TOOL_OUTPUT);
  assert.equal(parseRpc(raw, "text/event-stream", 8), null);
});
