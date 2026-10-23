// R17, cache leakage: a server on @x402/core behind the facilitator double, with a shared cache on loopback in front
// of it, on Solana devnet and Base Sepolia. The control marks paid responses private; each faulty build is caught.
import assert from "node:assert/strict";
import { test } from "node:test";
import { startDouble } from "../src/double.js";
import { probeCacheLeak } from "../src/cache.js";
import { BASE_SEPOLIA, DEVNET, startCacheServer, type CacheFault } from "../example/cache-server.js";

const NETS = [["Solana devnet", DEVNET], ["Base Sepolia", BASE_SEPOLIA]] as const;

async function run(fault: CacheFault, network: string, path = "/paid") {
  const double = await startDouble(0);
  const s = await startCacheServer(double.url, fault, network);
  try {
    const [r] = await probeCacheLeak(`${s.base}${path}`, double, { network });
    return { r, d: r.detail as any, handled: s.handled };
  } finally { await s.close(); await double.close(); }
}

for (const [name, net] of NETS) {
  test(`R17 control: a server that marks paid responses private, no-store leaks nothing through a shared cache, ${name}`,
    async () => {
      const { r, d, handled } = await run("", net);
      assert.equal(r.pass, true, JSON.stringify(r, null, 1));
      assert.equal(d.paid.status, 200);
      assert.equal(d.paid.marked, true);
      assert.equal(d.unpaid_after.status, 402);
      assert.equal(d.unpaid_after.from_cache, false);
      assert.equal(d.charged, 1);
      assert.equal(handled, 1, "the handler ran once, for the paid request");
    });
  test(`R17 catches a server whose paid response is public and cacheable (cache_public), ${name}`, async () => {
    const { r, d } = await run("cache_public", net);
    assert.equal(r.pass, false, JSON.stringify(r, null, 1));
    assert.equal(d.paid.marked, false);
    assert.equal(d.unpaid_after.status, 200);
    assert.equal(d.unpaid_after.from_cache, true);
    assert.match(d.error, /leaked/);
  });
  test(`R17 catches a server that says nothing about caching, so a shared cache stores the paid response (no_cache_headers), ${name}`,
    async () => {
      const { r, d } = await run("no_cache_headers", net);
      assert.equal(r.pass, false, JSON.stringify(r, null, 1));
      assert.equal(d.paid.cache_control, null);
      assert.equal(d.unpaid_after.from_cache, true);
    });
  test(`R17 control: a URL that is not a paid route grades nothing and fails, ${name}`, async () => {
    const { r, d } = await run("", net, "/free");
    assert.equal(r.pass, false);
    assert.equal(r.status, "unsupported");
    assert.equal(d.unpaid_status, 200);
  });
}
