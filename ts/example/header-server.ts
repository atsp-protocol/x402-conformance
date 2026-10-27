// Resource servers for R24, a malformed payment header. Each serves GET /paid behind the facilitator named by the
// caller, and records every request's payment headers in `seen`, with the value as it reached the server.
//
// The route advertises x402 V2, V1 or both:
//   "v2"    the stock @x402/express paymentMiddleware (2.28.0), which reads only PAYMENT-SIGNATURE
//   "v1"    a V1 route built here, because the stock middleware serves V2 only: the unpaid 402 is a V1 JSON body
//           (x402Version 1, error, accepts), and X-PAYMENT is decoded with a shape check. Anything malformed gets the
//           same 402 body. PAYMENT-SIGNATURE is ignored, as a V1 server does.
//   "both"  the stock middleware for V2, with the V1 body on its 402 and the same X-PAYMENT shape check in front
//
// By fault, on the "v2" route (each fault is a step in front of the middleware):
//   ""                  the control: the stock middleware, which answers a header it cannot decode with 402 and a
//                       PAYMENT-REQUIRED that names the error
//   decode_unchecked    the step decodes the header itself and reads a field of the result without checking it: a
//                       malformed header throws and Express answers 500
//   drop_on_bad_header  the same step, but a header it cannot decode closes the connection without an answer
//   null_member_deref   the step skips a header that does not parse, or parses to an array or a non-object, then reads
//                       `.accepted.network`. `typeof null` is "object", so null, {} and an object whose members are null
//                       throw, and Express answers 500. The original five values all reach the middleware.
//   parse_error_is_500  the step parses any header that is present, even an empty one, and hands the middleware only
//                       the parse errors it expects (an unexpected token). An empty or blank header gives a different
//                       one (unexpected end of input), which becomes a 500. The original five all reach the middleware.
// and on the "v1" route:
//   v1_header_unchecked decodes X-PAYMENT and reads `.payload.signature` without the shape check: a malformed X-PAYMENT
//                       throws and Express answers 500
import type { AddressInfo, Socket } from "node:net";
import express from "express";
import { paymentMiddleware, x402ResourceServer } from "@x402/express";
import { HTTPFacilitatorClient } from "@x402/core/server";
import { ExactSvmScheme } from "@x402/svm/exact/server";
import { ExactEvmScheme } from "@x402/evm/exact/server";

export const DEVNET = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1";
export const BASE_SEPOLIA = "eip155:84532";
export type HeaderFault = "" | "decode_unchecked" | "drop_on_bad_header" | "null_member_deref" | "parse_error_is_500"
  | "v1_header_unchecked";
export const HEADER_FAULTS: HeaderFault[] = ["decode_unchecked", "drop_on_bad_header", "null_member_deref", "parse_error_is_500",
  "v1_header_unchecked"];
export type HeaderRoute = "v2" | "v1" | "both";
export interface SeenHeader { header: "PAYMENT-SIGNATURE" | "X-PAYMENT"; value: string }

const decode = (h: string) => JSON.parse(Buffer.from(h, "base64").toString("utf8"));

/** A well-formed V1 payment payload: an object with x402Version 1, a scheme, a network and a payload object. */
function v1Shape(h: string): boolean {
  try {
    const v = decode(h);
    return !!v && typeof v === "object" && !Array.isArray(v) && v.x402Version === 1 && typeof v.scheme === "string"
      && typeof v.network === "string" && !!v.payload && typeof v.payload === "object";
  } catch { return false; }
}

export async function startHeaderServer(facilitatorUrl: string, fault: HeaderFault = "", network = DEVNET, port = 0,
    route: HeaderRoute = fault === "v1_header_unchecked" ? "v1" : "v2"):
    Promise<{ base: string; url: string; seen: SeenHeader[]; close(): Promise<void> }> {
  const evm = network === BASE_SEPOLIA;
  const payTo = evm ? "0x209693Bc6afc0C5328bA36FaF03C514EF312287C" : "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin";
  // V1 names the network and the USDC asset its own way
  const v1 = evm ? { network: "base-sepolia", asset: "0x036CbD53842c5426634e7929541eC2318f3dCF7e" }
    : { network: "solana-devnet", asset: "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU" };
  const v1Body = (req: express.Request, error: string) => ({ x402Version: 1, error, accepts: [{ scheme: "exact", network: v1.network,
    maxAmountRequired: "1000", resource: `http://${req.get("host")}${req.path}`, description: "header example",
    mimeType: "application/json", payTo, maxTimeoutSeconds: 300, asset: v1.asset }] });
  const seen: SeenHeader[] = [];
  const app = express();
  app.use((req, _res, next) => {
    for (const header of ["PAYMENT-SIGNATURE", "X-PAYMENT"] as const) {
      const value = req.headers[header.toLowerCase()];
      if (typeof value === "string") seen.push({ header, value });
    }
    next();
  });

  if (route === "v1") {
    app.get("/paid", (req, res) => {
      const h = req.header("x-payment");
      if (!h) return void res.status(402).json(v1Body(req, "X-PAYMENT header is required"));
      if (fault === "v1_header_unchecked") res.locals.signature = decode(h).payload.signature;
      else if (!v1Shape(h)) return void res.status(402).json(v1Body(req, "invalid X-PAYMENT header"));
      // a well-formed V1 payment is outside R24: this example never settles one
      res.status(402).json(v1Body(req, "this example does not settle V1 payments"));
    });
  } else {
    const server = new x402ResourceServer(new HTTPFacilitatorClient({ url: facilitatorUrl }))
      .register(network as `${string}:${string}`, evm ? new ExactEvmScheme() : new ExactSvmScheme());
    if (route === "both") {
      app.use("/paid", (req, res, next) => {
        const json = res.json.bind(res);
        // the stock middleware's 402 body is {}; this route also advertises V1 in it
        res.json = ((b: unknown) => json(res.statusCode === 402 && !!b && typeof b === "object" && !Object.keys(b).length
          ? v1Body(req, "payment required") : b)) as typeof res.json;
        const h = req.header("x-payment");
        if (h !== undefined && !v1Shape(h)) return void res.status(402).json(v1Body(req, "invalid X-PAYMENT header"));
        next();
      });
    }
    if (fault && fault !== "v1_header_unchecked") {
      app.use((req, res, next) => {
        const h = req.header("payment-signature");
        if (fault === "parse_error_is_500") {
          if (h === undefined) return next();
          try { decode(h); } catch (e) {
            if (e instanceof SyntaxError && /Unexpected token/.test(e.message)) return next();
            return void res.status(500).type("text/plain").send("Internal Server Error");
          }
          return next();
        }
        if (!h) return next();
        if (fault === "null_member_deref") {
          let v: any;
          try { v = decode(h); } catch { return next(); }
          if (typeof v !== "object" || Array.isArray(v)) return next();
          res.locals.network = v.accepted.network;
          return next();
        }
        if (fault === "drop_on_bad_header") {
          try { decode(h).accepted.network; } catch {
            return void (req.socket as Socket).destroy();
          }
          return next();
        }
        // decode_unchecked: any malformed header throws here, and Express's default handler answers 500.
        res.locals.network = decode(h).accepted.network;
        next();
      });
    }
    app.use(paymentMiddleware({
      "GET /paid": { accepts: [{ scheme: "exact", price: "$0.001", network: network as `${string}:${string}`, payTo }],
        description: "header example", mimeType: "application/json" },
    }, server));
    app.get("/paid", (_req, res) => { res.json({ content: "paid content" }); });
  }
  app.get("/free", (_req, res) => { res.json({ content: "free" }); });
  // An exception from an unchecked decode ends here: a plain 500, as Express's default handler answers, without its log.
  app.use((_err: unknown, _req: express.Request, res: express.Response, _next: express.NextFunction) => {
    res.status(500).type("text/plain").send("Internal Server Error");
  });
  const http = await new Promise<import("node:http").Server>((ok) => { const s = app.listen(port, "127.0.0.1", () => ok(s)); });
  const base = `http://127.0.0.1:${(http.address() as AddressInfo).port}`;
  return { base, url: `${base}/paid`, seen, close: () => new Promise((ok) => { http.closeAllConnections(); http.close(() => ok()); }) };
}
