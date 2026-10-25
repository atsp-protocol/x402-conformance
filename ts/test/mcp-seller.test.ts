// The MCP seller mode: one unpaid tools/call of a paid tool on a server you may test, X1 on the tool result and P3, P4,
// P5 and P7 on the PaymentRequired in it, paced and logged, nothing paid. Against the paid-tool example on loopback.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { test } from "node:test";
import { startDouble } from "../src/double.js";
import { checkMcpOffer, checkMcpSeller } from "../src/mcp-seller.js";
import { createPacedFetch } from "../src/pace.js";
import { BASE_SEPOLIA, DEVNET, PAID_TOOL, startMcpServer, type McpFault } from "../example/mcp-server.js";

const NETS = [["Solana devnet", DEVNET], ["Base Sepolia", BASE_SEPOLIA]] as const;
const ids = (rs: { check: string }[]) => rs.map((r) => r.check.split(" ")[0]);

async function seller(fault: McpFault, network: string, sessionless = false, initialize = true) {
  const double = await startDouble(0);
  const s = await startMcpServer(double.url, fault, network, 0, { sessionless });
  const f = createPacedFetch({ minIntervalMs: 0, log: () => {} });
  try {
    const rs = await checkMcpSeller({ url: s.url, tool: PAID_TOOL }, { fetch: f as typeof fetch, initialize });
    return { rs, sent: f.requests.length, settles: double.calls.filter((c) => c.path === "/settle").length,
      executed: s.executed };
  } finally { await s.close(); await double.close(); }
}

for (const [name, net] of NETS) {
  test(`MCP seller control: X1 and the offer checks pass after initialize, in 3 requests, nothing paid, ${name}`, async () => {
    const { rs, sent, settles, executed } = await seller("", net);
    assert.deepEqual(ids(rs), ["X1", "P3", "P4", "P5", "P7"]);
    assert.ok(rs.every((r) => r.pass), JSON.stringify(rs));
    assert.equal(sent, 3);
    assert.equal(settles, 0);
    assert.equal(executed, 0);
  });

  test(`MCP seller --no-initialize: a server that needs no session is graded in 1 request, ${name}`, async () => {
    const { rs, sent } = await seller("", net, true, false);
    assert.ok(rs.every((r) => r.pass), JSON.stringify(rs));
    assert.equal(sent, 1);
    assert.equal((rs[0].detail as any).initialized, false);
  });

  test(`MCP seller catches text_only: X1 fails and the offer in content[0].text is still graded, ${name}`, async () => {
    const { rs } = await seller("text_only", net);
    assert.equal(rs[0].pass, false);
    assert.match(String((rs[0].detail as any).error), /structuredContent is missing/);
    assert.deepEqual(ids(rs).slice(1), ["P3", "P4", "P5", "P7"]);
  });

  test(`MCP seller catches rpc_error: X1 fails and there is no offer to grade, ${name}`, async () => {
    const { rs } = await seller("rpc_error", net);
    assert.deepEqual(ids(rs), ["X1"]);
    assert.equal(rs[0].pass, false);
  });
}

test("MCP seller offer checks: a missing payTo fails P4 and an EVM offer without name and version fails P5", () => {
  const ok = { x402Version: 2, resource: { url: "mcp://tool/forecast" }, accepts: [{ scheme: "exact",
    network: BASE_SEPOLIA, asset: "0x036CbD53842c5426634e7929541eC2318f3dCF7e", amount: "1000",
    payTo: "0x0000000000000000000000000000000000000001", maxTimeoutSeconds: 60, extra: { name: "USDC", version: "2" } }] };
  assert.ok(checkMcpOffer(ok).every((r) => r.pass));
  const bad = structuredClone(ok) as any;
  delete bad.accepts[0].payTo;
  delete bad.accepts[0].extra;
  const rs = checkMcpOffer(bad);
  assert.equal(rs.find((r) => r.check.startsWith("P4"))!.pass, false);
  assert.equal(rs.find((r) => r.check.startsWith("P5"))!.pass, false);
  assert.equal((rs[0].detail as any).transport, "mcp");
});

const cli = new URL("../src/cli.js", import.meta.url).pathname;
const run = (...args: string[]) => new Promise<{ code: number; out: string; err: string }>((ok) => {
  const p = spawn(process.execPath, [cli, ...args]);
  let out = "", err = "";
  p.stdout.on("data", (d) => { out += d; });
  p.stderr.on("data", (d) => { err += d; });
  p.on("exit", (code) => ok({ code: code ?? 2, out, err }));
});

test("MCP seller CLI: x402conf-svm mcp logs each request, honours --no-initialize and --max-requests", async () => {
  const double = await startDouble(0);
  const s = await startMcpServer(double.url, "", BASE_SEPOLIA, 0, { sessionless: true });
  try {
    const one = await run("mcp", "--url", s.url, "--tool", PAID_TOOL, "--no-initialize", "--arguments", "{}",
      "--max-requests", "1");
    assert.equal(one.code, 0, one.out + one.err);
    const doc = JSON.parse(one.out);
    assert.equal(doc.pacing.sent, 1);
    assert.equal(doc.mode, "mcp-unpaid");
    assert.deepEqual(doc.checks.map((c: any) => c.check.split(" ")[0]), ["X1", "P3", "P4", "P5", "P7"]);
    assert.match(one.err, /x402conf-svm: request 1 of at most 1 .*POST /);
    const capped = await run("mcp", "--url", s.url, "--tool", PAID_TOOL, "--max-requests", "1");
    const d2 = JSON.parse(capped.out);
    assert.equal(d2.pacing.sent, 1);
    assert.match(d2.skipped[0], /--max-requests 1 reached/);
  } finally { await s.close(); await double.close(); }
});

test("MCP seller CLI: usage errors exit 2", async () => {
  assert.equal((await run("mcp", "--url", "http://127.0.0.1:9/mcp")).code, 2);
  assert.equal((await run("mcp", "--url", "http://127.0.0.1:9/mcp", "--tool", "t", "--arguments", "[1]")).code, 2);
  assert.equal((await run("live", "--url", "http://127.0.0.1:9/x", "--tool", "t")).code, 2);
  assert.equal((await run("mcp", "--url", "http://127.0.0.1:9/mcp", "--tool", "t", "--share")).code, 2);
});
