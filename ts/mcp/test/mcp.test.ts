// The MCP server over real stdio, the Vercel AI SDK tools through generateText with a mock model, and the LangChain
// tools through invoke(). Everything runs on loopback against the facilitator double and the built-in demo server.
import assert from "node:assert/strict";
import http from "node:http";
import type { AddressInfo } from "node:net";
import { after, before, describe, test } from "node:test";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { generateText } from "ai";
import { MockLanguageModelV3 } from "ai/test";
import { startDouble } from "x402-conformance-svm";
import { x402ConformanceTools as aiTools } from "../src/ai-sdk.js";
import { x402ConformanceTools as lcTools } from "../src/langchain.js";
import { startDemoServer } from "../src/demo.js";
import { AGENT_TOOLS, ALL_TOOLS } from "../src/tools.js";

const BIN = new URL("../src/bin.js", import.meta.url).pathname;
const text = (r: any) => r.content.map((c: any) => c.text).join("\n");

// A loopback route that answers like the demo server and records the User-Agent.
let route = "", lastUA = "";
let demo: Awaited<ReturnType<typeof startDemoServer>>, d0: Awaited<ReturnType<typeof startDouble>>;
const proxy = http.createServer(async (rq, rs) => {
  lastUA = String(rq.headers["user-agent"] ?? "");
  const r = await fetch(demo.url);
  rs.writeHead(r.status, Object.fromEntries(r.headers));
  rs.end(await r.text());
});
before(async () => {
  d0 = await startDouble(0);
  demo = await startDemoServer(d0.url);
  await new Promise<void>((ok) => proxy.listen(0, "127.0.0.1", ok));
  route = `http://127.0.0.1:${(proxy.address() as AddressInfo).port}/paid`;
});
after(async () => { proxy.closeAllConnections(); await new Promise((ok) => proxy.close(ok)); await demo.close(); await d0.close(); });

describe("MCP server over stdio", () => {
  let client: Client;
  before(async () => {
    client = new Client({ name: "test", version: "0" });
    await client.connect(new StdioClientTransport({ command: process.execPath, args: [BIN] }));
  });
  after(async () => { await client.close(); });

  test("lists the seven tools with annotations", async () => {
    const { tools } = await client.listTools();
    assert.deepEqual(tools.map((t) => t.name).sort(), ALL_TOOLS.map((t) => t.name).sort());
    const check = tools.find((t) => t.name === "x402_check_payment_required")!;
    assert.equal(check.annotations?.readOnlyHint, true);
    assert.ok((check.inputSchema as any).properties.url);
  });
  test("x402_demo passes on the reference demo server, and funnels to the badge", async () => {
    const r = await client.callTool({ name: "x402_demo", arguments: {} });
    const t = text(r);
    assert.match(t, /18 checks, 0 failed/);
    assert.match(t, /Add the badge/);
    assert.match(t, /"via": "mcp"/);
  });
  test("x402_demo with a faulty server fails R2-R9 and points to the fix, the corpus and sharing", async () => {
    const t = text(await client.callTool({ name: "x402_demo", arguments: { fault: "serve_on_any_settle" } }));
    for (const id of ["R2", "R3", "R5", "R9"]) assert.match(t, new RegExp(`"${id}"`));
    assert.match(t, /FIXES\.md#r3/);
    assert.match(t, /tree\/main\/corpus\b/);
    assert.match(t, /corpus-case\.yml/);
  });
  test("x402_check_payment_required: one unpaid GET, tagged via=mcp", async () => {
    const t = text(await client.callTool({ name: "x402_check_payment_required", arguments: { url: route } }));
    assert.match(t, /7 checks, 0 failed/);
    assert.match(lastUA, /via=mcp\)$/);
  });
  test("x402_check_payment_required refuses non-http URLs", async () => {
    const r: any = await client.callTool({ name: "x402_check_payment_required", arguments: { url: "file:///etc/passwd" } });
    assert.equal(r.isError, true);
  });
  test("start the double, run your server against it, probe it, stop it", async () => {
    const s = text(await client.callTool({ name: "x402_start_facilitator_double", arguments: {} }));
    const url = s.match(/http:\/\/127\.0\.0\.1:\d+/)![0];
    const mine = await startDemoServer(url);
    try {
      const p = text(await client.callTool({ name: "x402_probe_resource_server", arguments: { resource_url: mine.url } }));
      assert.match(p, /11 checks, 0 failed/);
    } finally { await mine.close(); }
    assert.match(text(await client.callTool({ name: "x402_stop_facilitator_double", arguments: {} })), /stopped/);
  });
  test("the probe refuses a non-loopback URL and a missing double", async () => {
    const a: any = await client.callTool({ name: "x402_probe_resource_server", arguments: { resource_url: "https://example.com/paid" } });
    assert.equal(a.isError, true);
    assert.match(text(a), /loopback/);
    const b: any = await client.callTool({ name: "x402_probe_resource_server", arguments: { resource_url: "http://127.0.0.1:1/paid" } });
    assert.equal(b.isError, true);
  });
  test("x402_explain_check returns the FIXES.md section", async () => {
    const t = text(await client.callTool({ name: "x402_explain_check", arguments: { id: "R3" } }));
    assert.match(t, /^## R3/);
    assert.match(t, /FIXES\.md#r3/);
    const low = text(await client.callTool({ name: "x402_explain_check", arguments: { id: "R11a" } }));
    assert.match(low, /^## R11a/);
    assert.match(low, /FIXES\.md#r11a/);
    const bad: any = await client.callTool({ name: "x402_explain_check", arguments: { id: "Z9" } });
    assert.equal(bad.isError, true);
  });
  test("x402_share_case anonymises a failing report and sends nothing", async () => {
    const failing = text(await client.callTool({ name: "x402_demo", arguments: { fault: "serve_on_any_settle" } }));
    const report = JSON.parse(failing.slice(failing.indexOf("\n{") + 1));
    const t = text(await client.callTool({ name: "x402_share_case", arguments: { report, framework: "demo" } }));
    assert.match(t, /nothing was sent/);
    assert.match(t, /issues\/new\?template=corpus-case\.yml/);
    assert.ok(!t.includes("127.0.0.1"));
  });
});

describe("Vercel AI SDK", () => {
  test("exposes only the agent-safe tools", () => {
    assert.deepEqual(Object.keys(aiTools()).sort(), AGENT_TOOLS.map((t) => t.name).sort());
  });
  test("a model's tool call runs the check through generateText, tagged via=ai-sdk", async () => {
    const model = new MockLanguageModelV3({
      doGenerate: async () => ({
        content: [{ type: "tool-call", toolCallId: "c1", toolName: "x402_check_payment_required", input: JSON.stringify({ url: route }) }],
        finishReason: { unified: "tool-calls", raw: "tool_calls" },
        usage: { inputTokens: { total: 1, noCache: 1, cacheRead: 0, cacheWrite: 0 }, outputTokens: { total: 1, text: 1, reasoning: 0 } },
        warnings: [],
      }) as any,
    });
    const r = await generateText({ model, tools: aiTools(), prompt: "check it" });
    assert.equal(r.toolResults.length, 1);
    assert.match(String(r.toolResults[0].output), /7 checks, 0 failed/);
    assert.match(lastUA, /via=ai-sdk\)$/);
  });
});

describe("LangChain", () => {
  test("tools invoke the same checks, tagged via=langchain", async () => {
    const tools = lcTools();
    assert.deepEqual(tools.map((t) => t.name).sort(), AGENT_TOOLS.map((t) => t.name).sort());
    const check = tools.find((t) => t.name === "x402_check_payment_required")!;
    assert.match(String(await check.invoke({ url: route })), /7 checks, 0 failed/);
    assert.match(lastUA, /via=langchain\)$/);
    const explain = tools.find((t) => t.name === "x402_explain_check")!;
    assert.match(String(await explain.invoke({ id: "P5" })), /^## P5/);
  });
});
