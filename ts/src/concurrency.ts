// R12 and R13, one payment is at most one grant under concurrency. The client names one logical payment with a
// payment-identifier id (and an Idempotency-Key header with the same value) and sends it with a fresh signed payment
// each time, as a client that retries in parallel, or behind a load balancer, does.
//
//   R12  N parallel requests to one server carry the same id. The double settles at most one payment for them, at
//        least one is served, and every one that is served names that settlement
//   R13  the same request goes to two replicas of the service: to the first, then to the second, then to both at once.
//        The double settles one payment in all, and every served answer names it. A per-process record lets the
//        second replica settle again
import { decodePaymentRequiredHeader, decodePaymentResponseHeader, encodePaymentSignatureHeader } from "@x402/core/http";
import type { Double } from "./double.js";
import type { Result } from "./probe.js";
import { freshPayload, newPaymentId, PAYMENT_IDENTIFIER } from "./retry.js";

export const R12 = "R12 parallel requests that carry the same payment identifier are charged at most once, and every "
  + "one that is served names that settlement";
export const R13 = "R13 the same payment identifier sent to two replicas is charged at most once, and every answer "
  + "that is served names that settlement";

export interface ConcurrencyOptions {
  /** Pay on this network when the route offers several. */
  network?: string;
  /** How many parallel requests R12 sends (default 8). */
  parallel?: number;
  /** How long the double holds each /settle, so the requests overlap while one is in flight (default 300 ms). */
  settleDelayMs?: number;
}

const res = (check: string, pass: boolean, detail: unknown): Result =>
  ({ check, pass, status: pass ? "pass" : "fail", detail });
const served = (s: number) => s >= 200 && s < 300;

async function offer(url: string, network?: string) {
  const r = await fetch(url, { signal: AbortSignal.timeout(15_000) }).catch(() => null);
  await r?.arrayBuffer().catch(() => null);
  const h = r?.headers.get("payment-required");
  let required: any = null;
  try { required = h ? decodePaymentRequiredHeader(h) : null; } catch { required = null; }
  const accepted = required?.accepts?.find((a: any) => a.scheme === "exact" && (!network || a.network === network));
  return r?.status === 402 && accepted ? { required, accepted } : { status: r?.status ?? null };
}

function header(required: any, accepted: any, id: string): string {
  return encodePaymentSignatureHeader({ x402Version: 2, resource: required.resource, accepted,
    payload: freshPayload(accepted),
    extensions: { ...(required.extensions ?? {}), [PAYMENT_IDENTIFIER]: { ...(required.extensions?.[PAYMENT_IDENTIFIER] ?? {}),
      info: { required: false, id } } } } as any);
}

async function send(url: string, sig: string, id: string) {
  try {
    const r = await fetch(url, { headers: { "PAYMENT-SIGNATURE": sig, "Idempotency-Key": id },
      signal: AbortSignal.timeout(15_000) });
    await r.arrayBuffer();
    let ref: string | null = null;
    const pr = r.headers.get("payment-response");
    if (pr) { try { ref = String((decodePaymentResponseHeader(pr) as any)?.transaction ?? "") || null; } catch { ref = null; } }
    return { status: r.status, ref };
  } catch (e) {
    return { status: 0, ref: null as string | null, error: String(e).slice(0, 160) };
  }
}

/** Grades the answers to one payment identifier against the settlements the double made for it. */
function grade(check: string, answers: { status: number; ref: string | null }[], txs: string[], extra: object): Result {
  const grants = answers.filter((a) => served(a.status));
  const stray = grants.filter((a) => a.ref !== txs[0]);
  const pass = txs.length === 1 && grants.length >= 1 && stray.length === 0;
  const error = txs.length > 1 ? `one payment identifier was charged ${txs.length} times`
    : txs.length === 0 ? "nothing was settled, so nothing was graded"
      : grants.length === 0 ? "the payment was settled but no request was served"
        : stray.length ? "a served answer does not name the one settlement" : undefined;
  return res(check, pass, { ...extra, successful_settles: txs.length, served: grants.length,
    statuses: answers.map((a) => a.status), ...(error ? { error } : {}) });
}

/** R12: `parallel` requests with one payment identifier, all at once, to `url`. */
export async function probeParallel(url: string, double: Double, opts: ConcurrencyOptions = {}): Promise<Result[]> {
  const o = await offer(url, opts.network);
  if (!("accepted" in o)) {
    return [res(R12, false, { status: o.status, error: "the route did not answer 402 with an exact offer, so nothing was graded" })];
  }
  const n = Math.max(2, opts.parallel ?? 8);
  const id = newPaymentId();
  double.mode = "reference";
  double.settleDelayMs = opts.settleDelayMs ?? 300;
  const before = double.successes.length;
  try {
    const answers = await Promise.all(Array.from({ length: n }, () => send(url, header(o.required, o.accepted, id), id)));
    return [grade(R12, answers, double.successes.slice(before), { network: o.accepted.network, parallel: n })];
  } finally { double.settleDelayMs = 0; }
}

/** R13: one payment identifier sent to replica `a`, then to replica `b`, then to both at once. */
export async function probeReplicas(a: string, b: string, double: Double, opts: ConcurrencyOptions = {}): Promise<Result[]> {
  const oa = await offer(a, opts.network);
  const ob = await offer(b, opts.network);
  if (!("accepted" in oa) || !("accepted" in ob)) {
    return [res(R13, false, { status: [oa, ob].map((x) => ("accepted" in x ? 402 : x.status)),
      error: "a replica did not answer 402 with an exact offer, so nothing was graded" })];
  }
  const id = newPaymentId();
  double.mode = "reference";
  double.settleDelayMs = opts.settleDelayMs ?? 300;
  const before = double.successes.length;
  try {
    const first = await send(a, header(oa.required, oa.accepted, id), id);
    const other = await send(b, header(ob.required, ob.accepted, id), id);
    const both = await Promise.all([send(a, header(oa.required, oa.accepted, id), id),
      send(b, header(ob.required, ob.accepted, id), id)]);
    return [grade(R13, [first, other, ...both], double.successes.slice(before),
      { network: oa.accepted.network, sequence: ["replica a", "replica b", "both at once"] })];
  } finally { double.settleDelayMs = 0; }
}
