// C3, a client offered V2 keeps V2. The stock @x402/express retry server behind the facilitator double on loopback,
// on Solana devnet and Base Sepolia, with a proxy that adds a V1 body to its 402. The stock @x402/fetch client passes;
// a client that pays the V1 offer is caught, and nothing settles for it.
import { test } from "node:test";
import assert from "node:assert/strict";
import { startDouble } from "../src/double.js";
import { checkClientKeepsV2 } from "../src/client-version.js";
import { BASE_SEPOLIA, DEVNET, startRetryServer } from "../example/retry-server.js";
import { payingClient, type VersionFault } from "../example/client-version-clients.js";

const NETS = [["Solana devnet", DEVNET], ["Base Sepolia", BASE_SEPOLIA]] as const;

async function run(fault: VersionFault, network: string) {
  const double = await startDouble(0);
  const s = await startRetryServer(double.url, "", network);
  try { return await checkClientKeepsV2(payingClient(network, fault), s.url, double); } finally {
    await s.close();
    await double.close();
  }
}

for (const [name, net] of NETS) {
  test(`C3 control: the stock @x402/fetch client pays with V2 when the 402 also carries a V1 body, ${name}`, async () => {
    const r = await run("", net);
    assert.equal(r.check.split(" ")[0], "C3");
    assert.equal(r.pass, true, JSON.stringify(r));
    const d = r.detail as any;
    assert.deepEqual(d.offered, { v2_header: true, v1_body: true }, JSON.stringify(d));
    assert.equal(d.header, "PAYMENT-SIGNATURE", JSON.stringify(d));
    assert.equal(d.x402_version, 2, JSON.stringify(d));
    assert.equal(d.final_status, 200, JSON.stringify(d));
    assert.equal(d.successful_settles, 1, JSON.stringify(d));
  });
  test(`C3 v1_fallback: a client that pays the V1 offer when V2 is present is caught, ${name}`, async () => {
    const r = await run("v1_fallback", net);
    assert.equal(r.pass, false, JSON.stringify(r));
    const d = r.detail as any;
    assert.deepEqual(d.offered, { v2_header: true, v1_body: true }, JSON.stringify(d));
    assert.equal(d.header, "X-PAYMENT", JSON.stringify(d));
    assert.equal(d.x402_version, 1, JSON.stringify(d));
    assert.equal(d.forwarded, 0, JSON.stringify(d));
    assert.equal(d.successful_settles, 0, JSON.stringify(d));
    assert.match(d.error, /X-PAYMENT at x402Version 1/);
  });
}
