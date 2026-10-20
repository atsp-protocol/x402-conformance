#!/usr/bin/env node
// x402conf-svm probe --resource <url> [--port 4402] [--start "<command>"] [--out results.json]
// Starts the facilitator double on 127.0.0.1:<port>, optionally starts your resource server with
// X402_FACILITATOR_URL pointing at it, waits for the resource to answer, runs R0-R9 and exits 0 only if all pass.
import { spawn } from "node:child_process";
import { writeFileSync } from "node:fs";
import { startDouble } from "./double.js";
import { probe } from "./probe.js";

function arg(name: string, def?: string): string | undefined {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : def;
}

async function main(): Promise<number> {
  if (process.argv[2] !== "probe" || !arg("resource")) {
    console.error('usage: x402conf-svm probe --resource <url> [--port 4402] [--start "<command>"] [--out file]');
    return 2;
  }
  const resource = arg("resource") as string;
  const double = await startDouble(Number(arg("port", "4402")));
  const cmd = arg("start");
  const child = cmd ? spawn(cmd, { shell: true, stdio: "inherit", env: { ...process.env, X402_FACILITATOR_URL: double.url } }) : null;
  try {
    for (let i = 0; i < 60; i++) {
      try { await fetch(resource, { signal: AbortSignal.timeout(2000) }); break; } catch { await new Promise((ok) => setTimeout(ok, 1000)); }
    }
    const results = await probe(resource, double);
    const doc = { tool: "x402-conformance-svm 1.2.1", run_at: new Date().toISOString(), resource, facilitator_double: double.url, results };
    const text = JSON.stringify(doc, null, 1);
    const out = arg("out");
    if (out) writeFileSync(out, text + "\n");
    console.log(text);
    return results.every((r) => r.pass) ? 0 : 1;
  } finally {
    child?.kill();
    await double.close();
  }
}

main().then((c) => process.exit(c), (e) => { console.error(e); process.exit(2); });
