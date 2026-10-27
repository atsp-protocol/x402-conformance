// R20, retry double-pay: the client times out before /settle answers and retries. Real @x402/express servers behind
// the facilitator double on loopback, on Solana devnet and Base Sepolia. The control passes; each faulty build is
// caught by the check it breaks.
import { test } from "node:test";
import assert from "node:assert/strict";
import type { AddressInfo } from "node:net";
import { createHash } from "node:crypto";
import express from "express";
import { paymentMiddlewareFromHTTPServer, x402HTTPResourceServer, x402ResourceServer } from "@x402/express";
import { HTTPFacilitatorClient } from "@x402/core/server";
import { decodePaymentSignatureHeader, encodePaymentResponseHeader } from "@x402/core/http";
import { ExactSvmScheme } from "@x402/svm/exact/server";
import { ExactEvmScheme } from "@x402/evm/exact/server";
import { declarePaymentIdentifierExtension, extractPaymentIdentifier, PAYMENT_IDENTIFIER }
  from "@x402/extensions/payment-identifier";
import { startDouble } from "../src/double.js";
import { checkClientRetry, probeRetry } from "../src/retry.js";
import { BASE_SEPOLIA, DEVNET, startRetryServer, type RetryFault } from "../example/retry-server.js";
import { retryingClient, type ClientFault } from "../example/retry-clients.js";
import type { Result } from "../src/probe.js";

const NETS = [["Solana devnet", DEVNET], ["Base Sepolia", BASE_SEPOLIA]] as const;
const find = (rs: Result[], id: string) => {
  const r = rs.find((x) => x.check.split(" ")[0] === id);
  assert.ok(r, `${id} missing from ${JSON.stringify(rs.map((x) => x.check))}`);
  return r;
};

async function server(fault: RetryFault, network: string) {
  const double = await startDouble(0);
  const s = await startRetryServer(double.url, fault, network);
  return { double, s, close: async () => { await s.close(); await double.close(); } };
}

async function run(fault: RetryFault, network: string) {
  const h = await server(fault, network);
  try { return { results: await probeRetry(h.s.url, h.double, { network }), double: h.double }; } finally { await h.close(); }
}

interface Refusal { status: number; namesId: boolean }

// R20c's refusing server, on the pattern of the payment-identifier extension's example: the stock middleware with a
// record keyed by the payment-identifier id that holds a hash of the payment it settled. A request whose id is in the
// record with a different payment is refused before the middleware runs, so it never reaches /settle; the same payment
// again is served from the record with its original PAYMENT-RESPONSE. `refusal` sets the status and whether the error
// names the id.
async function conflictServer(network: string, refusal: Refusal = { status: 409, namesId: true }) {
  const double = await startDouble(0);
  const net = network as `${string}:${string}`;
  const evm = network === BASE_SEPOLIA;
  const payTo = evm ? "0x209693Bc6afc0C5328bA36FaF03C514EF312287C" : "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin";
  const hash = (p: any) => createHash("sha256").update(JSON.stringify(p?.payload ?? null)).digest("hex");
  const record = new Map<string, { hash: string; settlement: unknown }>();
  const server = new x402ResourceServer(new HTTPFacilitatorClient({ url: double.url }))
    .register(net, evm ? new ExactEvmScheme() : new ExactSvmScheme());
  server.onAfterSettle(async (ctx: any) => {
    const id = extractPaymentIdentifier(ctx.paymentPayload, false);
    if (id && ctx.result?.success) record.set(id, { hash: hash(ctx.paymentPayload), settlement: { ...ctx.result } });
  });
  const routes = { "GET /report": { accepts: [{ scheme: "exact", price: "$0.01", network: net, payTo }],
    description: "conflict example", mimeType: "application/json",
    extensions: { [PAYMENT_IDENTIFIER]: declarePaymentIdentifierExtension(false) } } } as any;
  const app = express();
  app.use((req, res, next) => {
    const h = req.header("payment-signature");
    let p: any = null;
    if (h) { try { p = decodePaymentSignatureHeader(h); } catch { p = null; } }
    const id = p ? extractPaymentIdentifier(p, false) : null;
    const hit = id ? record.get(id) : undefined;
    if (!hit) return next();
    if (hit.hash !== hash(p)) {
      return void res.status(refusal.status).json({ error: refusal.namesId
        ? `payment identifier ${id} was already used with a different payment` : "conflict" });
    }
    res.setHeader("PAYMENT-RESPONSE", encodePaymentResponseHeader(hit.settlement as any));
    res.json({ content: "report", replayed: true });
  });
  app.use(paymentMiddlewareFromHTTPServer(new x402HTTPResourceServer(server, routes)));
  app.get("/report", (_req, res) => { res.json({ content: "report" }); });
  const http = await new Promise<import("node:http").Server>((ok) => { const h = app.listen(0, "127.0.0.1", () => ok(h)); });
  const url = `http://127.0.0.1:${(http.address() as AddressInfo).port}/report`;
  try { return { results: await probeRetry(url, double, { network }), double }; } finally {
    await new Promise<void>((ok) => { http.closeAllConnections(); http.close(() => ok()); });
    await double.close();
  }
}

async function client(fault: ClientFault, network: string) {
  const h = await server("", network);
  try { return await checkClientRetry(retryingClient(network, fault), h.s.url, h.double); } finally { await h.close(); }
}

for (const [name, net] of NETS) {
  test(`R20 control: a URL that is not a paid route fails the control and grades nothing, ${name}`, async () => {
    const h = await server("", net);
    try {
      const rs = await probeRetry(`${h.s.base}/free`, h.double, { network: net });
      assert.equal(rs.length, 1, JSON.stringify(rs));
      assert.equal(find(rs, "R20").pass, false);
      assert.equal(h.double.calls.filter((c) => c.path === "/settle").length, 0);
    } finally { await h.close(); }
  });
  test(`R20a control: the stock @x402/express server with an idempotency record charges a fresh-payment retry once, ${name}`,
    async () => {
      const { results } = await run("", net);
      assert.equal(find(results, "R20").pass, true, JSON.stringify(results));
      const a = find(results, "R20a");
      assert.equal(a.pass, true, JSON.stringify(a));
      assert.equal((a.detail as any).successful_settles, 1, JSON.stringify(a.detail));
      assert.equal((a.detail as any).first.timed_out, true, JSON.stringify(a.detail));
      assert.ok((a.detail as any).retry.settlement_ref, "the retry carries the original settlement");
    });
  test(`R20a settle_both: a server with no idempotency record settles the fresh-payment retry and is caught, ${name}`,
    async () => {
      const { results } = await run("settle_both", net);
      const a = find(results, "R20a");
      assert.equal(a.pass, false, JSON.stringify(a));
      assert.equal((a.detail as any).successful_settles, 2, JSON.stringify(a.detail));
    });
  test(`R20a key_by_payment: a record keyed by the payment instead of the request is caught, ${name}`, async () => {
    const { results } = await run("key_by_payment", net);
    const a = find(results, "R20a");
    assert.equal(a.pass, false, JSON.stringify(a));
    assert.equal((a.detail as any).successful_settles, 2, JSON.stringify(a.detail));
    // keyed by payment it does replay the identical payment, so only R20a catches it
    assert.equal(find(results, "R20b").pass, true, JSON.stringify(results));
  });
  test(`R20b control: the same signed payment resent after a timeout is not settled twice and gets the original result, ${name}`,
    async () => {
      const { results } = await run("", net);
      const b = find(results, "R20b");
      assert.equal(b.pass, true, JSON.stringify(b));
      assert.equal((b.detail as any).successful_settles, 1, JSON.stringify(b.detail));
    });
  test(`R20b settle_both: with no record the resent payment is refused as a duplicate and the result is lost, ${name}`,
    async () => {
      const { results, double } = await run("settle_both", net);
      const b = find(results, "R20b");
      assert.equal(b.pass, false, JSON.stringify(b));
      assert.equal((b.detail as any).successful_settles, 1, JSON.stringify(b.detail));
      assert.ok(double.calls.filter((c) => c.path === "/settle").length >= 4);
    });
  test(`R20b client control: the stock @x402/fetch client with a payment id retries under the same key, ${name}`,
    async () => {
      const r = await client("", net);
      assert.equal(r.pass, true, JSON.stringify(r));
      assert.equal((r.detail as any).same_payment_identifier, true, JSON.stringify(r.detail));
      assert.equal((r.detail as any).successful_settles, 1, JSON.stringify(r.detail));
    });
  test(`R20b client resign_on_timeout: a client that re-signs a fresh payment with no key is flagged, ${name}`,
    async () => {
      const r = await client("resign_on_timeout", net);
      assert.equal(r.pass, false, JSON.stringify(r));
      assert.equal((r.detail as any).fresh_nonce, true, JSON.stringify(r.detail));
      assert.equal((r.detail as any).same_payment_identifier, false, JSON.stringify(r.detail));
      assert.equal((r.detail as any).successful_settles, 2, JSON.stringify(r.detail));
    });
}

for (const [name, net] of NETS) {
  test(`R20c control: a server that refuses a same-id re-signed retry with 409 and settles it once passes; R20a stays `
    + `strict and fails it, ${name}`, async () => {
    const { results } = await conflictServer(net);
    const c = find(results, "R20c");
    assert.equal(c.pass, true, JSON.stringify(c));
    assert.equal((c.detail as any).retry.status, 409, JSON.stringify(c.detail));
    assert.equal((c.detail as any).outcome, "refused");
    assert.equal((c.detail as any).successful_settles, 1, JSON.stringify(c.detail));
    // the refusal loses the result the client paid for, which R20a still requires
    assert.equal(find(results, "R20a").pass, false, JSON.stringify(results));
    assert.equal(find(results, "R20b").pass, true, JSON.stringify(results));
  });
  test(`R20c control: the stock @x402/express server with an idempotency record returns the original result and passes, ${name}`,
    async () => {
      const { results } = await run("", net);
      const c = find(results, "R20c");
      assert.equal(c.pass, true, JSON.stringify(c));
      assert.equal((c.detail as any).outcome, "original result");
      assert.equal((c.detail as any).successful_settles, 1, JSON.stringify(c.detail));
    });
  test(`R20c settle_both: a server that settles the re-signed retry is caught, ${name}`, async () => {
    const { results } = await run("settle_both", net);
    const c = find(results, "R20c");
    assert.equal(c.pass, false, JSON.stringify(c));
    assert.equal((c.detail as any).successful_settles, 2, JSON.stringify(c.detail));
    assert.match(String((c.detail as any).error), /paid twice/);
  });
  test(`R20c key_by_payment: a record keyed by the payment settles the re-signed retry and is caught, ${name}`, async () => {
    const { results } = await run("key_by_payment", net);
    const c = find(results, "R20c");
    assert.equal(c.pass, false, JSON.stringify(c));
    assert.equal((c.detail as any).successful_settles, 2, JSON.stringify(c.detail));
  });
  test(`R20c refusal: a 403 that names the id passes, and a 400 that does not name it is caught, ${name}`, async () => {
    const named = find((await conflictServer(net, { status: 403, namesId: true })).results, "R20c");
    assert.equal(named.pass, true, JSON.stringify(named));
    assert.equal((named.detail as any).retry.names_id, true);
    const bare = find((await conflictServer(net, { status: 400, namesId: false })).results, "R20c");
    assert.equal(bare.pass, false, JSON.stringify(bare));
    assert.equal((bare.detail as any).successful_settles, 1, "not paid twice, but the refusal is not clear");
    assert.match(String((bare.detail as any).error), /neither the original result nor a 409/);
  });
}
