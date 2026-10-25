// U1-U3 (upto) and B1-B3 (batch-settlement) against the scheme double, on Solana devnet and Base Sepolia. The upto
// control is a server on @x402/core with the stock upto scheme servers; the batch-settlement control keeps the
// per-channel state the bindings ask of a server. Each check passes its control and catches its faulty build, and a
// route that offers neither scheme is not graded.
import assert from "node:assert/strict";
import { test } from "node:test";
import { probeBatch, probeUpto, startSchemeDouble } from "../src/schemes.js";
import { BASE_SEPOLIA, DEVNET, startUptoServer, type UptoFault } from "../example/upto-server.js";
import { startBatchServer, type BatchFault } from "../example/batch-server.js";

const NETS = [["Solana devnet", DEVNET], ["Base Sepolia", BASE_SEPOLIA]] as const;

async function upto(fault: UptoFault, network: string, units = 300) {
  const double = await startSchemeDouble(0);
  const s = await startUptoServer(double.url, fault, network);
  try {
    const [u1, u2, u3] = await probeUpto(`${s.base}/metered?units=${units}`, double, { network });
    return { u1, u2, u3, d1: u1.detail as any, d2: u2.detail as any, d3: u3.detail as any, handled: s.handled,
      settles: double.settles };
  } finally { await s.close(); await double.close(); }
}

async function batch(fault: BatchFault, network: string) {
  const double = await startSchemeDouble(0);
  const s = await startBatchServer(double.url, fault, network);
  try {
    const [b1, b2, b3] = await probeBatch(`${s.base}/api`, double, { network, redeem: () => s.redeem() });
    return { b1, b2, b3, d1: b1.detail as any, d2: b2.detail as any, d3: b3.detail as any, settles: double.settles };
  } finally { await s.close(); await double.close(); }
}

for (const [name, net] of NETS) {
  test(`U1 control: a stock upto server charges metered usage below the maximum as metered, ${name}`, async () => {
    const { u1, d1, settles } = await upto("", net, 300);
    assert.equal(u1.pass, true, JSON.stringify(u1, null, 1));
    assert.equal(d1.served, true);
    assert.equal(settles.filter((x) => x.type !== "deposit").at(-1)?.amount, "3000");
  });
  test(`U1 control: a stock upto server caps usage above the maximum at the maximum, ${name}`, async () => {
    const { u1, settles } = await upto("", net, 5000);
    assert.equal(u1.pass, true, JSON.stringify(u1, null, 1));
    assert.equal(settles.filter((x) => x.type !== "deposit").at(-1)?.amount, "10000");
  });
  test(`U1 catches a server that charges metered usage above the authorised maximum (no_cap), ${name}`, async () => {
    const { u1, d1 } = await upto("no_cap", net, 5000);
    assert.equal(u1.pass, false, JSON.stringify(u1, null, 1));
    assert.match(d1.error, /settle 50000 against an authorised maximum of 10000/);
  });
  test(`U2 control: the stock server's PAYMENT-RESPONSE reports the amount it settled, ${name}`, async () => {
    const { u2, d2 } = await upto("", net, 300);
    assert.equal(u2.pass, true, JSON.stringify(u2, null, 1));
    assert.equal(d2.reported.amount, "3000");
  });
  test(`U2 catches a server that reports the authorised maximum instead of the settled amount (report_max), ${name}`,
    async () => {
      const { u1, u2, d2 } = await upto("report_max", net, 300);
      assert.equal(u1.pass, true, "the charge itself is within the maximum");
      assert.equal(u2.pass, false, JSON.stringify(u2, null, 1));
      assert.match(d2.error, /reports 10000, the settle charged 3000/);
    });
  test(`U3 control: the stock upto offer declares no flow but the binding's own, ${name}`, async () => {
    const { u3, d3 } = await upto("", net);
    assert.equal(u3.pass, true, JSON.stringify(u3, null, 1));
    assert.notEqual(d3.declared_flow, "upfront");
  });
  test(`U3 catches a server whose upto offer declares the upfront flow (upfront_flow), ${name}`, async () => {
    const { u3, d3 } = await upto("upfront_flow", net);
    assert.equal(u3.pass, false, JSON.stringify(u3, null, 1));
    assert.equal(d3.declared_flow, "upfront");
    assert.match(d3.error, /cannot be upfront/);
  });

  test(`B1 control: each commitment is served once with its identifier and charge, and a spent voucher is refused, ${name}`,
    async () => {
      const { b1, d1 } = await batch("", net);
      assert.equal(b1.pass, true, JSON.stringify(b1, null, 1));
      // Two paid requests on each of three channels, then the replay (later requests belong to B3).
      assert.equal(d1.requests.slice(0, 6).every((r: any) => r.served), true);
      assert.equal(d1.requests[6].served, false, "the replayed voucher is refused");
      assert.equal(d1.requests[6].status, 402);
    });
  test(`B1 catches a server that serves a voucher it has already been paid with (accept_replay), ${name}`, async () => {
    const { b1, d1 } = await batch("accept_replay", net);
    assert.equal(b1.pass, false, JSON.stringify(b1, null, 1));
    assert.match(d1.error, /already spent was served a second time/);
  });
  test(`B2 control: one redemption run claims each channel once at its latest voucher, and an idle run claims nothing, ${name}`,
    async () => {
      const { b2, d2 } = await batch("", net);
      assert.equal(b2.pass, true, JSON.stringify(b2, null, 1));
      assert.equal(d2.run1.report.length, 3);
      assert.equal(d2.run2.claims, 0);
    });
  test(`B2 catches a server that claims every voucher it stored, not each channel's latest (claim_every_voucher), ${name}`,
    async () => {
      const { b2, d2 } = await batch("claim_every_voucher", net);
      assert.equal(b2.pass, false, JSON.stringify(b2, null, 1));
      assert.match(d2.error, /claimed channel .* 2 times/);
    });
  test(`B3 control: a partly failed run reports each channel's own outcome and claims only the failed ones again, ${name}`,
    async () => {
      const { b3, d3 } = await batch("", net);
      assert.equal(b3.pass, true, JSON.stringify(b3, null, 1));
      assert.ok(d3.failed_claims >= 1);
      assert.ok(d3.run3.report.some((x: any) => x.ok) && d3.run3.report.some((x: any) => !x.ok), "a partial failure");
      assert.equal(d3.run4.claimed, d3.failed_claims);
    });
  test(`B3 catches a server that records a failed claim batch as claimed (drop_failed), ${name}`, async () => {
    const { b3, d3 } = await batch("drop_failed", net);
    assert.equal(b3.pass, false, JSON.stringify(b3, null, 1));
    assert.match(d3.error, /as claimed, but its claim failed/);
  });
  test(`a route that offers neither upto nor batch-settlement is not graded by U1-U3 or B1-B3, ${name}`, async () => {
    const double = await startSchemeDouble(0);
    const s = await startBatchServer(double.url, "", net);
    const u = await startUptoServer(double.url, "", net);
    try {
      const rs = [...await probeUpto(`${s.base}/api`, double, { network: net }),
        ...await probeBatch(`${u.base}/metered`, double, { network: net, redeem: async () => [] })];
      assert.deepEqual(rs.map((r) => r.status), Array(6).fill("unsupported"));
      assert.ok(rs.every((r) => !r.pass));
    } finally { await s.close(); await u.close(); await double.close(); }
  });
}
