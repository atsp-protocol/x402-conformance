import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import http from "node:http";
import type { AddressInfo } from "node:net";
import { readFileSync, mkdtempSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, test } from "node:test";
import { BASE_SEPOLIA, DEVNET, startDouble } from "../src/double.js";
import { probe } from "../src/probe.js";
import { startExample } from "../example/server.js";
import { startStockExpress } from "../example/express-server.js";

const CLI = new URL("../src/cli.js", import.meta.url).pathname;
const PKG = JSON.parse(readFileSync(new URL("../../package.json", import.meta.url), "utf8"));
const ids = (rs: { check: string; pass: boolean }[]) => rs.filter((r) => !r.pass).map((r) => r.check.split(" ")[0]);

async function run(fault = "", network = DEVNET) {
  const double = await startDouble(0);
  const ex = await startExample(double.url, fault, 0, network);
  try {
    const results = await probe(ex.url, double, { deadlineMs: 10_000 });
    return { results, failed: ids(results) };
  } finally {
    await ex.close();
    await double.close();
  }
}

function cli(args: string[], env: Record<string, string> = {}): Promise<{ code: number; out: string; err: string }> {
  return new Promise((ok) => {
    const p = spawn(process.execPath, [CLI, ...args], { env: { ...process.env, ...env } });
    let out = "", err = "";
    p.stdout.on("data", (d) => { out += d; });
    p.stderr.on("data", (d) => { err += d; });
    p.on("exit", (code) => ok({ code: code ?? -1, out, err }));
  });
}

/** A port that was free a moment ago, for a server the CLI starts with --start. */
async function freePort(): Promise<number> {
  const s = http.createServer();
  await new Promise<void>((ok) => s.listen(0, "127.0.0.1", ok));
  const port = (s.address() as AddressInfo).port;
  await new Promise<void>((ok) => s.close(() => ok()));
  return port;
}

async function busyPort(): Promise<{ port: number; close(): Promise<void> }> {
  const s = http.createServer((_q, r) => { r.writeHead(200); r.end("someone else"); });
  await new Promise<void>((ok) => s.listen(0, "127.0.0.1", ok));
  return { port: (s.address() as AddressInfo).port, close: () => new Promise((ok) => s.close(() => ok())) };
}

describe("example servers", { concurrency: true }, () => {
  for (const net of [DEVNET, BASE_SEPOLIA]) {
    test(`the example server passes R0-R10 on ${net}`, async () => {
      const { results, failed } = await run("", net);
      assert.deepEqual(failed, [], JSON.stringify(results, null, 1));
      assert.equal(results.length, 11);
      assert.equal((results[0].detail as any).graded_on, net);
    });
    test(`a server that serves after /verify and ignores /settle is caught on ${net}`, async () => {
      const { failed } = await run("serve_after_verify", net);
      for (const c of ["R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9"]) assert.ok(failed.includes(c), `${c} not caught: ${failed}`);
    });
    test(`a server that serves whatever /settle answers is caught on ${net}`, async () => {
      const { failed } = await run("serve_on_any_settle", net);
      for (const c of ["R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9"]) assert.ok(failed.includes(c), `${c} not caught: ${failed}`);
    });
    test(`a server that serves without payment is caught on ${net}`, async () => {
      const { failed } = await run("serve_unpaid", net);
      assert.deepEqual(failed, ["R0"]);
    });
    test(`a server that serves without PAYMENT-RESPONSE is caught on ${net}`, async () => {
      const { failed } = await run("no_payment_response", net);
      assert.deepEqual(failed, ["R10"]);
    });
  }
  // Regression for the 1.2.1 R3 false positive: the double's "timeout" answered success after 30 s, so a stock server
  // with the upstream 90 s client timeout waited, got the success and served, and R3 failed a correct server.
  for (const net of [DEVNET, BASE_SEPOLIA]) {
    test(`a stock @x402/express server with default settings passes every check, R3 included, on ${net}`, async () => {
      const double = await startDouble(0);
      const ex = await startStockExpress(double.url, net);
      try {
        const results = await probe(ex.url, double, { deadlineMs: 40_000 });  // longer than the old 30 s hang
        assert.deepEqual(ids(results), [], JSON.stringify(results, null, 1));
        assert.equal(results.length, 11);
      } finally {
        await ex.close();
        await double.close();
      }
    });
  }
});

test("the double advertises Solana devnet and Base Sepolia", async () => {
  const double = await startDouble(0);
  try {
    const sup = await (await fetch(double.url + "/supported")).json();
    assert.deepEqual(sup.kinds.map((k: any) => k.network), [DEVNET, BASE_SEPOLIA]);
  } finally {
    await double.close();
  }
});

test("a server offering only networks the probe cannot grade is unsupported, not failed", async () => {
  const s = http.createServer((_q, r) => {
    const pr = { x402Version: 2, resource: { url: "x" }, accepts: [{ scheme: "exact", network: "eip155:8453", amount: "1",
      asset: "0x1", payTo: "0x2", maxTimeoutSeconds: 60, extra: { name: "USDC", version: "2" } }] };
    r.writeHead(402, { "payment-required": Buffer.from(JSON.stringify(pr)).toString("base64") });
    r.end("{}");
  });
  await new Promise<void>((ok) => s.listen(0, "127.0.0.1", ok));
  const double = await startDouble(0);
  try {
    const rs = await probe(`http://127.0.0.1:${(s.address() as AddressInfo).port}/`, double);
    assert.equal(rs.length, 1);
    assert.equal(rs[0].status, "unsupported");
  } finally {
    await double.close();
    await new Promise((ok) => s.close(ok));
  }
});

test("a server that is not using the double fails R1 and the probe stops", async () => {
  const other = await startDouble(0);   // the server's real facilitator, not the probe's double
  const ex = await startExample(other.url);
  const double = await startDouble(0);
  try {
    const rs = await probe(ex.url, double, { deadlineMs: 10_000 });
    assert.deepEqual(rs.map((r) => [r.check.split(" ")[0], r.pass]), [["R0", true], ["R1", false]]);
  } finally {
    await ex.close(); await double.close(); await other.close();
  }
});

describe("CLI", () => {
  test("--help and --version exit 0", async () => {
    const h = await cli(["--help"]);
    assert.equal(h.code, 0);
    assert.match(h.out, /probe --resource/);
    assert.match(h.out, /exit codes/);
    const v = await cli(["--version"]);
    assert.equal(v.code, 0);
    assert.equal(v.out.trim(), PKG.version);
  });
  test("usage errors exit 2", async () => {
    assert.equal((await cli([])).code, 2);
    assert.equal((await cli(["probe", "--bogus", "x"])).code, 2);
  });
  test("a taken double port exits 2 and still writes the results file with the error", async () => {
    const busy = await busyPort();
    const out = join(mkdtempSync(join(tmpdir(), "x402c-")), "r.json");
    try {
      const r = await cli(["probe", "--resource", "http://127.0.0.1:9/paid", "--port", String(busy.port), "--out", out]);
      assert.equal(r.code, 2);
      assert.match(JSON.parse(readFileSync(out, "utf8")).error, /already in use/);
    } finally { await busy.close(); }
  });
  test("--start refuses a resource port another process already answers on", async () => {
    const busy = await busyPort();
    try {
      const r = await cli(["probe", "--resource", `http://127.0.0.1:${busy.port}/paid`, "--port", "0",
        "--start", `node -e "setTimeout(()=>{},60000)"`]);
      assert.equal(r.code, 2);
      assert.match(r.err, /already answering/);
    } finally { await busy.close(); }
  });
  test("a --start server that exits is reported, not probed", async () => {
    const out = join(mkdtempSync(join(tmpdir(), "x402c-")), "r.json");
    const r = await cli(["probe", "--resource", "http://127.0.0.1:9/paid", "--port", "0", "--start", "exit 7", "--out", out]);
    assert.equal(r.code, 2);
    assert.ok(existsSync(out));
    assert.match(JSON.parse(readFileSync(out, "utf8")).error, /exited with code 7/);
  });
  // The CLI prints its JSON document last; a --start server may have printed lines before it.
  const lastDoc = (out: string) => JSON.parse(out.slice(out.lastIndexOf('{\n "tool"')));
  test("the CLI passes the example server end to end and exits 0", async () => {
    const ex = join(new URL("../example/server.js", import.meta.url).pathname);
    const port = await freePort();
    const r = await cli(["probe", "--resource", `http://127.0.0.1:${port}/paid`, "--port", "0",
      "--start", `PORT=${port} node ${ex}`]);
    assert.equal(r.code, 0, r.err + r.out);
    const doc = lastDoc(r.out);
    assert.equal(doc.evidence, "x402-conformance-evidence/2");
    for (const x of doc.results) assert.ok(x.profile && x.basis && x.fix.includes("FIXES.md#r"), JSON.stringify(x));
  });
  test("the CLI runs the R11 binding checks end to end and catches a server that trusts the client", async () => {
    const ex = join(new URL("../example/binding-server.js", import.meta.url).pathname);
    // Each run starts its own server on a port of its own: the first one's process may still hold its port while the
    // second starts.
    const args = (fault: string, port: number) => {
      const b = `http://127.0.0.1:${port}`;
      return ["probe", "--port", "0", "--cheap", `${b}/cheap`, "--expensive", `${b}/expensive`,
        "--by-method", `${b}/item`, "--by-query", `${b}/report?tier=basic,${b}/report?tier=pro`,
        "--param", `${b}/items/{id}/premium`, "--start", `PORT=${port} BINDING_FAULT=${fault} node ${ex}`];
    };
    const ok = await cli(args("", await freePort()));
    assert.equal(ok.code, 0, ok.err + ok.out);
    const ids = lastDoc(ok.out).results.map((x: any) => x.check.split(" ")[0]);
    assert.deepEqual(ids, ["R11", "R11a", "R11b", "R11c", "R11d", "R11e"]);
    const bad = await cli(args("trust_client", await freePort()));
    assert.equal(bad.code, 1, bad.err + bad.out);
    const profiles = lastDoc(bad.out).results.filter((x: any) => !x.pass).map((x: any) => x.profile);
    assert.deepEqual(profiles, ["normative", "normative", "security-profile", "security-profile"]);
  });
  test("demo: the bundled mock passes R0-R10 in under 60 s with no wallet or project", async () => {
    const out = join(mkdtempSync(join(tmpdir(), "x402c-demo-")), "demo.json");
    const t0 = Date.now();
    const r = await cli(["demo", "--out", out]);
    const secs = (Date.now() - t0) / 1000;
    assert.equal(r.code, 0, r.err + r.out);
    assert.ok(secs < 60, `the demo took ${secs} s`);
    assert.match(r.out, /11\/11 checks pass/);
    const doc = JSON.parse(readFileSync(out, "utf8"));
    assert.equal(doc.evidence, "x402-conformance-evidence/2");
    assert.equal(doc.results.length, 11);
  });
  test("demo --fault: a failing run exits 1 and prints a fix link under every failure", async () => {
    const r = await cli(["demo", "--fault", "serve_on_any_settle"]);
    assert.equal(r.code, 1, r.err + r.out);
    const fails = r.out.split("\n").filter((l) => l.trimStart().startsWith("FAIL"));
    const fixes = r.out.split("\n").filter((l) => l.trimStart().startsWith("fix: https://"));
    assert.ok(fails.length > 0 && fails.length === fixes.length, r.out);
    assert.equal((await cli(["demo", "--fault", "nope"])).code, 2);
  });
  test("binding options are checked before anything starts", async () => {
    assert.equal((await cli(["probe", "--cheap", "http://127.0.0.1:1/a"])).code, 2);
    assert.equal((await cli(["probe", "--param", "http://127.0.0.1:1/items/x"])).code, 2);
    assert.equal((await cli(["probe", "--by-query", "http://127.0.0.1:1/a"])).code, 2);
  });
});
