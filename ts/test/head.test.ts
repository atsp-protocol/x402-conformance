// R16: a HEAD request carrying a payment is refused and never settled. A server on @x402/core behind the facilitator
// double on loopback, on Solana devnet and Base Sepolia. XC-18 AC02.
import assert from "node:assert/strict";
import { test } from "node:test";
import { startDouble } from "../src/double.js";
import { probeHead } from "../src/head.js";
import { BASE_SEPOLIA, DEVNET, startHeadServer, type HeadFault } from "../example/head-server.js";

const NETS = [["Solana devnet", DEVNET], ["Base Sepolia", BASE_SEPOLIA]] as const;

async function run(fault: HeadFault, network: string) {
  const double = await startDouble(0);
  const s = await startHeadServer(double.url, fault, network);
  try {
    const [r] = await probeHead(s.url, double, { network });
    return { r, d: r.detail as any, handled: { ...s.handled } };
  } finally { await s.close(); await double.close(); }
}

for (const [name, net] of NETS) {
  test(`R16 control: a server that refuses a paid HEAD with a 402 and settles nothing passes, ${name}`, async () => {
    const { r, d, handled } = await run("", net);
    assert.equal(r.pass, true, JSON.stringify(r, null, 1));
    assert.equal(d.head_status, 402);
    assert.equal(d.settle_calls, 0);
    assert.equal(d.payment_response, false);
    assert.deepEqual(handled, { GET: 0, HEAD: 0 });
  });
  test(`R16 catches a server that settles a paid HEAD as if it were a GET (head_settles), ${name}`, async () => {
    const { r, d, handled } = await run("head_settles", net);
    assert.equal(r.pass, false);
    assert.equal(d.settle_calls, 1, JSON.stringify(d));
    assert.equal(d.charged, 1);
    assert.equal(handled.HEAD, 1);
    assert.match(d.error, /HEAD/);
  });
  test(`R16 control: a URL that is not a paid route grades nothing, ${name}`, async () => {
    const double = await startDouble(0);
    const s = await startHeadServer(double.url, "", net);
    try {
      const [r] = await probeHead(s.url.replace("/paid", "/free"), double, { network: net });
      assert.equal(r.status, "unsupported");
      assert.equal(double.calls.filter((c) => c.path === "/settle").length, 0);
    } finally { await s.close(); await double.close(); }
  });
}
