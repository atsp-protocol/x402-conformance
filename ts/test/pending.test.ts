// R18, a pending, late or unanswered settlement: a server on @x402/core behind the facilitator double on loopback, on
// Solana devnet and Base Sepolia. The control ends every case explicit and reconcilable; each faulty build is caught.
import assert from "node:assert/strict";
import { test } from "node:test";
import { startDouble } from "../src/double.js";
import { probePending } from "../src/pending.js";
import { BASE_SEPOLIA, DEVNET, startPendingServer, type PendingFault } from "../example/pending-server.js";

const NETS = [["Solana devnet", DEVNET], ["Base Sepolia", BASE_SEPOLIA]] as const;

async function run(fault: PendingFault, network: string, path = "/paid") {
  const double = await startDouble(0);
  const s = await startPendingServer(double.url, fault, network);
  try {
    const [r] = await probePending(`${s.base}${path}`, double, { network });
    return { r, d: r.detail as any, served: s.served, double };
  } finally { await s.close(); await double.close(); }
}

for (const [name, net] of NETS) {
  test(`R18 control: a server that refuses while pending, names the payment, and serves once when final passes, ${name}`,
    async () => {
      const { r, d, served, double } = await run("", net);
      assert.equal(r.pass, true, JSON.stringify(r, null, 1));
      const a = d.pending_then_success;
      assert.equal(a.pending.status, 402);
      assert.equal(a.pending.surfaced, true, "the pending answer names the transaction");
      assert.equal(a.retry.served, true);
      assert.equal(a.again.served, true, "a further retry is replayed from the record");
      assert.equal(a.successful_settles, 1);
      for (const x of d.pending_until_deadline.answers) { assert.equal(x.status, 402); assert.equal(x.surfaced, true); }
      const c = d.late_success;
      assert.equal(c.lost.status, 402);
      assert.equal(c.lost.surfaced, true, "an unanswered settle names the payment");
      assert.equal(c.served, 0, "with no record of a delivery, a duplicate is refused and named, not served");
      assert.equal(served, 1, "the handler served exactly once, for the final payment");
      assert.equal(double.successes.length, 2, "one success per settled payment: the final one and the lost one");
    });
  test(`R18 catches a server that serves on settlement_pending (serve_on_pending), ${name}`, async () => {
    const { r, d } = await run("serve_on_pending", net);
    assert.equal(r.pass, false, JSON.stringify(r, null, 1));
    assert.equal(d.pending_then_success.pending.served, true);
    assert.match(d.error, /served while the settlement was pending/);
  });
  test(`R18 catches a server that refuses a pending or lost settlement without naming the payment (swallow_pending), ${name}`,
    async () => {
      const { r, d } = await run("swallow_pending", net);
      assert.equal(r.pass, false, JSON.stringify(r, null, 1));
      assert.equal(d.pending_then_success.pending.surfaced, false);
      assert.match(d.error, /surfaced neither/);
    });
  test(`R18 control: a URL that is not a paid route grades nothing and fails, ${name}`, async () => {
    const { r } = await run("", net, "/free");
    assert.equal(r.pass, false);
    assert.equal(r.status, "unsupported");
  });
}
