// R23, a client abort during settle is recoverable. The probe pays a route, waits until the server's /settle is in
// flight at the facilitator double, and then drops its connection, as a client does when it is killed, loses its
// network or gives up. The double holds /settle for `settleDelayMs`, so the disconnect always lands while settlement
// is in flight; the double then answers it.
//
//   R23  either the payment was not settled (nothing is charged), or it was settled once and resending the same
//        signed payment returns the settled result (the content or a settlement reference naming that transaction)
//        with no second charge
import http from "node:http";
import { decodePaymentRequiredHeader, decodePaymentResponseHeader, encodePaymentSignatureHeader } from "@x402/core/http";
import type { Double } from "./double.js";
import type { Result } from "./probe.js";
import { freshPayload, newPaymentId, PAYMENT_IDENTIFIER } from "./retry.js";

export interface AbortOptions {
  /** Pay on this network when the route offers several. */
  network?: string;
  /** How long the double holds /settle after the client has gone (default 1500 ms). */
  settleDelayMs?: number;
  /** How long to wait for the server to call /settle before giving up (default 10 000 ms). */
  settleStartMs?: number;
}

const CHECK = "R23 a client that disconnects while /settle is in flight is not charged, or gets the settled result "
  + "when it resends the same payment, with no second charge";
const res = (pass: boolean, detail: unknown): Result => ({ check: CHECK, pass, status: pass ? "pass" : "fail", detail });
const served = (s: number) => s >= 200 && s < 300;
const sleep = (ms: number) => new Promise((ok) => setTimeout(ok, ms));
const settleCalls = (double: Double) => double.calls.filter((c) => c.path === "/settle").length;

/** Sends the paid request and destroys the connection as soon as the double has received a new /settle call. */
function payAndDisconnect(url: string, sig: string, double: Double, waitMs: number):
    Promise<{ disconnected: boolean; status: number | null }> {
  const before = settleCalls(double);
  return new Promise((done) => {
    let finished = false;
    const finish = (v: { disconnected: boolean; status: number | null }) => {
      if (finished) return;
      finished = true;
      clearInterval(timer);
      done(v);
    };
    const rq = http.request(url, { method: "GET", headers: { "PAYMENT-SIGNATURE": sig } }, (rs) => {
      rs.resume();
      // The server answered before its /settle was seen: there was nothing in flight to abort.
      finish({ disconnected: false, status: rs.statusCode ?? null });
    });
    rq.on("error", () => finish({ disconnected: true, status: null }));
    const end = Date.now() + waitMs;
    const timer = setInterval(() => {
      if (settleCalls(double) > before) {
        rq.destroy();
        finish({ disconnected: true, status: null });
      } else if (Date.now() > end) {
        rq.destroy();
        finish({ disconnected: false, status: null });
      }
    }, 5);
    rq.end();
  });
}

async function resend(url: string, sig: string) {
  try {
    const r = await fetch(url, { headers: { "PAYMENT-SIGNATURE": sig }, signal: AbortSignal.timeout(15_000) });
    const body = await r.text();
    let ref: string | null = null;
    const pr = r.headers.get("payment-response");
    if (pr) { try { ref = String((decodePaymentResponseHeader(pr) as any)?.transaction ?? "") || null; } catch { ref = null; } }
    return { status: r.status, body: body.slice(0, 300), ref };
  } catch (e) {
    return { status: 0, body: String(e), ref: null as string | null };
  }
}

export async function probeAbort(url: string, double: Double, opts: AbortOptions = {}): Promise<Result[]> {
  const delay = opts.settleDelayMs ?? 1500;
  const r = await fetch(url, { signal: AbortSignal.timeout(15_000) }).catch(() => null);
  const h = r?.headers.get("payment-required");
  let required: any = null;
  try { required = h ? decodePaymentRequiredHeader(h) : null; } catch { required = null; }
  const accepted = required?.accepts?.find((a: any) => a.scheme === "exact" && (!opts.network || a.network === opts.network));
  if (r?.status !== 402 || !accepted) {
    return [res(false, { status: r?.status ?? null, network: opts.network ?? null,
      error: "the route did not answer 402 with an exact offer the probe can pay" })];
  }
  // The same signed payment is resent, so the payment-identifier id, when the route declares it, rides along.
  const id = newPaymentId();
  const extensions = required.extensions?.[PAYMENT_IDENTIFIER]
    ? { ...required.extensions, [PAYMENT_IDENTIFIER]: { ...required.extensions[PAYMENT_IDENTIFIER], info: { required: false, id } } }
    : required.extensions;
  const sig = encodePaymentSignatureHeader({ x402Version: 2, resource: required.resource, accepted,
    payload: freshPayload(accepted), ...(extensions ? { extensions } : {}) } as any);

  double.mode = "reference";
  double.settleDelayMs = delay;
  const before = { successes: double.successes.length, answers: double.settleAnswers };
  let aborted: { disconnected: boolean; status: number | null };
  try {
    aborted = await payAndDisconnect(url, sig, double, opts.settleStartMs ?? 10_000);
    // Let the in-flight /settle answer and the server's after-settle work run before looking.
    if (aborted.disconnected) {
      const end = Date.now() + delay + 3000;
      while (double.settleAnswers <= before.answers && Date.now() < end) await sleep(25);
      await sleep(250);
    }
  } finally {
    double.settleDelayMs = 0;
  }
  if (!aborted.disconnected) {
    return [res(false, { network: accepted.network, first_status: aborted.status,
      error: aborted.status === null ? "the server never called /settle for a well-formed payment"
        : "the server answered before /settle was called, so there was no settlement in flight to abort" })];
  }
  const firstTx = double.successes.slice(before.successes)[0] ?? null;
  const settledOnAbort = double.successes.length - before.successes;
  if (settledOnAbort === 0) {
    return [res(true, { network: accepted.network, settled_on_abort: 0, successful_settles: 0 })];
  }
  const retry = await resend(url, sig);
  const charges = double.successes.length - before.successes;
  const result = served(retry.status) || (!!firstTx && (retry.ref === firstTx || retry.body.includes(firstTx)));
  return [res(charges === 1 && result, {
    network: accepted.network, settled_on_abort: settledOnAbort, first_transaction: firstTx,
    resend: { status: retry.status, settlement_ref: retry.ref }, successful_settles: charges,
    ...(charges > 1 ? { error: "the payment was settled again after the client came back" } : {}),
    ...(charges === 1 && !result ? { error: "settled once, but resending the same payment did not return the settled result" } : {}),
  })];
}
