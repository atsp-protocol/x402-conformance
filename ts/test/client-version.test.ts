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

async function run(fault: VersionFault | "no_signing", network: string, signsPayments?: boolean) {
  const double = await startDouble(0);
  const s = await startRetryServer(double.url, "", network);
  const client = fault === "no_signing" ? (u: string) => fetch(u) : payingClient(network, fault);
  try {
    return await checkClientKeepsV2(client, s.url, double, signsPayments === undefined ? {} : { signsPayments });
  } finally {
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

for (const [name, net] of NETS) {
  test(`C3 not applicable: a client declared not to sign that hands the 402 back is graded not_applicable, ${name}`, async () => {
    const r = await run("no_signing", net, false);
    assert.equal(r.status, "not_applicable", JSON.stringify(r));
    assert.equal((r.detail as any).final_status, 402);
  });
  test(`C3 a client that never pays without the declaration still fails, ${name}`, async () => {
    const r = await run("no_signing", net);
    assert.equal(r.status, "fail", JSON.stringify(r));
    assert.match((r.detail as any).error, /never paid/);
  });
  test(`C3 a client declared not to sign that pays V1 anyway is caught (v1_fallback), ${name}`, async () => {
    const r = await run("v1_fallback", net, false);
    assert.equal(r.status, "fail", JSON.stringify(r));
    assert.match((r.detail as any).error, /X-PAYMENT at x402Version 1/);
  });
}
