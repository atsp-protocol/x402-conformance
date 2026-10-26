// R24, a malformed payment header: payment headers that are not base64, not JSON, not an object, JSON null, true,
// false, an empty object, an object with null members, empty or blank are sent to a real @x402/express server behind
// the facilitator double on loopback, on Solana devnet and Base Sepolia, and to V1 and dual-version routes built in the
// example. The controls pass; each faulty build is caught, and the three added for XC-90 pass the original five-value
// R24, so only the added values or the V1 header catch them.
import { test } from "node:test";
import assert from "node:assert/strict";
import { startDouble } from "../src/double.js";
import { probeMalformedHeader, MALFORMED_HEADERS, ORIGINAL_MALFORMED_HEADERS, type MalformedHeaderOptions } from "../src/header.js";
import { BASE_SEPOLIA, DEVNET, startHeaderServer, type HeaderFault, type HeaderRoute } from "../example/header-server.js";
import type { Result } from "../src/probe.js";

const NETS = [["Solana devnet", DEVNET], ["Base Sepolia", BASE_SEPOLIA]] as const;
const N = Object.keys(MALFORMED_HEADERS).length;
// R24 as it was before XC-90: the five original values, in PAYMENT-SIGNATURE only
const ORIGINAL: MalformedHeaderOptions = { values: ORIGINAL_MALFORMED_HEADERS, headers: ["PAYMENT-SIGNATURE"] };
const r24 = (rs: Result[]) => {
  const r = rs.find((x) => x.check.split(" ")[0] === "R24");
  assert.ok(r, `R24 missing from ${JSON.stringify(rs.map((x) => x.check))}`);
  return r;
};

async function run(fault: HeaderFault, network: string, path = "/paid", opts: MalformedHeaderOptions = {}, route?: HeaderRoute) {
  const double = await startDouble(0);
  const s = await startHeaderServer(double.url, fault, network, 0, route);
  try { return { result: r24(await probeMalformedHeader(`${s.base}${path}`, double, opts)), double, seen: s.seen }; } finally {
    await s.close(); await double.close();
  }
}

test("R24 values: the five original values are unchanged and seven are added", () => {
  assert.deepEqual(Object.keys(ORIGINAL_MALFORMED_HEADERS), ["not_base64", "base64_not_json", "json_array", "json_string", "json_number"]);
  for (const [k, v] of Object.entries(ORIGINAL_MALFORMED_HEADERS)) assert.equal(MALFORMED_HEADERS[k], v);
  const b = (k: string) => Buffer.from(MALFORMED_HEADERS[k], "base64").toString("utf8");
  assert.equal(b("json_null"), "null");
  assert.equal(b("json_true"), "true");
  assert.equal(b("json_false"), "false");
  assert.equal(b("json_empty_object"), "{}");
  assert.deepEqual(JSON.parse(b("json_null_members")), { x402Version: 2, accepted: null, payload: null });
  assert.equal(MALFORMED_HEADERS.empty, "");
  assert.equal(MALFORMED_HEADERS.whitespace, " ");
  assert.equal(N, 12);
});

for (const [name, net] of NETS) {
  test(`R24 control: the stock @x402/express server answers every malformed payment header with 402 and a structured error, ${name}`,
    async () => {
      const { result, seen } = await run("", net);
      assert.equal(result.pass, true, JSON.stringify(result));
      const d = result.detail as any;
      assert.deepEqual(d.advertised, { v1: false, v2: true });
      assert.equal(d.cases.length, N);
      for (const c of d.cases) {
        assert.equal(c.status, 402, JSON.stringify(c));
        assert.equal(c.sent_in, "PAYMENT-SIGNATURE");
        assert.equal(c.facilitator_calls, 0, JSON.stringify(c));
      }
      assert.equal(d.facilitator_calls, 0, "nothing malformed reaches /verify or /settle");
      assert.deepEqual(d.control_after, { status: 402 });
      assert.equal(d.unpaid_requests, 2, "its own unpaid GET and the control after the batch");
      // fetch trims the blank value, so both empty and whitespace reach the server as an empty value
      assert.equal(seen.filter((x) => x.header === "PAYMENT-SIGNATURE" && x.value === "").length, 2);
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
  test(`R24 null_member_deref: a server that reads a member of a decoded null or {} answers 500 and is caught; the original R24 `
    + `passes it, ${name}`, async () => {
    const { result } = await run("null_member_deref", net);
    assert.equal(result.pass, false, JSON.stringify(result));
    const bad = (result.detail as any).cases.filter((c: any) => c.status === 500).map((c: any) => c.header).sort();
    assert.deepEqual(bad, ["json_empty_object", "json_null", "json_null_members"]);
    assert.equal((await run("null_member_deref", net, "/paid", ORIGINAL)).result.pass, true, "the five original values miss it");
  });
  test(`R24 parse_error_is_500: a server that maps the parse error of an empty header to 500 is caught; the original R24 `
    + `passes it, ${name}`, async () => {
    const { result } = await run("parse_error_is_500", net);
    assert.equal(result.pass, false, JSON.stringify(result));
    const bad = (result.detail as any).cases.filter((c: any) => c.status === 500).map((c: any) => c.header).sort();
    assert.deepEqual(bad, ["empty", "whitespace"]);
    assert.equal((await run("parse_error_is_500", net, "/paid", ORIGINAL)).result.pass, true, "the five original values miss it");
  });
}

for (const [name, net] of NETS) {
  test(`R24 v1 only: a route that advertises only x402Version 1 gets every value in X-PAYMENT, none in PAYMENT-SIGNATURE, `
    + `and its V1 body with accepts is graded as structured, ${name}`, async () => {
    const { result, seen } = await run("", net, "/paid", {}, "v1");
    assert.equal(result.pass, true, JSON.stringify(result));
    const d = result.detail as any;
    assert.deepEqual(d.advertised, { v1: true, v2: false });
    assert.deepEqual(d.sent_in, ["X-PAYMENT"]);
    assert.equal(d.cases.length, N);
    for (const c of d.cases) assert.ok(c.status === 402 && c.structured_error && c.sent_in === "X-PAYMENT", JSON.stringify(c));
    assert.equal(seen.filter((x) => x.header === "X-PAYMENT").length, N);
    assert.equal(seen.filter((x) => x.header === "PAYMENT-SIGNATURE").length, 0);
  });
  test(`R24 v1 and v2: a route that advertises both gets each value in both headers, one request each, ${name}`, async () => {
    const { result, seen } = await run("", net, "/paid", {}, "both");
    assert.equal(result.pass, true, JSON.stringify(result));
    const d = result.detail as any;
    assert.deepEqual(d.advertised, { v1: true, v2: true });
    assert.equal(d.cases.length, 2 * N);
    for (const h of ["PAYMENT-SIGNATURE", "X-PAYMENT"] as const) {
      assert.equal(d.cases.filter((c: any) => c.sent_in === h).length, N);
      assert.equal(seen.filter((x) => x.header === h).length, N);
    }
  });
  test(`R24 v1_header_unchecked: a V1 route that decodes X-PAYMENT without the shape check answers 500 and is caught; the `
    + `original R24, which sent only PAYMENT-SIGNATURE, passes it, ${name}`, async () => {
    const { result } = await run("v1_header_unchecked", net);
    assert.equal(result.pass, false, JSON.stringify(result));
    const d = result.detail as any;
    assert.ok(d.cases.some((c: any) => c.status === 500 && c.sent_in === "X-PAYMENT"), JSON.stringify(d));
    assert.match(String(d.error), /in X-PAYMENT\) got 500/);
    assert.equal((await run("v1_header_unchecked", net, "/paid", ORIGINAL)).result.pass, true, "PAYMENT-SIGNATURE alone misses it");
  });
}

test("R24 control after the batch: a server that stops answering the unpaid request with 402 after the batch is caught", async () => {
  const double = await startDouble(0);
  const s = await startHeaderServer(double.url, "", DEVNET);
  let n = 0;
  // a fetch that sees a 503 once the batch is over, as a server that fell over would answer
  const f: typeof fetch = async (input, init) => {
    n += 1;
    return n > 1 + N ? new Response("down", { status: 503 }) : fetch(input, init);
  };
  try {
    const result = r24(await probeMalformedHeader(s.url, double, { fetch: f }));
    assert.equal(result.pass, false, JSON.stringify(result));
    const d = result.detail as any;
    assert.equal(d.cases.filter((c: any) => c.pass).length, N);
    assert.deepEqual(d.control_after, { status: 503 });
    assert.match(String(d.error), /after the batch the unpaid control got 503/);
  } finally { await s.close(); await double.close(); }
});

test("R24 facilitator call: a malformed header that reaches /verify fails its case even with a 402 and a structured error", async () => {
  const calls: { path: string }[] = [];
  const double = await startDouble(0);
  const s = await startHeaderServer(double.url, "", DEVNET);
  // the double's call log, with a /verify recorded during the json_null request, as a server that forwarded it would
  const f: typeof fetch = async (input, init) => {
    const h = new Headers(init?.headers).get("payment-signature");
    if (h === MALFORMED_HEADERS.json_null) calls.push({ path: "/verify" });
    return fetch(input, init);
  };
  try {
    const result = r24(await probeMalformedHeader(s.url, { calls: calls as any }, { fetch: f }));
    assert.equal(result.pass, false, JSON.stringify(result));
    const d = result.detail as any;
    const c = d.cases.find((x: any) => x.header === "json_null");
    assert.ok(c.status === 402 && c.structured_error && c.facilitator_calls === 1 && !c.pass, JSON.stringify(c));
    assert.equal(d.cases.filter((x: any) => !x.pass).length, 1);
    assert.match(String(d.error), /json_null in PAYMENT-SIGNATURE\) reached the facilitator/);
  } finally { await s.close(); await double.close(); }
});

test("R24 no version: an unpaid 402 that advertises no version fails and grades nothing", async () => {
  const f: typeof fetch = async () => new Response("{}", { status: 402 });
  const result = r24(await probeMalformedHeader("http://127.0.0.1:9/paid", { calls: [] }, { fetch: f }));
  assert.equal(result.pass, false, JSON.stringify(result));
  assert.equal((result.detail as any).cases, undefined);
  assert.match(String((result.detail as any).error), /advertises no version/);
});

test("R24 unpaid answer: given the caller's unpaid answer, the probe sends only the values and the control", async () => {
  const double = await startDouble(0);
  const s = await startHeaderServer(double.url, "", DEVNET);
  let sent = 0;
  const f: typeof fetch = async (input, init) => { sent += 1; return fetch(input, init); };
  try {
    const r = await fetch(s.url);
    const unpaid = { status: r.status, paymentRequired: r.headers.get("payment-required"), body: await r.text() };
    const result = r24(await probeMalformedHeader(s.url, double, { fetch: f, unpaid }));
    assert.equal(result.pass, true, JSON.stringify(result));
    assert.equal((result.detail as any).unpaid_requests, 1);
    assert.equal(sent, N + 1, "twelve values and the control, no unpaid GET of its own");
  } finally { await s.close(); await double.close(); }
});

test("R24 status only: given an unpaid 402 status, the probe sends its own unpaid GET to read the advertisement", async () => {
  const double = await startDouble(0);
  const s = await startHeaderServer(double.url, "", DEVNET, 0, "v1");
  try {
    const result = r24(await probeMalformedHeader(s.url, double, { unpaidGetStatus: 402 }));
    assert.equal(result.pass, true, JSON.stringify(result));
    assert.deepEqual((result.detail as any).sent_in, ["X-PAYMENT"]);
    const other = r24(await probeMalformedHeader(s.url, double, { unpaidGetStatus: 200 }));
    assert.equal(other.pass, false);
    assert.equal((other.detail as any).status, 200);
  } finally { await s.close(); await double.close(); }
});
