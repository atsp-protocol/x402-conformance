// R19, upfront and escrow flows: a server on @x402/core behind the facilitator double on loopback, on Solana devnet
// and Base Sepolia. The control runs the resource only behind a passed check; each faulty build is caught. The probe
// reads the server's own execution count, so a resource that ran behind a refusal is graded, not only inferred.
import assert from "node:assert/strict";
import { test } from "node:test";
import { startDouble } from "../src/double.js";
import { probeFlows } from "../src/flow.js";
import { BASE_SEPOLIA, DEVNET, startFlowServer, type FlowFault } from "../example/flow-server.js";

const NETS = [["Solana devnet", DEVNET], ["Base Sepolia", BASE_SEPOLIA]] as const;

async function run(fault: FlowFault, network: string, path = "/upfront") {
  const double = await startDouble(0);
  const s = await startFlowServer(double.url, fault, network);
  try {
    const [r] = await probeFlows(`${s.base}${path}`, double, { network, executed: () => s.handled[path] ?? 0 });
    return { r, d: r.detail as any, handled: { ...s.handled } };
  } finally { await s.close(); await double.close(); }
}

for (const [name, net] of NETS) {
  test(`R19 control: an upfront route that settles before the handler runs it once, behind a passed check only, ${name}`,
    async () => {
      const { r, d, handled } = await run("", net);
      assert.equal(r.pass, true, JSON.stringify(r, null, 1));
      assert.equal(d.declared_flow, "upfront");
      assert.equal(d.cases.check_fails.status, 402);
      assert.ok(d.cases.check_fails.reason, "the refusal says why");
      assert.equal(d.cases.check_fails.executed, 0);
      assert.equal(d.cases.check_passes.served, true);
      assert.equal(d.cases.check_passes.charged, 1);
      assert.equal(d.cases.check_passes.payment_response, true, "the before-handler settlement is echoed");
      assert.equal(d.cases.wrong_flow.settle_calls, 0);
      assert.equal(d.cases.unknown_flow.settle_calls, 0);
      assert.equal(handled["/upfront"], 1, "the handler ran once, for the payment the check passed");
    });
  test(`R19 catches a server that runs the handler before any check (execute_first), ${name}`, async () => {
    const { r, d, handled } = await run("execute_first", net);
    assert.equal(r.pass, false, JSON.stringify(r, null, 1));
    assert.equal(d.cases.check_fails.executed, 1);
    assert.match(d.error, /executed before a check had passed/);
    assert.ok(handled["/upfront"] >= 2, "the handler ran behind refusals too");
  });
  test(`R19 catches a server that takes a payment signed for a flow it never offered (accept_any_flow), ${name}`, async () => {
    const { r, d } = await run("accept_any_flow", net);
    assert.equal(r.pass, false, JSON.stringify(r, null, 1));
    assert.equal(d.cases.wrong_flow.served, true);
    assert.equal(d.cases.wrong_flow.settle_calls, 1);
    assert.match(d.error, /did not offer, was served/);
  });
  test(`R19 control: a route with no upfront or escrow offer grades nothing and fails, ${name}`, async () => {
    const { r, d } = await run("", net, "/authorization");
    assert.equal(r.pass, false);
    assert.equal(r.status, "unsupported");
    assert.equal(d.declared_flow, null);
  });
  test(`R19 control: a URL that is not a paid route grades nothing and fails, ${name}`, async () => {
    const { r } = await run("", net, "/free");
    assert.equal(r.status, "unsupported");
  });
}
