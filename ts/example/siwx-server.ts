// A resource server for W1 to W3, the sign-in-with-x server rules, on @x402/express with the exact scheme on Base
// Sepolia. One paid GET route, /report ($0.01), declaring sign-in-with-x, so a wallet that has paid can come back with
// only a SIGN-IN-WITH-X header.
//   control           createSIWxResourceServerExtension as shipped, with the configured public origin and a storage
//                     that tracks used nonces (InMemorySIWxStorage alone does not)
// SIWX_FAULT values, each a faulty build a check must catch:
//   origin_from_host  W1: validates domain and uri against an origin built from X-Forwarded-Host or Host
//   no_nonce_store    W2: the shipped InMemorySIWxStorage, which records payments but not nonces
//   no_time_window    W3: checks domain, uri, signature and payment, but not issuedAt or expirationTime
import type { AddressInfo } from "node:net";
import express from "express";
import { paymentMiddleware, x402ResourceServer } from "@x402/express";
import { HTTPFacilitatorClient } from "@x402/core/server";
import { ExactEvmScheme } from "@x402/evm/exact/server";
import { createSIWxRequestHook, createSIWxResourceServerExtension, declareSIWxExtension, InMemorySIWxStorage,
  parseSIWxHeader, validateSIWxMessage, verifySIWxSignature } from "@x402/extensions/sign-in-with-x";

export const BASE_SEPOLIA = "eip155:84532";
export const SIWX_FAULTS = ["origin_from_host", "no_nonce_store", "no_time_window"] as const;
export type SiwxFault = "" | (typeof SIWX_FAULTS)[number];

/** InMemorySIWxStorage plus the optional nonce tracking the extension uses when a storage has it. */
export class NonceTrackingStorage extends InMemorySIWxStorage {
  private used = new Set<string>();
  hasUsedNonce(nonce: string) { return this.used.has(nonce); }
  recordNonce(nonce: string) { this.used.add(nonce); }
}

export interface SiwxServer { base: string; close(): Promise<void>; served: number }

export async function startSiwxRulesServer(facilitatorUrl: string, fault: SiwxFault = "", port = 0): Promise<SiwxServer> {
  const net = BASE_SEPOLIA as `${string}:${string}`;
  const storage = fault === "no_nonce_store" ? new InMemorySIWxStorage() : new NonceTrackingStorage();
  const app = express();
  const server = await new Promise<import("node:http").Server>((ok) => { const s = app.listen(port, "127.0.0.1", () => ok(s)); });
  const origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  const ext: any = createSIWxResourceServerExtension({ storage, origin });
  if (fault === "origin_from_host") {
    ext.transportHooks.http.onProtectedRequest = (_declared: unknown, context: any, routeConfig: any) => {
      const host = context.adapter.getHeader("x-forwarded-host") ?? context.adapter.getHeader("host");
      const proto = context.adapter.getHeader("x-forwarded-proto") ?? "http";
      return createSIWxRequestHook({ storage, origin: `${proto}://${host}` })(context, routeConfig);
    };
  }
  if (fault === "no_time_window") {
    ext.transportHooks.http.onProtectedRequest = async (_declared: unknown, context: any) => {
      const header = context.adapter.getHeader("sign-in-with-x");
      if (!header) return;
      try {
        const payload = parseSIWxHeader(header);
        const timeless = { ...payload, issuedAt: new Date().toISOString(), expirationTime: undefined, notBefore: undefined };
        if (!(await validateSIWxMessage(timeless, new URL(origin))).isValid) return;
        const v = await verifySIWxSignature(payload);
        if (!v.isValid || !v.payer) return;
        if (await (storage as NonceTrackingStorage).hasUsedNonce(payload.nonce)) return;
        if (!(await storage.hasPaid(context.path, v.payer))) return;
        (storage as NonceTrackingStorage).recordNonce(payload.nonce);
        return { grantAccess: true };
      } catch { return; }
    };
  }
  const rs = new x402ResourceServer(new HTTPFacilitatorClient({ url: facilitatorUrl, timeoutMs: 3000 }))
    .register(net, new ExactEvmScheme()).registerExtension(ext);
  const routes = { "GET /report": { accepts: [{ scheme: "exact", price: "$0.01", network: net,
    payTo: "0x209693Bc6afc0C5328bA36FaF03C514EF312287C" }], description: "SIWX rules example",
  mimeType: "application/json", extensions: declareSIWxExtension({ statement: "Sign in to read the report you bought" }) } };
  const state: SiwxServer = { base: origin, served: 0, close: async () => {} };
  app.use(paymentMiddleware(routes as any, rs));
  app.get("/report", (_req, res) => { state.served++; res.json({ content: "the report" }); });
  state.close = () => new Promise((ok) => { server.closeAllConnections(); server.close(() => ok()); });
  return state;
}
