// R24, a malformed payment header: payment headers that are not base64, not JSON or not an object are sent to a real
// @x402/express server behind the facilitator double on loopback, on Solana devnet and Base Sepolia. The control
// passes; each faulty build is caught.
import { test } from "node:test";
import assert from "node:assert/strict";
import { startDouble } from "../src/double.js";
import { probeMalformedHeader, MALFORMED_HEADERS } from "../src/header.js";
import { BASE_SEPOLIA, DEVNET, startHeaderServer, type HeaderFault } from "../example/header-server.js";
import type { Result } from "../src/probe.js";

const NETS = [["Solana devnet", DEVNET], ["Base Sepolia", BASE_SEPOLIA]] as const;
const r24 = (rs: Result[]) => {
  const r = rs.find((x) => x.check.split(" ")[0] === "R24");
  assert.ok(r, `R24 missing from ${JSON.stringify(rs.map((x) => x.check))}`);
  return r;
};

async function run(fault: HeaderFault, network: string, path = "/paid") {
  const double = await startDouble(0);
  const s = await startHeaderServer(double.url, fault, network);
  try { return { result: r24(await probeMalformedHeader(`${s.base}${path}`, double)), double }; } finally {
    await s.close(); await double.close();
  }
}

for (const [name, net] of NETS) {
  test(`R24 control: the stock @x402/express server answers every malformed payment header with 402 and a structured error, ${name}`,
    async () => {
      const { result } = await run("", net);
      assert.equal(result.pass, true, JSON.stringify(result));
      const d = result.detail as any;
      assert.equal(d.cases.length, Object.keys(MALFORMED_HEADERS).length);
      for (const c of d.cases) assert.equal(c.status, 402, JSON.stringify(c));
      assert.equal(d.facilitator_calls, 0, "nothing malformed reaches /verify or /settle");
    });
  test(`R24 decode_unchecked: a server that throws on a malformed payment header and answers 500 is caught, ${name}`,
    async () => {
      const { result } = await run("decode_unchecked", net);
      assert.equal(result.pass, false, JSON.stringify(result));
      assert.ok((result.detail as any).cases.some((c: any) => c.status === 500), JSON.stringify(result.detail));
      assert.match(String((result.detail as any).error), /got 500/);
    });
  test(`R24 drop_on_bad_header: a server that drops the connection on a malformed payment header is caught, ${name}`,
    async () => {
      const { result } = await run("drop_on_bad_header", net);
      assert.equal(result.pass, false, JSON.stringify(result));
      assert.ok((result.detail as any).cases.some((c: any) => c.status === 0), JSON.stringify(result.detail));
    });
  test(`R24 gate: a URL that is not a paid route fails and grades nothing, ${name}`, async () => {
    const { result, double } = await run("", net, "/free");
    assert.equal(result.pass, false, JSON.stringify(result));
    assert.equal((result.detail as any).cases, undefined);
    assert.equal(double.calls.filter((c) => c.path === "/settle").length, 0);
  });
}
