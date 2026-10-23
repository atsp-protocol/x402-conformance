// Resource servers for R24, a malformed payment header. Each serves GET /paid behind the stock @x402/express
// paymentMiddleware (2.28.0) and the facilitator named by the caller.
//
//   ""                  the control: the stock middleware, which answers a header it cannot decode with 402 and a
//                       PAYMENT-REQUIRED that names the error
//   decode_unchecked    a logging step in front of the middleware decodes the header itself and reads a field of
//                       the result without checking it: a malformed header throws and Express answers 500
//   drop_on_bad_header  the same step, but a header it cannot decode closes the connection without an answer
import type { AddressInfo, Socket } from "node:net";
import express from "express";
import { paymentMiddleware, x402ResourceServer } from "@x402/express";
import { HTTPFacilitatorClient } from "@x402/core/server";
import { ExactSvmScheme } from "@x402/svm/exact/server";
import { ExactEvmScheme } from "@x402/evm/exact/server";

export const DEVNET = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1";
export const BASE_SEPOLIA = "eip155:84532";
export type HeaderFault = "" | "decode_unchecked" | "drop_on_bad_header";
export const HEADER_FAULTS: HeaderFault[] = ["decode_unchecked", "drop_on_bad_header"];

export async function startHeaderServer(facilitatorUrl: string, fault: HeaderFault = "", network = DEVNET, port = 0):
    Promise<{ base: string; url: string; close(): Promise<void> }> {
  const evm = network === BASE_SEPOLIA;
  const payTo = evm ? "0x209693Bc6afc0C5328bA36FaF03C514EF312287C" : "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin";
  const server = new x402ResourceServer(new HTTPFacilitatorClient({ url: facilitatorUrl }))
    .register(network as `${string}:${string}`, evm ? new ExactEvmScheme() : new ExactSvmScheme());
  const app = express();
  if (fault) {
    app.use((req, res, next) => {
      const h = req.header("payment-signature");
      if (!h) return next();
      if (fault === "drop_on_bad_header") {
        try { JSON.parse(Buffer.from(h, "base64").toString("utf8")).accepted.network; } catch {
          return void (req.socket as Socket).destroy();
        }
        return next();
      }
      // decode_unchecked: any malformed header throws here, and Express's default handler answers 500.
      const network = JSON.parse(Buffer.from(h, "base64").toString("utf8")).accepted.network;
      res.locals.network = network;
      next();
    });
  }
  app.use(paymentMiddleware({
    "GET /paid": { accepts: [{ scheme: "exact", price: "$0.001", network: network as `${string}:${string}`, payTo }],
      description: "header example", mimeType: "application/json" },
  }, server));
  app.get("/paid", (_req, res) => { res.json({ content: "paid content" }); });
  app.get("/free", (_req, res) => { res.json({ content: "free" }); });
  // An exception from the unchecked decode ends here: a plain 500, as Express's default handler answers, without its log.
  app.use((_err: unknown, _req: express.Request, res: express.Response, _next: express.NextFunction) => {
    res.status(500).type("text/plain").send("Internal Server Error");
  });
  const http = await new Promise<import("node:http").Server>((ok) => { const s = app.listen(port, "127.0.0.1", () => ok(s)); });
  const base = `http://127.0.0.1:${(http.address() as AddressInfo).port}`;
  return { base, url: `${base}/paid`, close: () => new Promise((ok) => { http.closeAllConnections(); http.close(() => ok()); }) };
}
