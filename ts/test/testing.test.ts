// The test-framework entry point: runConformance(), the expect.extend matchers, the report, the anonymised corpus case
// and the CLI's resource command and --share. Every run is on loopback against the facilitator double.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, test } from "node:test";
import { BASE_SEPOLIA, DEVNET } from "../src/double.js";
import { anonymise, shareUrl } from "../src/corpus.js";
import { LINKS, makeReport } from "../src/report.js";
import { assertX402Conformance, runConformance, saveReport, x402Matchers, checkPaymentRequired } from "../src/testing.js";
import { startExample } from "../example/server.js";
import { startStockExpress } from "../example/express-server.js";
import { startStockHono } from "../example/hono-server.js";
import { withPorts } from "./ports.js";

const CLI = new URL("../src/cli.js", import.meta.url).pathname;

function cli(args: string[], env: Record<string, string> = {}, cwd?: string): Promise<{ code: number; out: string; err: string }> {
  return new Promise((ok) => {
    const p = spawn(process.execPath, [CLI, ...args], { env: { ...process.env, ...env }, cwd });
    let out = "", err = "";
    p.stdout.on("data", (d) => { out += d; });
    p.stderr.on("data", (d) => { err += d; });
    p.on("exit", (code) => ok({ code: code ?? -1, out, err }));
  });
}

describe("runConformance with the stock middleware", { concurrency: true }, () => {
  for (const net of [DEVNET, BASE_SEPOLIA]) {
    test(`stock @x402/hono passes R0-R10 on ${net}`, async () => {
      const report = await runConformance({ via: "node-test", start: (f) => startStockHono(f, net) });
      assert.equal(x402Matchers.toPassX402Conformance.call(undefined, report).pass, true, JSON.stringify(report, null, 1));
      assert.equal(report.results.length, 11);
      assert.equal(report.kind, "resource-server");
      assert.equal(report.via, "node-test");
    });
    test(`stock @x402/express passes R0-R10 on ${net}`, async () => {
      const report = await runConformance({ start: (f) => startStockExpress(f, net) });
      assert.doesNotThrow(() => assertX402Conformance(report));
      assert.equal(report.via, "testing");
    });
  }
});

describe("a faulty server is caught, and the message funnels to the fix and the corpus", () => {
  test("serve_on_any_settle fails the matcher with fix links", async () => {
    const report = await runConformance({ via: "node-test", start: (f) => startExample(f, "serve_on_any_settle") });
    const m = x402Matchers.toPassX402Conformance.call(undefined, report);
    assert.equal(m.pass, false);
    for (const id of ["R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9"]) assert.ok(report.summary.failed_ids.includes(id), id);
    const msg = m.message();
    assert.match(msg, /docs\/FIXES\.md#r3/);
    assert.ok(msg.includes(LINKS.contribute) && msg.includes(LINKS.corpus));
    assert.throws(() => assertX402Conformance(report), /R5 \/settle 503/);
  });
  test("a server that cannot start is a failed run, not a crash", async () => {
    const report = await runConformance({ start: () => { throw new Error("boom"); } });
    assert.match(report.error ?? "", /boom/);
    assert.equal(x402Matchers.toPassX402Conformance.call(undefined, report).pass, false);
  });
  test("the matchers refuse anything that is not a report", () => {
    assert.equal(x402Matchers.toPassX402Conformance.call(undefined, { results: [] }).pass, false);
    assert.equal(x402Matchers.toBeValidX402Challenge.call(undefined, makeReport("resource-server", "x", [])).pass, false);
  });
});

describe("corpus case: anonymised, opt-in, never sent", () => {
  const report = makeReport("resource-402", "https://api.seller.example.com/paid?key=abc", [
    { check: "P1 an unpaid GET answers HTTP 402 (V2 HTTP transport)", pass: true },
    { check: "P5 scheme-specific extra fields are present", pass: false, detail: { problems: [{ network:
      "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1", payTo: "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin",
      note: "seen at https://api.seller.example.com/x from 10.1.2.3:8080 paying 0x209693Bc6afc0C5328bA36FaF03C514EF312287C on seller.io" }] } },
  ], "vitest");
  test("anonymise drops URLs, hosts, IPs and addresses but keeps check IDs and public network IDs", () => {
    const c = anonymise(report, { framework: "hono", sdk: "@x402/hono", sdk_version: "2.28.0" });
    const text = JSON.stringify(c);
    for (const leak of ["seller", "9xQeWvG8", "0x209693", "10.1.2.3", "key=abc", "https://"]) assert.ok(!text.includes(leak), leak);
    assert.ok(text.includes("solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"));
    assert.deepEqual(c.failed_ids, ["P5"]);
    assert.equal(c.target, "redacted");
    assert.equal(c.via, "vitest");
    assert.equal(c.results[0].detail, null);
  });
  test("anonymise matches the fixture the Python CLI also matches", () => {
    const root = new URL("../../../corpus/fixtures/", import.meta.url);
    const input = JSON.parse(readFileSync(new URL("anonymise-input.json", root), "utf8"));
    const expected = JSON.parse(readFileSync(new URL("anonymise-expected.json", root), "utf8"));
    assert.deepEqual(anonymise(input.report, input.stack), expected);
  });
  test("shareUrl pre-fills the corpus-case issue form and is null for a passing run", () => {
    const u = new URL(shareUrl(anonymise(report, { framework: "hono" }))!);
    assert.equal(u.origin + u.pathname, "https://github.com/atsp-protocol/x402-conformance/issues/new");
    assert.equal(u.searchParams.get("template"), "corpus-case.yml");
    assert.equal(u.searchParams.get("checks"), "P5");
    assert.ok(u.toString().length < 8000);
    assert.equal(shareUrl(anonymise(makeReport("resource-402", "x", [{ check: "P1 x", pass: true }]))), null);
  });
  test("saveReport writes the report, and the case only with share", () => {
    const dir = mkdtempSync(join(tmpdir(), "x402c-"));
    const plain = saveReport(report, { dir });
    assert.ok(existsSync(plain.report) && !plain.case);
    const shared = saveReport(report, { dir, share: true });
    assert.ok(shared.case && existsSync(shared.case) && shared.shareUrl);
    assert.equal(JSON.parse(readFileSync(shared.case, "utf8")).schema, "x402-conformance.case/1");
  });
});

describe("CLI: resource and --share", () => {
  test("resource checks a 402 answer, tags the report and prints the funnel footer", async () => {
    const dir = mkdtempSync(join(tmpdir(), "x402c-"));
    const { startDouble } = await import("../src/double.js");
    const double = await startDouble(0);
    const ex = await startStockHono(double.url);
    try {
      const r = await cli(["resource", "--url", ex.url, "--out", join(dir, "r.json")], { X402CONF_VIA: "docker" });
      assert.equal(r.code, 0, r.err);
      const doc = JSON.parse(readFileSync(join(dir, "r.json"), "utf8"));
      assert.equal(doc.schema, "x402-conformance.report/1");
      assert.equal(doc.via, "docker");
      assert.deepEqual(doc.summary.failed_ids, []);
      assert.match(r.err, /Add the badge/);
    } finally { await ex.close(); await double.close(); }
  });
  test("--share on a failing probe writes the anonymised case and prints the link, sending nothing", async () => {
    const dir = mkdtempSync(join(tmpdir(), "x402c-"));
    const server = new URL("../example/server.js", import.meta.url).pathname;
    const r = await withPorts(2, ([port, doublePort]) => cli(["probe", "--resource", `http://127.0.0.1:${port}/paid`,
      "--port", String(doublePort), "--start", `PORT=${port} EXAMPLE_FAULT=serve_on_any_settle ${process.execPath} ${server}`,
      "--out", join(dir, "p.json"), "--share"]));
    assert.equal(r.code, 1, r.err);
    const c = JSON.parse(readFileSync(join(dir, "p.case.json"), "utf8"));
    assert.equal(c.target, "loopback");
    assert.ok(c.failed_ids.includes("R3"));
    assert.equal(c.via, "cli-ts");
    assert.match(r.err, /nothing was sent/);
    assert.match(r.err, /issues\/new\?template=corpus-case\.yml/);
  });
  test("usage errors", async () => {
    assert.equal((await cli(["resource"])).code, 2);
    assert.equal((await cli(["resource", "--url", "http://x", "--start", "y"])).code, 2);
    assert.equal((await cli(["probe", "--url", "http://x"])).code, 2);
  });
  test("an unknown X402CONF_VIA falls back to cli-ts", async () => {
    const r = await cli(["resource", "--url", "http://127.0.0.1:9/paid"], { X402CONF_VIA: "evil; rm -rf" });
    assert.equal(JSON.parse(r.out).via, "cli-ts");
    assert.equal(r.code, 1);
  });
});

test("checkPaymentRequired is re-exported for test suites", () => { assert.equal(typeof checkPaymentRequired, "function"); });
