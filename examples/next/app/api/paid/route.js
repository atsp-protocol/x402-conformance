// The smallest paid route on Next: @x402/next's withX402 wrapper around an App Router API handler, one GET at $0.001.
// withX402 settles only after the handler answered below 400. X402_FACILITATOR_URL names the facilitator (the probe
// sets it), EXAMPLE_NETWORK the network (Solana devnet by default, or eip155:84532 for Base Sepolia).
import { NextResponse } from "next/server";
import { withX402, x402ResourceServer } from "@x402/next";
import { HTTPFacilitatorClient } from "@x402/core/server";
import { ExactSvmScheme } from "@x402/svm/exact/server";
import { ExactEvmScheme } from "@x402/evm/exact/server";

export const dynamic = "force-dynamic";

const network = process.env.EXAMPLE_NETWORK ?? "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1";
const evm = network.startsWith("eip155:");
const payTo = evm ? "0x209693Bc6afc0C5328bA36FaF03C514EF312287C" : "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin";

const server = new x402ResourceServer(new HTTPFacilitatorClient({ url: process.env.X402_FACILITATOR_URL }))
  .register(network, evm ? new ExactEvmScheme() : new ExactSvmScheme());

const handler = async () => NextResponse.json({ content: "paid content" });

export const GET = withX402(handler,
  { accepts: [{ scheme: "exact", price: "$0.001", network, payTo }], description: "quickstart", mimeType: "application/json" },
  server);
