// R21, settlement preemption for Permit2, against the facilitator double on Base Sepolia. The control serves only on
// its own successful settle; a build that reads a spent nonce as paid and a build that serves before settling are
// each caught, and a route that does not offer Permit2 is not graded.
import assert from "node:assert/strict";
import { test } from "node:test";
import { startDouble } from "../src/double.js";
import { probePreempt } from "../src/preempt.js";
import { startPreemptServer, type PreemptFault } from "../example/preempt-server.js";

async function run(fault: PreemptFault, method = "permit2") {
  const double = await startDouble(0);
  const s = await startPreemptServer(double.url, fault, method);
  try {
    const [r] = await probePreempt(`${s.base}/paid`, double);
    return { r, d: r.detail as any, handled: s.handled, settles: double.calls.filter((c) => c.path === "/settle").length,
      successes: double.successes.length };
  } finally { await s.close(); await double.close(); }
}

test("R21 control: a server that serves only on its own settle refuses a preempted Permit2 payment, Base Sepolia", async () => {
  const { r, d, handled, successes } = await run("");
  assert.equal(r.pass, true, JSON.stringify(r, null, 1));
  assert.equal(d.cases.preempted.served, false);
  assert.equal(d.cases.preempted.settle_calls, 1);
  assert.equal(d.cases.preempted_resend.served, false);
  assert.equal(d.cases.reference.served, true);
  assert.equal(d.cases.resend.served, false);
  assert.equal(d.third_party_settlements, 1);
  assert.equal(successes, 1);
  assert.equal(handled, 1);
});

test("R21 catches a server that reads a spent Permit2 nonce as paid, Base Sepolia", async () => {
  const { r, d } = await run("nonce_used_is_paid");
  assert.equal(r.pass, false);
  assert.equal(d.cases.preempted.served, true);
  assert.equal(d.cases.resend.served, true);
  assert.match(d.error, /settlement a third party made/);
  assert.match(d.error, /granted a second time/);
});

test("R21 catches a server that serves a Permit2 payment before its settle, Base Sepolia", async () => {
  const { r, d } = await run("serve_before_settle");
  assert.equal(r.pass, false);
  assert.equal(d.cases.preempted.served, true);
  assert.match(d.error, /preempted: served/);
});

test("R21 gate: a route that offers EIP-3009, not Permit2, is not graded and nothing is paid, Base Sepolia", async () => {
  const { r, settles } = await run("", "eip3009");
  assert.equal(r.pass, false);
  assert.equal(r.status, "unsupported");
  assert.equal(settles, 0);
});
