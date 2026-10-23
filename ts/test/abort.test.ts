// R23, a client abort during settle: the client drops its connection while the server's /settle is in flight. Real
// @x402/express servers behind the facilitator double on loopback, on Solana devnet and Base Sepolia. The control
// passes; each faulty build is caught.
import { test } from "node:test";
import assert from "node:assert/strict";
import { startDouble } from "../src/double.js";
import { probeAbort } from "../src/abort.js";
import { BASE_SEPOLIA, DEVNET, startRetryServer, type RetryFault } from "../example/retry-server.js";
import type { Result } from "../src/probe.js";

const NETS = [["Solana devnet", DEVNET], ["Base Sepolia", BASE_SEPOLIA]] as const;
const r23 = (rs: Result[]) => {
  const r = rs.find((x) => x.check.split(" ")[0] === "R23");
  assert.ok(r, `R23 missing from ${JSON.stringify(rs.map((x) => x.check))}`);
  return r;
};

async function run(fault: RetryFault, network: string, path = "") {
  const double = await startDouble(0);
  const s = await startRetryServer(double.url, fault, network);
  try {
    return { result: r23(await probeAbort(path ? `${s.base}${path}` : s.url, double, { network })), double };
  } finally { await s.close(); await double.close(); }
}

for (const [name, net] of NETS) {
  test(`R23 control: the stock @x402/express server with an idempotency record returns the settled result after the client aborted, ${name}`,
    async () => {
      const { result } = await run("", net);
      assert.equal(result.pass, true, JSON.stringify(result));
      const d = result.detail as any;
      assert.equal(d.settled_on_abort, 1, JSON.stringify(d));
      assert.equal(d.successful_settles, 1, JSON.stringify(d));
      assert.ok(d.resend.status >= 200 && d.resend.status < 300, JSON.stringify(d));
      assert.equal(d.resend.settlement_ref, d.first_transaction, "the resend names the original transaction");
    });
  test(`R23 record_on_delivery: a server that records the result only once the response is delivered loses it when the client aborts, ${name}`,
    async () => {
      const { result } = await run("record_on_delivery", net);
      assert.equal(result.pass, false, JSON.stringify(result));
      const d = result.detail as any;
      assert.equal(d.settled_on_abort, 1, JSON.stringify(d));
      assert.equal(d.successful_settles, 1, "the double refuses the duplicate, so nothing is charged twice");
      assert.match(String(d.error), /did not return the settled result/);
    });
  test(`R23 settle_both: a server with no idempotency record loses the settled result when the client aborts, ${name}`,
    async () => {
      const { result, double } = await run("settle_both", net);
      assert.equal(result.pass, false, JSON.stringify(result));
      assert.equal((result.detail as any).successful_settles, 1, JSON.stringify(result.detail));
      assert.ok(double.calls.filter((c) => c.path === "/settle").length >= 2, "the resend was settled again and refused");
    });
  test(`R23 control: a URL that is not a paid route fails and settles nothing, ${name}`, async () => {
    const { result, double } = await run("", net, "/free");
    assert.equal(result.pass, false, JSON.stringify(result));
    assert.equal(double.calls.filter((c) => c.path === "/settle").length, 0);
  });
}
