// XC-56 parity harness for the official TypeScript libraries (@x402/core, @x402/evm, @x402/express at the pin).
// Reads JSON lines on stdin: one {config}, then one {vector} per line. Writes one outcome line per vector and a last
// {done} line. Run with node --import dist/src/guard.js so that any connection off loopback is refused and counted.
//
//   verify      x402Facilitator.verify(payload, requirements), the exact EVM scheme registered for the config's network
//               with a stub signer: getCode answers "0x" (an account with no code, so signatures are recovered
//               locally), every other read rejects, and every write is refused and counted.
//   paid-route  GET /paid on an express app behind the stock paymentMiddleware, whose facilitator is the runner's
//               recording double on loopback, with the vector's PAYMENT-SIGNATURE header.
//
// Faults (self-test only) substitute the library's decision at this boundary, except wildcard-network, which
// registers two networks of the family so that the library itself derives the eip155:* pattern.
import { readFileSync } from "node:fs";
import type { Server } from "node:http";
import type { AddressInfo } from "node:net";
import { dirname, join } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import express from "express";
import { x402Facilitator } from "@x402/core/facilitator";
import { HTTPFacilitatorClient } from "@x402/core/server";
import { ExactEvmScheme as ExactEvmFacilitatorScheme } from "@x402/evm/exact/facilitator";
import { ExactEvmScheme as ExactEvmServerScheme } from "@x402/evm/exact/server";
import { paymentMiddleware, x402ResourceServer } from "@x402/express";

type Config = { network: string; payTo: string; asset: string; facilitator_url: string; fault: string | null;
  probe_outbound?: boolean };
type Vector = { id: string; target: "verify" | "paid-route"; input: Record<string, unknown> };
type Outcome = { status: number | null; content_type: string | null; isValid: boolean | null;
  invalidReason: string | null; threw: boolean; error: string | null };

const guard = (globalThis as { __parityGuard?: { outbound: number } }).__parityGuard;
const calls = { reads: 0, writes: 0, unhandled: 0 };
process.on("unhandledRejection", () => { calls.unhandled++; });

const refuse = (what: string) => async () => { calls.writes++; throw new Error(`parity stub signer: ${what} refused`); };
const signer = {
  getAddresses: () => { calls.reads++; return ["0x209693Bc6afc0C5328bA36FaF03C514EF312287C"]; },
  getCode: async () => { calls.reads++; return "0x"; },
  readContract: async () => { calls.reads++; throw new Error("parity stub signer: no chain"); },
  verifyTypedData: async () => { calls.reads++; throw new Error("parity stub signer: no chain"); },
  writeContract: refuse("writeContract"),
  sendTransaction: refuse("sendTransaction"),
  waitForTransactionReceipt: refuse("waitForTransactionReceipt"),
};

const blank = (): Outcome => ({ status: null, content_type: null, isValid: null, invalidReason: null, threw: false,
  error: null });

function facilitatorFor(cfg: Config) {
  const networks = cfg.fault === "wildcard-network" ? [cfg.network, "eip155:84533"] : [cfg.network];
  const scheme = new ExactEvmFacilitatorScheme(signer as unknown as ConstructorParameters<typeof ExactEvmFacilitatorScheme>[0]);
  return new x402Facilitator().register(networks as `${string}:${string}`[], scheme);
}

async function verify(fac: ReturnType<typeof facilitatorFor>, v: Vector, cfg: Config): Promise<Outcome> {
  const out = blank();
  try {
    const r = await fac.verify(v.input.payload as never, v.input.requirements as never);
    out.isValid = r.isValid;
    out.invalidReason = r.invalidReason ?? null;
  } catch (e) {
    out.threw = true;
    out.error = String(e).slice(0, 200);
  }
  if (cfg.fault === "swallow-reason" && out.isValid === false) out.invalidReason = null;
  return out;
}

async function startRoute(cfg: Config): Promise<{ url: string; server: Server }> {
  const rs = new x402ResourceServer(new HTTPFacilitatorClient({ url: cfg.facilitator_url }))
    .register(cfg.network as `${string}:${string}`, new ExactEvmServerScheme());
  const app = express();
  app.use(paymentMiddleware({
    "GET /paid": { accepts: [{ scheme: "exact", price: "$0.001", network: cfg.network as `${string}:${string}`,
      payTo: cfg.payTo }], description: "parity", mimeType: "application/json" },
  }, rs));
  app.get("/paid", (_req, res) => { res.json({ content: "paid content" }); });
  const server = await new Promise<Server>((ok) => { const s = app.listen(0, "127.0.0.1", () => ok(s)); });
  return { url: `http://127.0.0.1:${(server.address() as AddressInfo).port}/paid`, server };
}

async function paidRoute(url: string, v: Vector, cfg: Config): Promise<Outcome> {
  const out = blank();
  try {
    const r = await fetch(url, { headers: { "PAYMENT-SIGNATURE": String(v.input.header) },
      signal: AbortSignal.timeout(15_000) });
    await r.arrayBuffer();
    out.status = r.status;
    out.content_type = r.headers.get("content-type");
  } catch (e) {
    out.error = `no answer: ${String(e).slice(0, 160)}`;
  }
  if (cfg.fault === "status" && out.status !== null && out.status >= 400 && out.status < 500) out.status = 500;
  return out;
}

async function main() {
  const lines = createInterface({ input: process.stdin });
  let cfg: Config | null = null;
  const vectors: Vector[] = [];
  for await (const line of lines) {
    if (!line.trim()) continue;
    const msg = JSON.parse(line) as { config?: Config; vector?: Vector };
    if (msg.config) cfg = msg.config;
    if (msg.vector) vectors.push(msg.vector);
  }
  if (!cfg) throw new Error("no config line");
  if (cfg.probe_outbound) await fetch("http://192.0.2.1/").catch(() => null); // TEST-NET-1; port 80, which fetch does not refuse itself
  const fac = facilitatorFor(cfg);
  const route = vectors.some((v) => v.target === "paid-route") ? await startRoute(cfg) : null;
  for (const v of vectors) {
    const out = v.target === "verify" ? await verify(fac, v, cfg) : await paidRoute(route!.url, v, cfg);
    process.stdout.write(JSON.stringify({ vector: v.id, ...out }) + "\n");
  }
  if (route) await new Promise<void>((ok) => { route.server.closeAllConnections(); route.server.close(() => ok()); });
  await new Promise((ok) => setTimeout(ok, 50)); // let a background asset check settle before counting
  const here = dirname(fileURLToPath(import.meta.url));
  const version = (JSON.parse(readFileSync(join(here, "..", "..", "node_modules", "@x402", "core", "package.json"),
    "utf8")) as { version: string }).version;
  process.stdout.write(JSON.stringify({ done: true, sdk: "ts", version, outbound_attempts: guard ? guard.outbound : -1,
    signer_reads: calls.reads, signer_writes: calls.writes, unhandled_rejections: calls.unhandled }) + "\n");
}

main().catch((e) => { console.error(e); process.exit(1); });
