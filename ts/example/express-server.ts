// A stock resource server: the upstream @x402/express paymentMiddleware with its defaults (no timeout tuning), exactly
// as the x402 examples set it up. The probe must pass it on every check, R3 included. EXAMPLE_NETWORK picks Solana
// devnet (default) or Base Sepolia (eip155:84532). X402_FACILITATOR_URL names its facilitator.
import type { AddressInfo } from "node:net";
import express from "express";
import { paymentMiddleware, x402ResourceServer } from "@x402/express";
import { HTTPFacilitatorClient } from "@x402/core/server";
import { ExactSvmScheme } from "@x402/svm/exact/server";
import { ExactEvmScheme } from "@x402/evm/exact/server";

export const DEVNET = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1";
export const BASE_SEPOLIA = "eip155:84532";

export async function startStockExpress(facilitatorUrl: string, network = DEVNET, port = 0):
    Promise<{ url: string; close(): Promise<void> }> {
  const evm = network === BASE_SEPOLIA;
  const payTo = evm ? "0x209693Bc6afc0C5328bA36FaF03C514EF312287C" : "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin";
  const server = new x402ResourceServer(new HTTPFacilitatorClient({ url: facilitatorUrl }))
    .register(network as `${string}:${string}`, evm ? new ExactEvmScheme() : new ExactSvmScheme());
  const app = express();
  app.use(paymentMiddleware({
    "GET /paid": { accepts: [{ scheme: "exact", price: "$0.001", network: network as `${string}:${string}`, payTo }],
      description: "stock example", mimeType: "application/json" },
  }, server));
  app.get("/paid", (_req, res) => { res.json({ content: "paid content" }); });
  const http = await new Promise<import("node:http").Server>((ok) => { const s = app.listen(port, "127.0.0.1", () => ok(s)); });
  return {
    url: `http://127.0.0.1:${(http.address() as AddressInfo).port}/paid`,
    close: () => new Promise((ok) => { http.closeAllConnections(); http.close(() => ok()); }),
  };
}

const isMain = process.argv[1] && import.meta.url.endsWith(process.argv[1].replace(/\\/g, "/").split("/").pop() ?? "");
if (isMain && process.env.X402_FACILITATOR_URL) {
  startStockExpress(process.env.X402_FACILITATOR_URL, process.env.EXAMPLE_NETWORK ?? DEVNET, Number(process.env.PORT ?? 4020))
    .then((s) => console.log(JSON.stringify({ listening: s.url })));
}
