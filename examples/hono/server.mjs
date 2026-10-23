// The smallest paid route on @x402/hono: the stock paymentMiddleware with its defaults, one GET /paid at $0.001,
// served with @hono/node-server. X402_FACILITATOR_URL names the facilitator (the probe sets it), PORT the port,
// EXAMPLE_NETWORK the network (Solana devnet by default, or eip155:84532 for Base Sepolia).
import { Hono } from "hono";
import { serve } from "@hono/node-server";
import { paymentMiddleware, x402ResourceServer } from "@x402/hono";
import { HTTPFacilitatorClient } from "@x402/core/server";
import { ExactSvmScheme } from "@x402/svm/exact/server";
import { ExactEvmScheme } from "@x402/evm/exact/server";

const network = process.env.EXAMPLE_NETWORK ?? "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1";
const evm = network.startsWith("eip155:");
const payTo = evm ? "0x209693Bc6afc0C5328bA36FaF03C514EF312287C" : "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin";
const port = Number(process.env.PORT ?? 4020);

const server = new x402ResourceServer(new HTTPFacilitatorClient({ url: process.env.X402_FACILITATOR_URL }))
  .register(network, evm ? new ExactEvmScheme() : new ExactSvmScheme());
const app = new Hono();
app.use(paymentMiddleware({
  "GET /paid": { accepts: [{ scheme: "exact", price: "$0.001", network, payTo }],
    description: "quickstart", mimeType: "application/json" },
}, server));
app.get("/paid", (c) => c.json({ content: "paid content" }));
serve({ fetch: app.fetch, port, hostname: "127.0.0.1" }, () => {
  console.log(JSON.stringify({ listening: `http://127.0.0.1:${port}/paid` }));
});
