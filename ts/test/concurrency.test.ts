// R12 and R13, one payment is at most one grant under concurrency: real @x402/express servers behind the facilitator
// double on loopback, on Solana devnet and Base Sepolia. The controls pass; each faulty build is caught.
import { test } from "node:test";
import assert from "node:assert/strict";
import { startDouble } from "../src/double.js";
import { probeParallel, probeReplicas } from "../src/concurrency.js";
import { BASE_SEPOLIA, DEVNET, newReplicaStore, startReplicaServer, type ReplicaFault } from "../example/replica-server.js";
import type { Result } from "../src/probe.js";

const NETS = [["Solana devnet", DEVNET], ["Base Sepolia", BASE_SEPOLIA]] as const;
const one = (id: string, rs: Result[]) => {
  const r = rs.find((x) => x.check.split(" ")[0] === id);
  assert.ok(r, `${id} missing from ${JSON.stringify(rs.map((x) => x.check))}`);
  return r;
};

async function parallel(fault: ReplicaFault, network: string, path = "/report") {
  const double = await startDouble(0);
  const s = await startReplicaServer(double.url, { fault, network });
  try { return { result: one("R12", await probeParallel(`${s.base}${path}`, double, { network })), double }; } finally {
    await s.close(); await double.close();
  }
}

async function replicas(shared: boolean, network: string, path = "/report") {
  const double = await startDouble(0);
  const store = newReplicaStore();
  const a = await startReplicaServer(double.url, { network, store });
  const b = await startReplicaServer(double.url, { network, store: shared ? store : newReplicaStore() });
  try {
    return { result: one("R13", await probeReplicas(`${a.base}${path}`, `${b.base}${path}`, double, { network })), double };
  } finally {
    await a.close(); await b.close(); await double.close();
  }
}

for (const [name, net] of NETS) {
  test(`R12 control: a record that reserves the key before it awaits settles one of eight parallel requests and serves them, ${name}`,
    async () => {
      const { result } = await parallel("", net);
      assert.equal(result.pass, true, JSON.stringify(result));
      const d = result.detail as any;
      assert.equal(d.successful_settles, 1);
      assert.equal(d.served, 8, JSON.stringify(d));
    });
  test(`R12 catches a non-atomic check-then-set: parallel requests with one payment identifier are each settled, ${name}`,
    async () => {
      const { result } = await parallel("check_then_set", net);
      assert.equal(result.pass, false, JSON.stringify(result));
      assert.ok((result.detail as any).successful_settles > 1, JSON.stringify(result.detail));
      assert.match(String((result.detail as any).error), /charged \d+ times/);
    });
  test(`R12 gate: a URL that is not a paid route fails and settles nothing, ${name}`, async () => {
    const { result, double } = await parallel("", net, "/missing");
    assert.equal(result.pass, false, JSON.stringify(result));
    assert.equal(double.calls.filter((c) => c.path === "/settle").length, 0);
  });
  test(`R13 control: two replicas sharing one record settle the payment identifier once and serve it from both, ${name}`,
    async () => {
      const { result } = await replicas(true, net);
      assert.equal(result.pass, true, JSON.stringify(result));
      const d = result.detail as any;
      assert.equal(d.successful_settles, 1);
      assert.equal(d.served, 4, JSON.stringify(d));
    });
  test(`R13 catches a per-process in-memory cache: the second replica settles the payment identifier again, ${name}`,
    async () => {
      const { result } = await replicas(false, net);
      assert.equal(result.pass, false, JSON.stringify(result));
      assert.ok((result.detail as any).successful_settles > 1, JSON.stringify(result.detail));
    });
  test(`R13 gate: a URL that is not a paid route fails and settles nothing, ${name}`, async () => {
    const { result, double } = await replicas(true, net, "/missing");
    assert.equal(result.pass, false, JSON.stringify(result));
    assert.equal(double.calls.filter((c) => c.path === "/settle").length, 0);
  });
}
