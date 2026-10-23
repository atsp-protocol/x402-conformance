// The paid response keeps the handler's 2xx status and headers. A local server behind the facilitator double, on
// Solana devnet and Base Sepolia. The control returns 201 with Location and 202 with Content-Location; the rewrite
// build is caught, and a non-2xx expectation is refused because a paid 3xx is never settled (R15).
import assert from "node:assert/strict";
import { test } from "node:test";
import { startDouble } from "../src/double.js";
import { probeStatus, type StatusRoutes } from "../src/status.js";
import { BASE_SEPOLIA, DEVNET, startStatusServer, type StatusFault } from "../example/status-server.js";

const NETS = [["Solana devnet", DEVNET], ["Base Sepolia", BASE_SEPOLIA]] as const;

const routesFor = (base: string): StatusRoutes => ({
  created: { url: `${base}/created`, status: 201, headers: ["location"] },
  accepted: { url: `${base}/accepted`, status: 202, headers: ["content-location"] },
});

async function run(fault: StatusFault, network: string, routes = routesFor) {
  const double = await startDouble(0);
  const s = await startStatusServer(double.url, fault, network);
  try {
    const [r] = await probeStatus(routes(s.base), double, { network });
    return { r, d: r.detail as any, handled: s.handled, settles: double.calls.filter((c) => c.path === "/settle").length };
  } finally { await s.close(); await double.close(); }
}

for (const [name, net] of NETS) {
  test(`R22 control: a server that returns the handler status keeps 201 and 202 with their headers, ${name}`, async () => {
    const { r, d, handled } = await run("", net);
    assert.equal(r.pass, true, JSON.stringify(r, null, 1));
    assert.equal(d.cases.created.status, 201);
    assert.equal(d.cases.created.headers.location, "/created/1");
    assert.equal(d.cases.created.settle_calls, 1);
    assert.equal(d.cases.accepted.status, 202);
    assert.equal(d.cases.accepted.headers["content-location"], "/jobs/1");
    assert.equal(d.cases.accepted.settle_calls, 1);
    assert.deepEqual(handled, { "/created": 1, "/accepted": 1 });
  });
  test(`R22 catches a server that rewrites the paid response to 200 and drops the handler headers, ${name}`, async () => {
    const { r, d } = await run("rewrite_200", net);
    assert.equal(r.pass, false);
    assert.equal(d.cases.created.status, 200);
    assert.equal(d.cases.accepted.status, 200);
    assert.equal(d.cases.created.headers.location, "");
    assert.match(d.error, /answered 200/);
  });
  test(`R22 gate: a 3xx expectation is refused and nothing is paid, ${name}`, async () => {
    const { r, d, settles } = await run("", net, (base) => ({ moved: { url: `${base}/created`, status: 302 } }));
    assert.equal(r.pass, false);
    assert.equal(r.status, "unsupported");
    assert.equal(settles, 0);
    assert.match(d.error, /not 2xx/);
  });
}
