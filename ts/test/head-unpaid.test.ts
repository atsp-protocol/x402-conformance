// R16a: an unpaid HEAD on a paid route is answered 402 like GET, and the protected handler never runs. A server on
// @x402/core behind the facilitator double on loopback, on Solana devnet and Base Sepolia.
import assert from "node:assert/strict";
import { test } from "node:test";
import { startDouble } from "../src/double.js";
import { probeUnpaidHead } from "../src/head-unpaid.js";
import { BASE_SEPOLIA, DEVNET, startUnpaidHeadServer, type UnpaidHeadFault } from "../example/head-unpaid-server.js";

const NETS = [["Solana devnet", DEVNET], ["Base Sepolia", BASE_SEPOLIA]] as const;

async function run(fault: UnpaidHeadFault, network: string) {
  const double = await startDouble(0);
  const s = await startUnpaidHeadServer(double.url, fault, network);
  try {
    const [r] = await probeUnpaidHead(s.url);
    return { r, d: r.detail as any, handled: s.handled, settles: double.calls.filter((c) => c.path === "/settle").length };
  } finally { await s.close(); await double.close(); }
}

for (const [name, net] of NETS) {
  test(`R16a control: a paywall that covers HEAD answers it 402 and the handler never runs, ${name}`, async () => {
    const { r, d, handled, settles } = await run("", net);
    assert.equal(r.pass, true, JSON.stringify(r, null, 1));
    assert.equal(d.head_status, 402);
    assert.ok(d.head_offers > 0);
    assert.equal(handled, 0);
    assert.equal(settles, 0);
  });
  test(`R16a catches a paywall that matches only GET, so HEAD reaches the handler for free (head_bypass), ${name}`, async () => {
    const { r, d, handled } = await run("head_bypass", net);
    assert.equal(r.pass, false);
    assert.equal(d.head_status, 200);
    assert.equal(handled, 1, "the protected handler ran with no payment");
    assert.match(d.error, /reached the protected handler/);
  });
  test(`R16a control: a router that refuses HEAD with 405 and Allow: GET never reaches the handler, ${name}`, async () => {
    const { r, d, handled, settles } = await run("head_refused", net);
    assert.equal(r.pass, true, JSON.stringify(r, null, 1));
    assert.equal(d.head_status, 405);
    assert.equal(d.allow, "GET");
    assert.equal(handled, 0);
    assert.equal(settles, 0);
  });
  test(`R16a control: a URL that is not a paid route grades nothing, ${name}`, async () => {
    const double = await startDouble(0);
    const s = await startUnpaidHeadServer(double.url, "", net);
    try {
      const [r] = await probeUnpaidHead(s.url.replace("/paid", "/free"));
      assert.equal(r.status, "unsupported");
    } finally { await s.close(); await double.close(); }
  });
}
