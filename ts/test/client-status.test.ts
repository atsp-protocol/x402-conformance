// C1, a client never hands a 402 to its caller as a success. Each client runs against the stock @x402/express retry
// server (ts/example/retry-server.ts, no fault) behind the facilitator double on loopback, on Solana devnet and Base
// Sepolia. The controls pass; the faulty build is caught.
import { test } from "node:test";
import assert from "node:assert/strict";
import { startDouble } from "../src/double.js";
import { checkClientHandles402, type PayingClient } from "../src/client-status.js";
import { BASE_SEPOLIA, DEVNET, startRetryServer } from "../example/retry-server.js";
import { decliningClient, statusCheckedClient, stockClient } from "../example/client-status-clients.js";

const NETS = [["Solana devnet", DEVNET], ["Base Sepolia", BASE_SEPOLIA]] as const;

async function run(client: PayingClient, network: string, path = "/report") {
  const double = await startDouble(0);
  const s = await startRetryServer(double.url, "", network);
  try { return await checkClientHandles402(client, `${s.base}${path}`, double); } finally { await s.close(); await double.close(); }
}

for (const [name, net] of NETS) {
  test(`C1 control: the stock @x402/fetch client pays the 402 and gets the content, ${name}`, async () => {
    const r = await run(stockClient(net), net);
    assert.equal(r.pass, true, JSON.stringify(r));
    assert.equal((r.detail as any).paid_attempts, 1, JSON.stringify(r.detail));
    assert.equal((r.detail as any).final_status, 200, JSON.stringify(r.detail));
    assert.equal((r.detail as any).successful_settles, 1, JSON.stringify(r.detail));
  });
  test(`C1 control: a stock @x402/fetch client whose policy declines the price rejects with a payment error, ${name}`,
    async () => {
      const r = await run(decliningClient(net), net);
      assert.equal(r.pass, true, JSON.stringify(r));
      assert.equal((r.detail as any).rejected, true, JSON.stringify(r.detail));
      assert.equal((r.detail as any).paid_attempts, 0, JSON.stringify(r.detail));
      assert.match((r.detail as any).client_error, /payment/i, JSON.stringify(r.detail));
    });
  test(`C1 control: a client whose status check passes every status but pays a 402 before the check gets the content, ${name}`,
    async () => {
      const r = await run(statusCheckedClient(net, ""), net);
      assert.equal(r.pass, true, JSON.stringify(r));
      assert.equal((r.detail as any).paid_attempts, 1, JSON.stringify(r.detail));
      assert.equal((r.detail as any).final_status, 200, JSON.stringify(r.detail));
    });
  test(`C1 accept_any_status: a client whose status check passes 402 through unpaid is caught, ${name}`, async () => {
    const r = await run(statusCheckedClient(net, "accept_any_status"), net);
    assert.equal(r.pass, false, JSON.stringify(r));
    assert.equal((r.detail as any).final_status, 402, JSON.stringify(r.detail));
    assert.equal((r.detail as any).paid_attempts, 0, JSON.stringify(r.detail));
    assert.equal((r.detail as any).rejected, false, JSON.stringify(r.detail));
    assert.equal((r.detail as any).successful_settles, 0, JSON.stringify(r.detail));
  });
  test(`C1 gate: a URL that is not a paid route fails the check and grades nothing, ${name}`, async () => {
    const r = await run(stockClient(net), net, "/free");
    assert.equal(r.pass, false, JSON.stringify(r));
    assert.match((r.detail as any).error, /nothing was graded/, JSON.stringify(r.detail));
  });
  test(`C1 gate: a client that rejects before it receives a 402 does not pass, ${name}`, async () => {
    const r = await run(async () => { throw new Error("no request sent"); }, net);
    assert.equal(r.pass, false, JSON.stringify(r));
    assert.equal((r.detail as any).requests, 0, JSON.stringify(r.detail));
    assert.match((r.detail as any).error, /never received a 402/, JSON.stringify(r.detail));
  });
}
