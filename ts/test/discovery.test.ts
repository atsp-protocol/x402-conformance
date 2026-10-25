// D1 against a loopback Bazaar discovery API, and G1 against a loopback A2A agent whose paid skill mirrors an HTTP
// route behind the facilitator double (Base Sepolia). Each control passes and each faulty build is caught.
import assert from "node:assert/strict";
import { test } from "node:test";
import { startDouble } from "../src/double.js";
import { checkA2aMirrorsHttp, checkDiscovery } from "../src/discovery.js";
import { startA2aAgent, startDiscoveryServer, type A2aFault, type DiscoveryFault } from "../example/discovery-server.js";

async function d1(fault: DiscoveryFault) {
  const s = await startDiscoveryServer(fault);
  try { const [r] = await checkDiscovery(s.base); return { r, d: r.detail as any }; } finally { await s.close(); }
}
async function g1(fault: A2aFault) {
  const double = await startDouble(0);
  const s = await startA2aAgent(double.url, fault);
  try {
    const [r] = await checkA2aMirrorsHttp({ a2aUrl: `${s.base}/a2a`, httpUrl: `${s.base}/generate` });
    return { r, d: r.detail as any, settles: double.calls.filter((c) => c.path === "/settle").length };
  } finally { await s.close(); await double.close(); }
}

test("D1 control: a discovery API in the V2 section 8 shapes that honours limit and the network filter", async () => {
  const { r, d } = await d1("");
  assert.equal(r.pass, true, JSON.stringify(r, null, 1));
  assert.equal(d.items, 2);
  assert.equal(d.network_filter.off_network, 0);
});
test("D1 catches a discovery API whose items lack x402Version, lastUpdated and maxTimeoutSeconds", async () => {
  const { r, d } = await d1("v1_items");
  assert.equal(r.pass, false);
  assert.match(d.error, /lastUpdated is not an ISO 8601 timestamp/);
  assert.match(d.error, /x402Version is not a number/);
  assert.match(d.error, /maxTimeoutSeconds is not a number/);
});
test("D1 catches a discovery API that ignores limit and the network filter", async () => {
  const { r, d } = await d1("ignore_filters");
  assert.equal(r.pass, false);
  assert.match(d.error, /returned 3 items for limit=2/);
  assert.ok(d.network_filter.off_network > 0);
});
test("D1 gate: a facilitator with no discovery endpoints is unsupported, not failed", async () => {
  const double = await startDouble(0);
  try {
    const [r] = await checkDiscovery(double.url);
    assert.equal(r.status, "unsupported");
  } finally { await double.close(); }
});

test("G1 control: an A2A agent's input-required task carries the HTTP route's PAYMENT-REQUIRED accepts, Base Sepolia", async () => {
  const { r, d, settles } = await g1("");
  assert.equal(r.pass, true, JSON.stringify(r, null, 1));
  assert.equal(d.state, "input-required");
  assert.deepEqual(d.a2a_accepts, d.http_accepts);
  assert.equal(settles, 0);
});
test("G1 catches an A2A agent whose requirements carry a different price from the HTTP 402, Base Sepolia", async () => {
  const { r, d } = await g1("stale_price");
  assert.equal(r.pass, false);
  assert.match(d.error, /differ from the HTTP 402/);
});
test("G1 catches an A2A agent that answers a failed task with the requirements only in text, Base Sepolia", async () => {
  const { r, d } = await g1("not_input_required");
  assert.equal(r.pass, false);
  assert.match(d.error, /not input-required/);
  assert.match(d.error, /x402.payment.required is missing/);
});
