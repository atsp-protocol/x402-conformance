// Resource servers for R12 (parallel requests) and R13 (two replicas). Each serves GET /report ($0.01), declares the
// payment-identifier extension, uses the facilitator named by the caller and keeps an idempotency record keyed by the
// request (route and payment-identifier id, bound to the payer where the payload names one).
//
//   ""              the control: a request reserves its key in the record before anything is awaited, so a parallel
//                   request with the same id waits for the first one and is served from its result, never settled
//   check_then_set  the record is read when a request arrives and written only after /settle returns: parallel
//                   requests with the same id all miss it, and each is settled
//
// R13 runs two of these as replicas of one service. Passing one store to both gives them a shared record (the
// control); a store each is a per-process in-memory cache, and a retry that reaches the other replica is settled again.
import type { AddressInfo } from "node:net";
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
export type ReplicaFault = "" | "check_then_set";

interface Entry { payer: string | null; settlement: unknown; body: unknown }
/** A key's slot: the settled result, or the reservation of the request that is paying for it. */
interface Slot { entry?: Entry; pending?: Promise<Entry | null>; release?: (e: Entry | null) => void }
/** The idempotency record. Pass one to several replicas to share it. */
export type ReplicaStore = Map<string, Slot>;
export const newReplicaStore = (): ReplicaStore => new Map();

export interface ReplicaServer { base: string; url: string; close(): Promise<void> }

const payerOf = (p: any): string | null => {
  const from = p?.payload?.authorization?.from;
  return typeof from === "string" ? from.toLowerCase() : null;
};

export async function startReplicaServer(facilitatorUrl: string,
    opts: { fault?: ReplicaFault; network?: string; store?: ReplicaStore; port?: number } = {}): Promise<ReplicaServer> {
  const fault = opts.fault ?? "";
  const store = opts.store ?? newReplicaStore();
  const net = (opts.network ?? DEVNET) as `${string}:${string}`;
  const evm = net === BASE_SEPOLIA;
  const payTo = evm ? "0x209693Bc6afc0C5328bA36FaF03C514EF312287C" : "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin";
  const keyOf = (path: string, p: any): string | null => {
    const id = extractPaymentIdentifier(p, false);
    return id ? `${path} ${id}` : null;
  };
  // The handler's body by key until its payment settles, so the record holds the result the paid request produced.
  const bodies = new Map<string, unknown>();
  let n = 0;
  const server = new x402ResourceServer(new HTTPFacilitatorClient({ url: facilitatorUrl }))
    .register(net, evm ? new ExactEvmScheme() : new ExactSvmScheme());
  server.onAfterSettle(async (ctx: any) => {
    const key = keyOf(ctx.transportContext?.request?.path ?? "/report", ctx.paymentPayload);
    if (!key || !ctx.result?.success) return;
    const entry = { payer: payerOf(ctx.paymentPayload), settlement: { ...ctx.result }, body: bodies.get(key) ?? null };
    bodies.delete(key);
    const slot = store.get(key);
    store.set(key, { entry });
    slot?.release?.(entry);
  });
  const routes = { "GET /report": { accepts: [{ scheme: "exact", price: "$0.01", network: net, payTo }],
    description: "replica example", mimeType: "application/json",
    extensions: { [PAYMENT_IDENTIFIER]: declarePaymentIdentifierExtension(false) } } } as any;
  const http402 = new x402HTTPResourceServer(server, routes);
  http402.onProtectedRequest(async (ctx: any) => {
    if (!ctx.paymentHeader) return;
    let p: any;
    try { p = decodePaymentSignatureHeader(ctx.paymentHeader); } catch { return; }
    const key = keyOf(ctx.path, p);
    if (!key) return;
    const req = (ctx.adapter as any).req;
    const slot = store.get(key);
    if (!slot) {
      if (fault === "check_then_set") return;   // the record is written only after /settle returns
      // Reserve the key before anything is awaited: the read and the write are one step.
      let release!: (e: Entry | null) => void;
      const pending = new Promise<Entry | null>((ok) => { release = ok; });
      store.set(key, { pending, release });
      req.replicaKey = key;
      return;
    }
    const hit = slot.entry ?? await slot.pending;
    if (!hit) return { abort: true, reason: "an earlier request with this payment identifier was not paid; retry" };
    if (hit.payer && payerOf(p) && hit.payer !== payerOf(p)) {
      return { abort: true, reason: "payment identifier already used by another payer" };
    }
    req.replicaHit = hit;
    return { grantAccess: true };
  });
  const app = express();
  app.use((req, res, next) => {
    const h = req.header("payment-signature");
    if (h) { try { (req as any).payment = decodePaymentSignatureHeader(h); } catch { /* the middleware answers */ } }
    // A reservation whose request ends without a settlement is dropped, so the next request with the id can pay.
    res.on("close", () => {
      const key = (req as any).replicaKey;
      const slot = key ? store.get(key) : undefined;
      if (slot && !slot.entry) { store.delete(key); slot.release?.(null); }
    });
    next();
  });
  app.use(paymentMiddlewareFromHTTPServer(http402));
  app.get("/report", (req, res) => {
    const hit: Entry | undefined = (req as any).replicaHit;
    if (hit) {
      res.setHeader("PAYMENT-RESPONSE", encodePaymentResponseHeader(hit.settlement as any));
      return void res.json({ ...(hit.body as object ?? {}), replayed: true });
    }
    const body = { content: "report", serial: ++n };
    const key = (req as any).payment ? keyOf(req.path, (req as any).payment) : null;
    if (key) bodies.set(key, body);
    res.json(body);
  });
  const http = await new Promise<import("node:http").Server>((ok) => {
    const s = app.listen(opts.port ?? 0, "127.0.0.1", () => ok(s));
  });
  const base = `http://127.0.0.1:${(http.address() as AddressInfo).port}`;
  return {
    base, url: `${base}/report`,
    close: () => new Promise((ok) => { http.closeAllConnections(); http.close(() => ok()); }),
  };
}
