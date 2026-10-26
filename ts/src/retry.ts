// R20, retry double-pay, on a real resource server. The client times out before /settle answers and retries the same
// request. The facilitator double holds /settle for `settleDelayMs`, longer than the client waits, so the first attempt
// is always abandoned while its settlement is in flight; the double then settles it, and the retry arrives after.
//
//   R20 control  the route answers 402 with an exact offer the probe can pay
//   R20a         (server) the retry carries a fresh payment and the same client idempotency key: the payment-identifier
//                id, with an Idempotency-Key header carrying the same value. It is not charged again: the double sees
//                one successful /settle for the request, and the retry gets the earlier result or a settlement
//                reference naming the first transaction
//   R20b         (server) the retry resends the same signed payment (same nonce or transaction) with the same key: the
//                double refuses a second settle of it as a duplicate, and the retry still gets the original result
//   R20c         (server) the same exchange as R20a, graded for safety: the re-signed retry under the same
//                payment-identifier id is never settled. It passes when the server refuses the retry with 409 (or
//                another 4xx naming the id) or returns the original result, with one successful /settle in all. R20a
//                stays strict: a 409 refusal loses the result the client paid for, so it fails R20a and passes R20c
//   R20b client  checkClientRetry: a client's own timeout-and-retry is watched through a recording proxy. It passes when
//                the retry reuses the signed payment or carries the same payment-identifier id, and is flagged when it
//                re-signs a fresh payment with no key
import http from "node:http";
import type { AddressInfo } from "node:net";
import { randomBytes } from "node:crypto";
import { decodePaymentRequiredHeader, decodePaymentResponseHeader, decodePaymentSignatureHeader,
  encodePaymentSignatureHeader } from "@x402/core/http";
import type { Double } from "./double.js";
import type { Result } from "./probe.js";

export const PAYMENT_IDENTIFIER = "payment-identifier";

export interface RetryOptions {
  /** Pay on this network when the route offers several. */
  network?: string;
  /** How long the client waits for the first attempt (default 400 ms). */
  clientTimeoutMs?: number;
  /** How long the double holds /settle for the first attempt (default 1500 ms; must exceed clientTimeoutMs). */
  settleDelayMs?: number;
}

const res = (check: string, pass: boolean, detail: unknown): Result =>
  ({ check, pass, status: pass ? "pass" : "fail", detail });
const served = (s: number) => s >= 200 && s < 300;
const sleep = (ms: number) => new Promise((ok) => setTimeout(ok, ms));

/** A well-formed exact payload for `accepted` with a fresh nonce (EVM) or transaction (Solana). The double accepts
 * any well-formed payload, so nothing here holds or signs value. */
export function freshPayload(accepted: any): Record<string, unknown> {
  if (String(accepted.network).startsWith("eip155:")) {
    const now = Math.floor(Date.now() / 1000);
    return { signature: "0x" + randomBytes(65).toString("hex"),
      authorization: { from: "0x" + "ab".repeat(20), to: accepted.payTo, value: accepted.amount,
        validAfter: String(now - 60), validBefore: String(now + Number(accepted.maxTimeoutSeconds ?? 60)),
        nonce: "0x" + randomBytes(32).toString("hex") } };
  }
  return { transaction: randomBytes(160).toString("base64") };
}

export const newPaymentId = () => "pay_" + randomBytes(16).toString("hex");

async function send(url: string, headers: Record<string, string>, timeoutMs: number) {
  try {
    const r = await fetch(url, { headers, signal: AbortSignal.timeout(timeoutMs) });
    const body = await r.text();
    let ref: string | null = null;
    const pr = r.headers.get("payment-response");
    if (pr) { try { ref = String((decodePaymentResponseHeader(pr) as any)?.transaction ?? "") || null; } catch { ref = null; } }
    // the error a PAYMENT-REQUIRED carries, which is where a 402 refusal would name the id
    let required = "";
    const h = r.headers.get("payment-required");
    if (h) { try { required = String((decodePaymentRequiredHeader(h) as any)?.error ?? ""); } catch { required = ""; } }
    return { status: r.status, timedOut: false, body: body.slice(0, 300), ref, required };
  } catch (e) {
    const timedOut = (e as Error)?.name === "TimeoutError" || (e as Error)?.name === "AbortError";
    return { status: 0, timedOut, body: timedOut ? "" : String(e), ref: null as string | null, required: "" };
  }
}

/** Waits until the double has answered `n` /settle calls in total, or `ms` passes. */
async function settled(double: Double, n: number, ms: number) {
  const end = Date.now() + ms;
  while (double.settleAnswers < n && Date.now() < end) await sleep(25);
  await sleep(250);   // give the server's after-settle hook time to record the result
}

export async function probeRetry(url: string, double: Double, opts: RetryOptions = {}): Promise<Result[]> {
  const out: Result[] = [];
  const wait = opts.clientTimeoutMs ?? 400;
  const delay = Math.max(opts.settleDelayMs ?? 1500, wait + 500);
  const r = await fetch(url, { signal: AbortSignal.timeout(15_000) }).catch(() => null);
  const h = r?.headers.get("payment-required");
  let required: any = null;
  try { required = h ? decodePaymentRequiredHeader(h) : null; } catch { required = null; }
  const accepted = required?.accepts?.find((a: any) => a.scheme === "exact" && (!opts.network || a.network === opts.network));
  const ctl = "R20 control: the route answers 402 with an exact offer the probe can pay";
  if (r?.status !== 402 || !accepted) {
    out.push(res(ctl, false, { status: r?.status ?? null, network: opts.network ?? null }));
    return out;
  }
  out.push(res(ctl, true, { network: accepted.network, declares_payment_identifier: !!required.extensions?.[PAYMENT_IDENTIFIER] }));
  const header = (id: string) => encodePaymentSignatureHeader({ x402Version: 2, resource: required.resource, accepted,
    payload: freshPayload(accepted),
    extensions: { ...(required.extensions ?? {}), [PAYMENT_IDENTIFIER]: { ...(required.extensions?.[PAYMENT_IDENTIFIER] ?? {}),
      info: { required: false, id } } } } as any);
  const firstAttempt = async (id: string, sig: string) => {
    double.mode = "reference";
    double.settleDelayMs = delay;
    const before = { successes: double.successes.length, answers: double.settleAnswers };
    const first = await send(url, { "PAYMENT-SIGNATURE": sig, "Idempotency-Key": id }, wait);
    // The first settle may never have been asked for (the server refused before /settle); wait only for one that was.
    const asked = double.calls.filter((c) => c.path === "/settle").length > before.answers;
    if (asked) await settled(double, before.answers + 1, delay + 3000);
    double.settleDelayMs = 0;
    return { before, first, firstTx: double.successes.slice(before.successes)[0] ?? null };
  };

  // R20a: same key, fresh payment. R20c grades the same exchange for safety only.
  let r20c: Result;
  {
    const id = newPaymentId();
    const { before, first, firstTx } = await firstAttempt(id, header(id));
    const retry = await send(url, { "PAYMENT-SIGNATURE": header(id), "Idempotency-Key": id }, 15_000);
    const charges = double.successes.length - before.successes;
    const earlier = served(retry.status) || (!!firstTx && (retry.ref === firstTx || retry.body.includes(firstTx)));
    out.push(res("R20a a retry with a fresh payment and the same idempotency key is not charged again and gets the "
      + "earlier result", first.timedOut && charges === 1 && earlier,
      { first: { timed_out: first.timedOut, status: first.status }, retry: { status: retry.status, settlement_ref: retry.ref },
        successful_settles: charges, first_transaction: firstTx,
        ...(first.timedOut ? {} : { error: "the first attempt answered before the client gave up; nothing was retried" }),
        ...(charges > 1 ? { error: "the request was paid twice" } : {}),
        ...(charges === 1 && !earlier ? { error: "not charged twice, but the retry lost the earlier result" } : {}) }));
    const namesId = retry.body.includes(id) || retry.required.includes(id);
    const refused = retry.status === 409 || (retry.status >= 400 && retry.status < 500 && namesId);
    r20c = res("R20c a retry re-signed under the same payment-identifier id is refused with 409 (or a 4xx naming the id) "
      + "or gets the original result, and is never settled", first.timedOut && charges === 1 && (earlier || refused),
      { first: { timed_out: first.timedOut, status: first.status },
        retry: { status: retry.status, settlement_ref: retry.ref, names_id: namesId }, payment_identifier: id,
        successful_settles: charges, outcome: earlier ? "original result" : refused ? "refused" : "neither",
        ...(first.timedOut ? {} : { error: "the first attempt answered before the client gave up; nothing was retried" }),
        ...(charges > 1 ? { error: "the re-signed retry was settled: the request was paid twice" } : {}),
        ...(charges === 1 && !earlier && !refused ? { error: `the retry got ${retry.status || "no answer"}: neither the `
          + "original result nor a 409 or a 4xx naming the id" } : {}) });
  }
  // R20b: same key, same signed payment.
  {
    const id = newPaymentId();
    const sig = header(id);
    const { before, first, firstTx } = await firstAttempt(id, sig);
    const settlesBefore = double.calls.filter((c) => c.path === "/settle").length;
    const retry = await send(url, { "PAYMENT-SIGNATURE": sig, "Idempotency-Key": id }, 15_000);
    const charges = double.successes.length - before.successes;
    const resettled = double.calls.filter((c) => c.path === "/settle").length - settlesBefore;
    const original = served(retry.status) || (!!firstTx && (retry.ref === firstTx || retry.body.includes(firstTx)));
    out.push(res("R20b a retry resending the same signed payment is not settled twice and gets the original result",
      first.timedOut && charges === 1 && original,
      { first: { timed_out: first.timedOut, status: first.status }, retry: { status: retry.status, settlement_ref: retry.ref },
        successful_settles: charges, settle_calls_on_retry: resettled, first_transaction: firstTx,
        ...(charges === 1 && !original ? { error: "not settled twice, but the retry lost the original result" } : {}) }));
  }
  out.push(r20c);
  return out;
}

/** A client under test: it fetches `url` with its own timeout-and-retry policy and returns the final response. */
export type RetryingClient = (url: string) => Promise<Response>;

/** R20b, client side. Puts a recording proxy in front of `url` (a paid route behind `double`), holds /settle longer
 * than the client waits, and reads which payment the client's retry carried. */
export async function checkClientRetry(client: RetryingClient, url: string, double: Double,
    opts: { settleDelayMs?: number } = {}): Promise<Result> {
  const target = new URL(url);
  const seen: { sig: string; id: string | null; nonce: string }[] = [];
  const slow = opts.settleDelayMs ?? 4000;
  const answersBefore = double.settleAnswers;
  const proxy = http.createServer(async (rq, rs) => {
    const sig = rq.headers["payment-signature"];
    const headers: Record<string, string> = {};
    for (const [k, v] of Object.entries(rq.headers)) if (typeof v === "string" && k !== "host") headers[k] = v;
    if (typeof sig === "string") {
      let p: any = null;
      try { p = decodePaymentSignatureHeader(sig); } catch { p = null; }
      seen.push({ sig, id: p?.extensions?.[PAYMENT_IDENTIFIER]?.info?.id ?? null,
        nonce: String(p?.payload?.authorization?.nonce ?? p?.payload?.transaction ?? "") });
      // A retry is held until the first attempt's settlement has been answered, so it arrives after it, as in R20a.
      if (seen.length >= 2) { double.settleDelayMs = 0; await settled(double, answersBefore + 1, slow + 3000); }
    }
    try {
      const up = await fetch(new URL(rq.url ?? "/", target), { headers });
      const out: Record<string, string> = {};
      up.headers.forEach((v, k) => { if (k !== "content-length" && k !== "transfer-encoding") out[k] = v; });
      rs.writeHead(up.status, out);
      rs.end(Buffer.from(await up.arrayBuffer()));
    } catch (e) {
      if (!rs.headersSent) rs.writeHead(502);
      rs.end(String(e));
    }
  });
  await new Promise<void>((ok) => proxy.listen(0, "127.0.0.1", ok));
  const front = `http://127.0.0.1:${(proxy.address() as AddressInfo).port}${target.pathname}${target.search}`;
  // One unpaid request first, so a server that syncs with its facilitator on first use has done so before the
  // client's clock starts: the client's timeout must land on the paid attempt, not on start-up.
  await fetch(url, { signal: AbortSignal.timeout(15_000) }).then((r) => r.arrayBuffer()).catch(() => null);
  double.mode = "reference";
  double.settleDelayMs = slow;
  const before = double.successes.length;
  let final: Response | { status: number } = { status: 0 };
  let error: string | undefined;
  try {
    final = await client(front);
    await (final as Response).text().catch(() => "");
  } catch (e) { error = String(e); }
  double.settleDelayMs = 0;
  await new Promise<void>((ok) => { proxy.closeAllConnections(); proxy.close(() => ok()); });
  const charges = double.successes.length - before;
  const [a, b] = seen;
  const reused = !!a && !!b && a.sig === b.sig;
  const keyed = !!a && !!b && !!a.id && a.id === b.id;
  const pass = seen.length >= 2 && (reused || keyed) && charges <= 1 && served(final.status);
  return res("R20b client: after a timeout the retry reuses the signed payment or the same payment-identifier id",
    pass, { paid_attempts: seen.length, reused_payment: reused, same_payment_identifier: keyed,
      fresh_nonce: !!a && !!b && a.nonce !== b.nonce, successful_settles: charges, final_status: final.status,
      ...(seen.length < 2 ? { error: error ?? "the client did not retry after timing out" } : {}),
      ...(seen.length >= 2 && !reused && !keyed ? { error: "the client re-signed a fresh payment with no idempotency key" } : {}) });
}
