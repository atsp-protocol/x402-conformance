// W1 to W3, the sign-in-with-x server rules, against a paid route behind the facilitator double on Base Sepolia. The
// control is the shipped extension with a configured origin and a nonce-tracking storage; each faulty build is caught
// by its own check and passes the other two.
import assert from "node:assert/strict";
import { test } from "node:test";
import { startDouble } from "../src/double.js";
import { probeSiwx } from "../src/siwx.js";
import { startSiwxRulesServer, type SiwxFault } from "../example/siwx-server.js";

async function run(fault: SiwxFault) {
  const double = await startDouble(0);
  const s = await startSiwxRulesServer(double.url, fault);
  try {
    const r = await probeSiwx(`${s.base}/report`, double);
    const by = Object.fromEntries(r.map((x) => [x.check.split(" ")[0], x]));
    return { by, d: (id: string) => by[id].detail as any, successes: double.successes.length };
  } finally { await s.close(); await double.close(); }
}

test("W1 control: the shipped extension with a configured origin refuses a message signed for another site, Base Sepolia", async () => {
  const { by, d, successes } = await run("");
  assert.equal(by.W1.pass, true, JSON.stringify(by.W1, null, 1));
  assert.equal(d("W1").control_status, 200);
  assert.equal(d("W1").host_header, 402);
  assert.equal(d("W1").x_forwarded_host, 402);
  assert.equal(successes, 1);
});
test("W1 catches a server that takes its sign-in-with-x origin from Host or X-Forwarded-Host, Base Sepolia", async () => {
  const { by, d } = await run("origin_from_host");
  assert.equal(by.W1.pass, false);
  assert.equal(d("W1").host_header, 200);
  assert.equal(d("W1").x_forwarded_host, 200);
  assert.equal(by.W2.pass, true);
  assert.equal(by.W3.pass, true);
});
test("W2 control: a storage that tracks nonces refuses the same signed message the second time, Base Sepolia", async () => {
  const { by, d } = await run("");
  assert.equal(by.W2.pass, true, JSON.stringify(by.W2, null, 1));
  assert.equal(d("W2").first_use, 200);
  assert.equal(d("W2").second_use, 402);
});
test("W2 catches a server whose sign-in-with-x storage does not track nonces, Base Sepolia", async () => {
  const { by, d } = await run("no_nonce_store");
  assert.equal(by.W2.pass, false);
  assert.equal(d("W2").second_use, 200);
  assert.equal(by.W1.pass, true);
  assert.equal(by.W3.pass, true);
});
test("W3 control: the shipped validation refuses a stale or future issuedAt and an expired message, Base Sepolia", async () => {
  const { by, d } = await run("");
  assert.equal(by.W3.pass, true, JSON.stringify(by.W3, null, 1));
  assert.deepEqual(d("W3").cases, { issued_at_too_old: 402, issued_at_in_future: 402, expired: 402 });
});
test("W3 catches a server that does not check issuedAt or expirationTime, Base Sepolia", async () => {
  const { by, d } = await run("no_time_window");
  assert.equal(by.W3.pass, false);
  assert.deepEqual(d("W3").cases, { issued_at_too_old: 200, issued_at_in_future: 200, expired: 200 });
  assert.equal(by.W1.pass, true);
  assert.equal(by.W2.pass, true);
});
