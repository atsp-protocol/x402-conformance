// R15: no settlement when the paid handler fails. A server on @x402/core behind the facilitator double on loopback, on
// Solana devnet and Base Sepolia. The control settles only after a 2xx; each faulty build is caught.
import assert from "node:assert/strict";
import { test } from "node:test";
import { startDouble } from "../src/double.js";
import { probeDelivery } from "../src/delivery.js";
import { BASE_SEPOLIA, DEVNET, startDeliveryServer, type DeliveryFault } from "../example/delivery-server.js";

const NETS = [["Solana devnet", DEVNET], ["Base Sepolia", BASE_SEPOLIA]] as const;

async function run(fault: DeliveryFault, network: string) {
  const double = await startDouble(0);
  const s = await startDeliveryServer(double.url, fault, network);
  try {
    const [r] = await probeDelivery({ error: `${s.base}/fail`, redirect: `${s.base}/moved`, throws: `${s.base}/throws` }, double,
      { network });
    const ok = await fetch(`${s.base}/ok`);
    return { r, d: r.detail as any, handled: s.handled, okStatus: ok.status, double };
  } finally { await s.close(); await double.close(); }
}

for (const [name, net] of NETS) {
  test(`R15 control: a server that settles only after a 2xx charges nothing for a 500, a 302 or a throw, ${name}`, async () => {
    const { r, d, handled, okStatus } = await run("", net);
    assert.equal(r.pass, true, JSON.stringify(r, null, 1));
    for (const c of ["error", "redirect", "throws"]) {
      assert.equal(d.cases[c].settle_calls, 0, c);
      assert.equal(d.cases[c].payment_response, false, c);
    }
    assert.equal(d.cases.error.status, 500);
    assert.equal(d.cases.redirect.status, 302);
    assert.equal(d.cases.throws.status, 500);
    assert.deepEqual(handled, { "/fail": 1, "/moved": 1, "/throws": 1 }, "each handler ran once, for the paid request");
    assert.equal(okStatus, 402, "the control route is still paid");
  });
  test(`R15 catches a server that settles before the handler runs (settle_first), ${name}`, async () => {
    const { r, d } = await run("settle_first", net);
    assert.equal(r.pass, false);
    for (const c of ["error", "redirect", "throws"]) assert.equal(d.cases[c].settle_calls, 1, c);
    assert.match(d.error, /called \/settle/);
  });
  test(`R15 catches a server that settles anything below 400, so a redirect is charged (settle_below_400), ${name}`, async () => {
    const { r, d } = await run("settle_below_400", net);
    assert.equal(r.pass, false);
    assert.equal(d.cases.redirect.settle_calls, 1);
    assert.equal(d.cases.error.settle_calls, 0);
    assert.equal(d.cases.throws.settle_calls, 0);
  });
  test(`R15 control: a URL that is not a paid route grades nothing and fails, ${name}`, async () => {
    const double = await startDouble(0);
    const s = await startDeliveryServer(double.url, "", net);
    try {
      const [r] = await probeDelivery({ error: `${s.base}/nothing-here` }, double, { network: net });
      assert.equal(r.pass, false);
      assert.equal(r.status, "unsupported");
    } finally { await s.close(); await double.close(); }
  });
}
