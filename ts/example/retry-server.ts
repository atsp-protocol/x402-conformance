// Resource servers for R20, retry double-pay. Each serves GET /report ($0.01), declares the payment-identifier
// extension, and uses the facilitator named by X402_FACILITATOR_URL.
//
//   ""              the control: the stock @x402/express middleware (x402HTTPResourceServer and
//                   paymentMiddlewareFromHTTPServer, 2.28.0) with a durable idempotency record, on the pattern of the
//                   upstream payment-identifier example. The record is written in onAfterSettle, keyed by the request
//                   (route and payment-identifier id, bound to the payer where the payload names one) and holds the
//                   result and its settlement. onProtectedRequest serves a retry with a known key from the record,
//                   with the original PAYMENT-RESPONSE, and never settles again
//   settle_both     the same route with no idempotency record: a retry with a fresh payment is settled again
//   key_by_payment  a record keyed by the payment (a hash of the whole payload) instead of the request: a retry that
//                   resends the same payment is served from it, a retry with a fresh payment is settled again
//   record_on_delivery  the control's record, but committed only once the response has been delivered: when the
//                   client disconnects while /settle is in flight the settlement happens and the record is lost (R23)
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

export const DEVNET = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1";
export const BASE_SEPOLIA = "eip155:84532";
export type RetryFault = "" | "settle_both" | "key_by_payment" | "record_on_delivery";
export const RETRY_FAULTS: RetryFault[] = ["settle_both", "key_by_payment", "record_on_delivery"];

export interface RetryServer { base: string; url: string; close(): Promise<void> }

interface Entry { payer: string | null; settlement: unknown; body: unknown }

const payerOf = (p: any): string | null => {
  const from = p?.payload?.authorization?.from;
  return typeof from === "string" ? from.toLowerCase() : null;
};
// The payment itself: the signed authorization or transaction, which a fresh payment always changes.
const fingerprint = (p: any) => createHash("sha256").update(JSON.stringify(p?.payload ?? null)).digest("hex");

export async function startRetryServer(facilitatorUrl: string, fault: RetryFault = "", network = DEVNET,
    port = 0): Promise<RetryServer> {
  const net = network as `${string}:${string}`;
  const evm = network === BASE_SEPOLIA;
  const payTo = evm ? "0x209693Bc6afc0C5328bA36FaF03C514EF312287C" : "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin";
  const facilitator = new HTTPFacilitatorClient({ url: facilitatorUrl });
  const record = new Map<string, Entry>();
  // record_on_delivery: entries wait here until their response has been written out to the client.
  const undelivered = new Map<string, Entry>();
  // The handler's body by key until its payment settles, so the record returns the result the first attempt produced.
  const bodies = new Map<string, unknown>();
  const keyOf = (path: string, p: any): string | null => {
    if (fault === "key_by_payment") return `${path} ${fingerprint(p)}`;
    const id = extractPaymentIdentifier(p, false);
    return id ? `${path} ${id}` : null;
  };
  let n = 0;
  const content = () => ({ content: "report", serial: ++n });
  const server = new x402ResourceServer(facilitator).register(net, evm ? new ExactEvmScheme() : new ExactSvmScheme());
  if (fault !== "settle_both") {
    server.onAfterSettle(async (ctx: any) => {
      const key = keyOf(ctx.transportContext?.request?.path ?? "/report", ctx.paymentPayload);
      if (!key || !ctx.result?.success) return;
      const entry = { payer: payerOf(ctx.paymentPayload), settlement: { ...ctx.result }, body: bodies.get(key) ?? null };
      if (fault === "record_on_delivery") undelivered.set(key, entry); else record.set(key, entry);
      bodies.delete(key);
    });
  }
  const routes = { "GET /report": { accepts: [{ scheme: "exact", price: "$0.01", network: net, payTo }],
    description: "retry example", mimeType: "application/json",
    extensions: { [PAYMENT_IDENTIFIER]: declarePaymentIdentifierExtension(false) } } } as any;
  const http402 = new x402HTTPResourceServer(server, routes);
  if (fault !== "settle_both") {
    http402.onProtectedRequest(async (ctx: any) => {
      if (!ctx.paymentHeader) return;
      let p: any;
      try { p = decodePaymentSignatureHeader(ctx.paymentHeader); } catch { return; }
      const key = keyOf(ctx.path, p);
      const hit = key ? record.get(key) : undefined;
      if (!hit) return;
      const req = (ctx.adapter as any).req;
      if (hit.payer && payerOf(p) && hit.payer !== payerOf(p)) {
        return { abort: true, reason: "payment identifier already used by another payer" };
      }
      req.retryHit = hit;
      return { grantAccess: true };
    });
  }
  const app = express();
  app.use((req, res, next) => {
    const h = req.header("payment-signature");
    if (h) { try { (req as any).payment = decodePaymentSignatureHeader(h); } catch { /* the middleware answers */ } }
    if (fault === "record_on_delivery") {
      res.on("finish", () => {
        const key = (req as any).payment ? keyOf(req.path, (req as any).payment) : null;
        const entry = key ? undelivered.get(key) : undefined;
        if (key && entry) { record.set(key, entry); undelivered.delete(key); }
      });
    }
    next();
  });
  app.use(paymentMiddlewareFromHTTPServer(http402));
  app.get("/report", (req, res) => {
    const hit: Entry | undefined = (req as any).retryHit;
    if (hit) {
      res.setHeader("PAYMENT-RESPONSE", encodePaymentResponseHeader(hit.settlement as any));
      return void res.json({ ...(hit.body as object ?? {}), replayed: true });
    }
    const body = content();
    const key = (req as any).payment ? keyOf(req.path, (req as any).payment) : null;
    if (key && fault !== "settle_both") bodies.set(key, body);
    res.json(body);
  });
  const http = await new Promise<import("node:http").Server>((ok) => { const s = app.listen(port, "127.0.0.1", () => ok(s)); });
  const base = `http://127.0.0.1:${(http.address() as AddressInfo).port}`;
  return {
    base, url: `${base}/report`,
    close: () => new Promise((ok) => { http.closeAllConnections(); http.close(() => ok()); }),
  };
}
