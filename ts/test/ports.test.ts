// The port helpers behind the CLI tests: fresh distinct ports, and a run that is repeated on new ports only when the
// CLI says a port was taken (#67).
import assert from "node:assert/strict";
import { test } from "node:test";
import { freePorts, PORT_TAKEN, withPorts, type CliResult } from "./ports.js";

const taken: CliResult = { code: 2, out: "", err: "x402conf-svm: port 5 on 127.0.0.1 is already in use; pick another with --port" };

test("freePorts hands out n distinct ephemeral ports", async () => {
  const ports = await freePorts(4);
  assert.equal(new Set(ports).size, 4, String(ports));
  for (const p of ports) assert.ok(p > 1024 && p < 65536, String(p));
});

test("the port-taken pattern matches the CLI's three messages and not a usage error", () => {
  assert.ok(PORT_TAKEN.test(taken.err));
  assert.ok(PORT_TAKEN.test("something is already answering at http://127.0.0.1:5/paid before --start ran"));
  assert.ok(PORT_TAKEN.test("Error: listen EADDRINUSE: address already in use 127.0.0.1:5"));
  assert.ok(!PORT_TAKEN.test("x402conf-svm: --port must be a number"));
});

test("withPorts runs again on fresh ports after a port-taken exit and returns the first other result", async () => {
  const seen: number[][] = [];
  const r = await withPorts(2, async (ports) => {
    seen.push(ports);
    return seen.length === 1 ? taken : { code: 1, out: "R14 FAIL", err: "" };
  });
  assert.equal(seen.length, 2);
  assert.equal(seen[0].length, 2);
  assert.notDeepEqual(seen[0], seen[1]);
  assert.equal(r.code, 1);
  assert.equal(r.out, "R14 FAIL");
});

test("withPorts never runs a pass, a real failure or a usage error again", async () => {
  for (const first of [{ code: 0, out: "pass", err: "" }, { code: 1, out: "FAIL R2", err: "" },
    { code: 2, out: "", err: "x402conf-svm: --port must be a number" }]) {
    let calls = 0;
    const r = await withPorts(1, async () => { calls++; return first; });
    assert.equal(calls, 1, JSON.stringify(first));
    assert.deepEqual(r, first);
  }
});

test("withPorts gives up after three attempts and says the ports were taken", async () => {
  let calls = 0;
  const r = await withPorts(1, async () => { calls++; return taken; });
  assert.equal(calls, 3);
  assert.equal(r.code, 2);
  assert.match(r.err, /already in use/);
  assert.match(r.err, /taken on all 3 attempts/);
});
