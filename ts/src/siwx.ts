// Sign-in-with-x, the normative server rules (specs/extensions/sign-in-with-x.md, Message Validation). A wallet that
// has paid for a route may come back with only a SIGN-IN-WITH-X header; the server must validate that message before
// it grants access.
//
//   W1  domain and the uri origin are checked against the server's configured public origin, never against the Host
//       or X-Forwarded-Host header: a message signed for another site, sent with Host (or X-Forwarded-Host) naming
//       that site, is refused
//   W2  a nonce is single-use: the same signed message presented a second time is refused
//   W3  the time window is enforced: issuedAt older than five minutes, issuedAt in the future and expirationTime in
//       the past are each refused
//
// First the probe pays the route once through the facilitator double with a throwaway wallet (Base Sepolia exact; the
// wallet holds nothing and nothing touches a chain), then signs in with a fresh, valid message: that control must be
// let in, or nothing after it means anything. Every message is signed by the same wallet, so a refusal is about the
// rule under test, not about who signed.
import http from "node:http";
import { randomBytes } from "node:crypto";
import { decodePaymentRequiredHeader, encodePaymentSignatureHeader } from "@x402/core/http";
import { BASE_SEPOLIA, type Double } from "./double.js";
import type { Result } from "./probe.js";

export const W1 = "W1 sign-in-with-x domain and uri are checked against the server's configured origin, never the "
  + "Host or X-Forwarded-Host header";
export const W2 = "W2 a sign-in-with-x nonce is single-use: the same signed message is refused the second time";
export const W3 = "W3 the sign-in-with-x time window is enforced: a stale or future issuedAt and a past "
  + "expirationTime are refused";

export interface SiwxOptions { timeoutMs?: number }

/** The host a W1 message is signed for: another site, never the server under test. */
export const FOREIGN_HOST = "siwx-foreign.example";

interface Answer { status: number; body: string }

function request(url: string, headers: Record<string, string>, timeoutMs: number): Promise<Answer> {
  return new Promise((ok) => {
    const u = new URL(url);
    const rq = http.request({ host: u.hostname, port: u.port, path: u.pathname + u.search, method: "GET", headers,
      timeout: timeoutMs }, (rs) => {
      let body = "";
      rs.on("data", (c) => { body += c; });
      rs.on("end", () => ok({ status: rs.statusCode ?? 0, body: body.slice(0, 300) }));
    });
    rq.on("timeout", () => { rq.destroy(); ok({ status: 0, body: "timed out" }); });
    rq.on("error", (e) => ok({ status: 0, body: String(e).slice(0, 200) }));
    rq.end();
  });
}

const served = (a: Answer) => a.status >= 200 && a.status < 300;
const iso = (ms: number) => new Date(ms).toISOString();

/** Runs W1, W2 and W3 against a paid route that declares sign-in-with-x, wired to `double`. */
export async function probeSiwx(url: string, double: Double, opts: SiwxOptions = {}): Promise<Result[]> {
  const t = opts.timeoutMs ?? 15_000;
  const all = (pass: boolean, status: Result["status"], detail: Record<string, unknown>) =>
    [W1, W2, W3].map((check) => ({ check, pass, status, detail }));
  let siwx: any, accounts: any;
  try {
    siwx = await import("@x402/extensions/sign-in-with-x");
    accounts = await import("viem/accounts");
  } catch {
    return all(false, "unsupported", { note: "W1 to W3 need @x402/extensions and viem installed next to the probe" });
  }
  const challenge = async () => {
    const r = await fetch(url, { signal: AbortSignal.timeout(t) }).catch(() => null);
    const h = r?.headers.get("payment-required");
    let pr: any = null;
    try { pr = h ? decodePaymentRequiredHeader(h) : null; } catch { pr = null; }
    const ext: any = pr?.extensions?.["sign-in-with-x"];
    const chain = ext?.supportedChains?.find((c: any) => c.chainId === BASE_SEPOLIA && c.type === "eip191");
    const accepted = pr?.accepts?.find((a: any) => a.scheme === "exact" && a.network === BASE_SEPOLIA);
    return { status: r?.status ?? 0, pr, accepted, info: ext?.info && chain ? { ...ext.info, chainId: chain.chainId,
      type: chain.type } : null };
  };
  const first = await challenge();
  if (first.status !== 402 || !first.accepted || !first.info) {
    return all(false, "unsupported", { unpaid_status: first.status, error: "the route did not answer 402 with an exact "
      + `${BASE_SEPOLIA} offer and a sign-in-with-x declaration for ${BASE_SEPOLIA} (eip191)` });
  }
  const wallet = accounts.privateKeyToAccount(accounts.generatePrivateKey());   // throwaway, holds nothing
  // Pay once, so this wallet has bought the route.
  double.mode = "reference";
  const now = Math.floor(Date.now() / 1000);
  const payment = encodePaymentSignatureHeader({ x402Version: 2, resource: first.pr.resource, accepted: first.accepted,
    payload: { signature: "0x" + randomBytes(65).toString("hex"), authorization: { from: wallet.address,
      to: first.accepted.payTo, value: first.accepted.amount, validAfter: String(now - 60),
      validBefore: String(now + Number(first.accepted.maxTimeoutSeconds ?? 60)),
      nonce: "0x" + randomBytes(32).toString("hex") } } } as any);
  const paid = await request(url, { "PAYMENT-SIGNATURE": payment }, t);
  // A signed message from the server's own challenge, with fields overridden; signed as is, never checked locally.
  const message = async (over: Record<string, unknown> = {}) => {
    const c = await challenge();
    const info = { ...(c.info ?? first.info), ...over };
    const address = siwx.getEVMAddress(wallet);
    const signature = await siwx.signEVMMessage(siwx.createSIWxMessage(info, address), wallet);
    return siwx.encodeSIWxHeader({ ...info, address, signature });
  };
  const signIn = (header: string, extra: Record<string, string> = {}) =>
    request(url, { "SIGN-IN-WITH-X": header, ...extra }, t);
  const control = await signIn(await message());
  if (!served(paid) || !served(control)) {
    return all(false, "fail", { paid_status: paid.status, control_status: control.status, error: "the control failed: "
      + "a wallet that paid for the route and signs a fresh, valid message is not let in, so W1 to W3 prove nothing" });
  }
  const base = { paid_status: paid.status, control_status: control.status };
  const out: Result[] = [];

  // W1: a message signed for another site, presented with Host or X-Forwarded-Host naming that site.
  const path = new URL(url).pathname;
  const foreign = { domain: FOREIGN_HOST, uri: `http://${FOREIGN_HOST}${path}` };
  const viaHost = await signIn(await message(foreign), { host: FOREIGN_HOST });
  const viaForwarded = await signIn(await message(foreign), { "x-forwarded-host": FOREIGN_HOST,
    "x-forwarded-proto": "http" });
  const w1 = !served(viaHost) && !served(viaForwarded);
  out.push({ check: W1, pass: w1, status: w1 ? "pass" : "fail", detail: { ...base, foreign_host: FOREIGN_HOST,
    host_header: viaHost.status, x_forwarded_host: viaForwarded.status,
    ...(w1 ? {} : { error: "a message signed for another site was accepted because a request header named that site" }) } });

  // W2: the same signed message twice.
  const once = await message();
  const firstUse = await signIn(once);
  const secondUse = await signIn(once);
  const w2ok = served(firstUse) && !served(secondUse);
  out.push({ check: W2, pass: w2ok, status: w2ok ? "pass" : "fail", detail: { ...base, first_use: firstUse.status,
    second_use: secondUse.status, ...(w2ok ? {} : { error: served(firstUse)
      ? "the same signed message, nonce and all, was accepted a second time"
      : "a fresh, valid message was not accepted on first use" }) } });

  // W3: outside the time window. Each message is otherwise valid.
  const ms = Date.now();
  const cases: Record<string, Record<string, unknown>> = {
    issued_at_too_old: { issuedAt: iso(ms - 10 * 60_000), expirationTime: iso(ms + 5 * 60_000) },
    issued_at_in_future: { issuedAt: iso(ms + 5 * 60_000), expirationTime: iso(ms + 10 * 60_000) },
    expired: { issuedAt: iso(ms - 2 * 60_000), expirationTime: iso(ms - 60_000) },
  };
  const w3: Record<string, number> = {};
  for (const [name, over] of Object.entries(cases)) w3[name] = (await signIn(await message(over))).status;
  const accepted3 = Object.entries(w3).filter(([, s]) => s >= 200 && s < 300).map(([k]) => k);
  const w3ok = accepted3.length === 0;
  out.push({ check: W3, pass: w3ok, status: w3ok ? "pass" : "fail", detail: { ...base, cases: w3,
    ...(w3ok ? {} : { error: `accepted outside the time window: ${accepted3.join(", ")}` }) } });
  return out;
}
