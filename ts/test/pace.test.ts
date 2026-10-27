// Pacing for live targets: the interval, the loopback exemption, the request cap and the log.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createPacedFetch, RequestBudgetExceeded } from "../src/pace.js";

function fake() {
  let t = 1_000;
  const slept: number[] = [];
  const sent: string[] = [];
  const log: string[] = [];
  const f = (async (u: any, init?: RequestInit) => { sent.push(`${init?.method ?? "GET"} ${u}`); return new Response(null, { status: 402 }); }) as typeof fetch;
  return { slept, sent, log, now: () => t, sleep: async (ms: number) => { slept.push(ms); t += ms; }, advance: (ms: number) => { t += ms; }, f };
}

test("pace: live requests are spaced by the minimum interval and each one is logged", async () => {
  const k = fake();
  const p = createPacedFetch({ minIntervalMs: 5000, fetch: k.f, now: k.now, sleep: k.sleep, log: (l) => k.log.push(l) });
  await p("https://live.example/paid");
  k.advance(1200);
  await p("https://live.example/paid", { method: "HEAD" });
  await p("https://live.example/paid", { headers: { "PAYMENT-SIGNATURE": "%%%" } });
  assert.deepEqual(k.slept, [3800, 5000]);
  assert.equal(k.log.length, 3);
  assert.match(k.log[1], /request 2 at .*: HEAD https:\/\/live\.example\/paid, after waiting 3\.8 s/);
  assert.match(k.log[2], /malformed PAYMENT-SIGNATURE/);
  assert.deepEqual(p.requests.map((r) => r.status), [402, 402, 402]);
});

test("pace: concurrent calls are still spaced one after another", async () => {
  const k = fake();
  const p = createPacedFetch({ minIntervalMs: 5000, fetch: k.f, now: k.now, sleep: k.sleep, log: () => {} });
  await Promise.all([p("https://live.example/a"), p("https://live.example/b"), p("https://live.example/c")]);
  assert.deepEqual(k.slept, [5000, 5000]);
});

test("pace: loopback targets are counted but not spaced", async () => {
  const k = fake();
  const p = createPacedFetch({ fetch: k.f, now: k.now, sleep: k.sleep, log: () => {} });
  for (let i = 0; i < 3; i++) await p("http://127.0.0.1:4020/paid");
  assert.deepEqual(k.slept, []);
  assert.equal(p.requests.length, 3);
});

test("pace: a request over --max-requests is refused before it is sent", async () => {
  const k = fake();
  const p = createPacedFetch({ minIntervalMs: 0, maxRequests: 2, fetch: k.f, now: k.now, sleep: k.sleep, log: () => {} });
  await p("https://live.example/1");
  await p("https://live.example/2");
  await assert.rejects(p("https://live.example/3"), RequestBudgetExceeded);
  assert.equal(k.sent.length, 2);
  assert.throws(() => createPacedFetch({ maxRequests: 0 }), RangeError);
  assert.throws(() => createPacedFetch({ minIntervalMs: -1 }), RangeError);
});

test("pace: x402conf-svm live grades P1-P7, R16a and R24, logs every request it sends and honours --max-requests",
  async () => {
  const { spawn } = await import("node:child_process");
  const { mkdtempSync, readFileSync } = await import("node:fs");
  const { tmpdir } = await import("node:os");
  const { join } = await import("node:path");
  const { startDouble } = await import("../src/double.js");
  const { startUnpaidHeadServer, BASE_SEPOLIA } = await import("../example/head-unpaid-server.js");
  const double = await startDouble(0);
  const s = await startUnpaidHeadServer(double.url, "head_refused", BASE_SEPOLIA);
  const cli = new URL("../src/cli.js", import.meta.url).pathname;
  // The CLI prints its report and then exits, so on macOS a piped stdout can be cut at 8192 bytes. The full run reads
  // the report from --out, a synchronous file write, and every run waits for the process to close, not to exit.
  const run = (...args: string[]) => new Promise<{ code: number; out: string; err: string }>((ok) => {
    const p = spawn(process.execPath, [cli, "live", "--url", s.url, ...args]);
    let out = "", err = "";
    p.stdout.on("data", (d) => { out += d; });
    p.stderr.on("data", (d) => { err += d; });
    p.on("close", (code) => ok({ code: code ?? 2, out, err }));
  });
  try {
    const report = join(mkdtempSync(join(tmpdir(), "x402conf-pace-")), "live.json");
    const full = await run("--min-interval", "0", "--out", report);
    assert.equal(full.code, 0, full.err);
    const doc = JSON.parse(readFileSync(report, "utf8"));
    assert.deepEqual(doc.checks.map((c: any) => c.check.split(" ")[0]), ["P1", "P2", "P6", "P3", "P4", "P5", "P7", "R16a", "R24"]);
    assert.ok(doc.checks.every((c: any) => c.pass), JSON.stringify(doc.checks));
    // Two requests are shared: the unpaid GET the P checks grade and R16a's HEAD. R24 sends one request per malformed
    // header it tries, and its own unpaid requests when it reports them. The count is derived from the run, so it
    // holds whatever R24 sends.
    const r24 = doc.checks.find((c: any) => c.check.startsWith("R24"));
    const expected = 2 + r24.detail.cases.length + (r24.detail.unpaid_requests ?? 0);
    assert.equal(doc.pacing.sent, expected);
    assert.equal(doc.pacing.requests.length, expected);
    assert.equal((full.err.match(/x402conf-svm: request \d/g) ?? []).length, expected);
    const capped = await run("--min-interval", "0", "--max-requests", "2");
    const d2 = JSON.parse(capped.out);
    assert.equal(d2.pacing.sent, 2);
    assert.match(d2.skipped[0], /--max-requests 2 reached/);
    assert.ok(!d2.checks.some((c: any) => c.check.startsWith("R24")));
  } finally { await s.close(); await double.close(); }
});
