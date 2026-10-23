// C2, a client pays an offer within its own policy. The stock @x402/express retry server (no fault) behind the
// facilitator double on loopback, on Solana devnet and Base Sepolia. The check puts two decoys before the route's
// offer: the same offer on a network outside the client's set (index 0) and one on its network above its maximum
// (index 1). The control pays the route's offer (index 2); each faulty client signs a decoy and is caught.
import { test } from "node:test";
import assert from "node:assert/strict";
import { startDouble } from "../src/double.js";
import { checkClientOfferPolicy, type OfferPolicy } from "../src/client-offers.js";
import { BASE_SEPOLIA, DEVNET, startRetryServer } from "../example/retry-server.js";
import { offerClient, type OfferFault } from "../example/client-offers-clients.js";

const NETS = [["Solana devnet", DEVNET], ["Base Sepolia", BASE_SEPOLIA]] as const;
const MAX = "50000";   // the route asks 10000 ($0.01 in USDC)

async function run(fault: OfferFault, network: string) {
  const double = await startDouble(0);
  const s = await startRetryServer(double.url, "", network);
  const policy: OfferPolicy = { networks: [network], maxAmount: MAX };
  try {
    return await checkClientOfferPolicy(offerClient(policy, fault), s.url, double, policy);
  } finally { await s.close(); await double.close(); }
}

for (const [name, net] of NETS) {
  test(`C2 control: the stock x402Client pays the offer within its networks and maximum, ${name}`, async () => {
    const r = await run("", net);
    assert.equal(r.pass, true, JSON.stringify(r));
    const d = r.detail as any;
    assert.deepEqual(d.chosen, { index: 2, network: net, amount: "10000" }, JSON.stringify(d));
    assert.equal(d.payments.length, 1, JSON.stringify(d));
    assert.equal(d.final_status, 200, JSON.stringify(d));
    assert.equal(d.successful_settles, 1, JSON.stringify(d));
    assert.equal(d.error, undefined, JSON.stringify(d));
  });
  test(`C2 first_offer: a client that signs the first offer outside its policy is caught, ${name}`, async () => {
    const r = await run("first_offer", net);
    assert.equal(r.pass, false, JSON.stringify(r));
    const d = r.detail as any;
    assert.equal(d.chosen.index, 0, JSON.stringify(d));
    assert.notEqual(d.chosen.network, net, JSON.stringify(d));
    assert.match(d.error, /outside its configured networks/);
    assert.equal(d.successful_settles, 0, JSON.stringify(d));
  });
  test(`C2 ignore_max: a client that signs an offer above its maximum is caught, ${name}`, async () => {
    const r = await run("ignore_max", net);
    assert.equal(r.pass, false, JSON.stringify(r));
    const d = r.detail as any;
    assert.equal(d.chosen.index, 1, JSON.stringify(d));
    assert.equal(d.chosen.network, net, JSON.stringify(d));
    assert.ok(BigInt(d.chosen.amount) > BigInt(MAX), JSON.stringify(d));
    assert.match(d.error, /over its maximum/);
    assert.equal(d.successful_settles, 0, JSON.stringify(d));
  });
}
