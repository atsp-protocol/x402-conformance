// R14: a crash between a successful /settle and the response. The crash server runs as a real subprocess: the probe
// SIGKILLs its process group at the crash point and starts it again with the same store file.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, test } from "node:test";
import { BASE_SEPOLIA, DEVNET, startDouble } from "../src/double.js";
import { probe } from "../src/probe.js";
import { probeCrash, SpawnedServer, base58, paymentRef } from "../src/crash.js";
import { freePort, withPorts } from "./ports.js";

const CLI = new URL("../src/cli.js", import.meta.url).pathname;
const SERVER = new URL("../example/crash-server.js", import.meta.url).pathname;

async function up(url: string): Promise<void> {
  for (let i = 0; i < 100; i++) {
    try { await fetch(url, { signal: AbortSignal.timeout(1000) }); return; } catch { await new Promise((ok) => setTimeout(ok, 100)); }
  }
  throw new Error(`no answer from ${url}`);
}

/** Starts the crash server under a SpawnedServer, runs R0-R10 and R14 against it, and returns both. */
async function run(fault: string, network: string) {
  const double = await startDouble(0);
  const port = await freePort();
  const store = join(mkdtempSync(join(tmpdir(), "x402c-r14-")), "store.json");
  const url = `http://127.0.0.1:${port}/paid`;
  const srv = new SpawnedServer(`node ${SERVER}`, { ...process.env, X402_FACILITATOR_URL: double.url, PORT: String(port),
    CRASH_FAULT: fault, CRASH_STORE: store, EXAMPLE_NETWORK: network }, "ignore");
  srv.start();
  try {
    await up(url);
    const base = await probe(url, double, { deadlineMs: 10_000 });
    const [r14] = await probeCrash(url, double, srv, { deadlineMs: 10_000, upMs: 20_000 });
    return { base, r14, d: r14.detail as any, settleCalls: double.calls.filter((c) => c.path === "/settle").length };
  } finally {
    srv.stop();
    await double.close();
  }
}

const point = (d: any, p: string) => d.crash_points[p];

describe("R14 crash between settle and response", { concurrency: true }, () => {
  for (const net of [DEVNET, BASE_SEPOLIA]) {
    test(`R14 control: a server with a durable idempotency record passes on ${net}`, async () => {
      const { base, r14, d } = await run("", net);
      assert.deepEqual(base.filter((r) => !r.pass).map((r) => r.check.split(" ")[0]), [], JSON.stringify(base, null, 1));
      assert.equal(r14.pass, true, JSON.stringify(r14, null, 1));
      assert.equal(d.graded_on, net);
      for (const p of ["settle", "response"]) {
        assert.equal(point(d, p).first_attempt, "no response (server killed)");
        assert.equal(point(d, p).settlements, 1);
        assert.equal(point(d, p).settle_calls_after_restart, 0);
        assert.equal(point(d, p).payment_identifier, "sent");
      }
      // Killed during /settle, it never heard the outcome: it refuses and names the payment for reconciliation.
      assert.equal(point(d, "settle").after_restart.status, 409);
      assert.equal(point(d, "settle").after_restart.outcome, "refused, payment surfaced");
      // Killed while answering, it replays the cached response for the same payment id.
      assert.equal(point(d, "response").after_restart.outcome, "delivered");
    });
    test(`R14 catches a server whose idempotency record is in memory only (it settles again after a restart) on ${net}`, async () => {
      const { r14, d } = await run("memory_record", net);
      assert.equal(r14.pass, false);
      for (const p of ["settle", "response"]) {
        assert.equal(point(d, p).settle_calls_after_restart, 1, JSON.stringify(d, null, 1));
        assert.equal(point(d, p).settlements, 1, "the double refuses the second settle (duplicate_settlement)");
        assert.equal(point(d, p).after_restart.outcome, "asked to pay again");
        assert.match(point(d, p).problems[0], /called \/settle again/);
      }
    });
    test(`R14 catches a server that writes its record only after /settle returns on ${net}`, async () => {
      const { r14, d } = await run("record_after_settle", net);
      assert.equal(r14.pass, false);
      assert.equal(point(d, "settle").settle_calls_after_restart, 1, JSON.stringify(d, null, 1));
      assert.ok(point(d, "settle").problems.length > 0);
      // The crash after /settle answered is survived: the record was written before the response.
      assert.equal(point(d, "response").problems, undefined, JSON.stringify(d, null, 1));
    });
    test(`R14 catches a server that refuses after a restart without surfacing the payment on ${net}`, async () => {
      const { r14, d } = await run("refuse_silent", net);
      assert.equal(r14.pass, false);
      for (const p of ["settle", "response"]) {
        assert.equal(point(d, p).settle_calls_after_restart, 0, JSON.stringify(d, null, 1));
        assert.equal(point(d, p).after_restart.outcome, "refused, nothing surfaced");
      }
    });
  }
  test("R14 payment references: a Solana transaction is known by its first signature, an EVM payment by its nonce", () => {
    const tx = Buffer.alloc(100, 0);
    tx[0] = 1;
    tx[1] = 7;
    assert.equal(paymentRef({ transaction: tx.toString("base64") }), base58(tx.subarray(1, 65)));
    assert.equal(base58(Uint8Array.from([0, 0, 1])), "112");
    assert.equal(paymentRef({ authorization: { nonce: "0xabc" } }), "0xabc");
  });
});

describe("R14 from the CLI", { concurrency: true }, () => {
  const cli = (args: string[], env: Record<string, string> = {}): Promise<{ code: number; out: string; err: string }> =>
    new Promise((ok) => {
      const p = spawn(process.execPath, [CLI, ...args], { env: { ...process.env, ...env } });
      let out = "", err = "";
      p.stdout.on("data", (x) => { out += x; });
      p.stderr.on("data", (x) => { err += x; });
      p.on("exit", (code) => ok({ code: code ?? -1, out, err }));
    });
  const lastDoc = (out: string) => JSON.parse(out.slice(out.lastIndexOf('{\n "tool"')));

  test("R14 the CLI runs the crash check with --crash and --start, and fails a faulty server", async () => {
    for (const [fault, code] of [["", 0], ["memory_record", 1]] as const) {
      // Each attempt gets its own store and results file: a run on a taken port must not leave records behind.
      let out = "";
      const r = await withPorts(1, ([port]) => {
        const store = join(mkdtempSync(join(tmpdir(), "x402c-r14-")), "store.json");
        out = join(mkdtempSync(join(tmpdir(), "x402c-r14-")), "resource-server.json");
        return cli(["probe", "--resource", `http://127.0.0.1:${port}/paid`, "--port", "0", "--crash", "--out", out,
          "--start", `PORT=${port} CRASH_STORE=${store} CRASH_FAULT=${fault} node ${SERVER}`]);
      });
      assert.equal(r.code, code, r.err + r.out);
      const doc = JSON.parse(readFileSync(out, "utf8"));
      const r14 = doc.results.find((x: any) => x.check.startsWith("R14"));
      assert.equal(r14.pass, code === 0, JSON.stringify(r14, null, 1));
      assert.equal(r14.profile, "resilience");
      assert.ok(r14.fix.endsWith("FIXES.md#r14"));
      assert.equal(doc.results.length, 12, "R0-R10 and R14");
      assert.equal(lastDoc(r.out).results.length, 12);
    }
  });
  test("R14 the CLI crashes and restarts a server it did not start with --crash-kill and --crash-restart", async () => {
    // The server is started here, before the CLI exists, so the double's port has to be chosen in advance: this is
    // the one CLI run that cannot use --port 0. Each attempt starts its own server and stops it before the next.
    const r = await withPorts(2, async ([port, double]) => {
      const dir = mkdtempSync(join(tmpdir(), "x402c-r14-"));
      const env = `X402_FACILITATOR_URL=http://127.0.0.1:${double} PORT=${port} CRASH_STORE=${dir}/store.json`;
      const startCmd = `${env} nohup node ${SERVER} >/dev/null 2>&1 & echo $! > ${dir}/pid`;
      await new Promise<void>((ok, fail) => spawn(startCmd, { shell: true, stdio: "ignore" })
        .on("exit", (c) => c === 0 ? ok() : fail(new Error(String(c)))));
      try {
        return await cli(["probe", "--resource", `http://127.0.0.1:${port}/paid`, "--port", String(double), "--crash",
          "--crash-kill", `kill -9 $(cat ${dir}/pid); while kill -0 $(cat ${dir}/pid) 2>/dev/null; do sleep 0.05; done`,
          "--crash-restart", startCmd]);
      } finally {
        try { process.kill(Number(readFileSync(join(dir, "pid"), "utf8")), "SIGTERM"); } catch { /* already gone */ }
      }
    });
    assert.equal(r.code, 0, r.err + r.out);
    const r14 = lastDoc(r.out).results.find((x: any) => x.check.startsWith("R14"));
    assert.equal(r14.pass, true, JSON.stringify(r14, null, 1));
  });
  test("R14 usage: --crash needs --resource and a way to restart the server", async () => {
    for (const args of [["probe", "--resource", "http://127.0.0.1:1/paid", "--crash"],
      ["probe", "--cheap", "http://127.0.0.1:1/a", "--expensive", "http://127.0.0.1:1/b", "--crash", "--start", "true"],
      ["probe", "--resource", "http://127.0.0.1:1/paid", "--crash", "--crash-kill", "true"],
      ["probe", "--resource", "http://127.0.0.1:1/paid", "--crash-kill", "true", "--crash-restart", "true", "--start", "true"]]) {
      const r = await cli(args);
      assert.equal(r.code, 2, `${args.join(" ")}: ${r.err}`);
    }
  });
});
