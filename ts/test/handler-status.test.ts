// The paid response keeps the handler status. A local server behind the facilitator double, on
// Solana devnet and Base Sepolia. The control returns 201 and 302 with Location; the rewrite build is caught.
import assert from "node:assert/strict";
import { test } from "node:test";
import { startDouble } from "../src/double.js";
import { probeStatus } from "../src/status.js";
import { BASE_SEPOLIA, DEVNET, startStatusServer, type StatusFault } from "../example/status-server.js";

const NETS = [["Solana devnet", DEVNET], ["Base Sepolia", BASE_SEPOLIA]] as const;

async function run(fault: StatusFault, network: string) {
  const double = await startDouble(0);
  const s = await startStatusServer(double.url, fault, network);
  try {
    const [r] = await probeStatus({ created: `${s.base}/created`, redirect: `${s.base}/moved` }, double, { network });
    return { r, d: r.detail as any, handled: s.handled };
  } finally { await s.close(); await double.close(); }
}

for (const [name, net] of NETS) {
  test(`R22 control: a server that returns the handler status keeps 201 and 302 with Location, ${name}`, async () => {
    const { r, d, handled } = await run("", net);
    assert.equal(r.pass, true, JSON.stringify(r, null, 1));
    assert.equal(d.cases.created.status, 201);
    assert.equal(d.cases.created.settle_calls, 1);
    assert.equal(d.cases.redirect.status, 302);
    assert.equal(d.cases.redirect.location, "/created");
    assert.equal(d.cases.redirect.settle_calls, 1);
    assert.deepEqual(handled, { "/created": 1, "/moved": 1 });
  });
  test(`R22 catches a server that rewrites the paid response to 200 and drops Location, ${name}`, async () => {
    const { r, d } = await run("rewrite_200", net);
    assert.equal(r.pass, false);
    assert.equal(d.cases.created.status, 200);
    assert.equal(d.cases.redirect.status, 200);
    assert.equal(d.cases.redirect.location, "");
    assert.match(d.error, /answered 200/);
  });
}
