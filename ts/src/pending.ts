// R18, a settlement that is pending, late or unanswered. Three things can happen between /settle and the response that
// leave the server unsure whether the payment went through: the facilitator answers settlement_pending; it keeps
// answering pending until the server's deadline; or it settles but the answer never arrives. In each the outcome must
// be explicit and reconcilable (V2 9: settlement_pending carries the transaction so the caller can reconcile): the
// content is served once, after the payment is final, or the request is refused with the payment surfaced, and it is
// never served while the payment is not final. The client's retries resend the same signed payment, as a client
// that knows it may have paid does.
import { decodePaymentRequiredHeader, decodePaymentResponseHeader, encodePaymentSignatureHeader } from "@x402/core/http";
import { doubleTransaction, type Double } from "./double.js";
import type { Result } from "./probe.js";
import { freshPayload } from "./retry.js";
import { paymentRef } from "./crash.js";

export const R18 = "R18 a pending, late or unanswered settlement ends served once after the payment is final, or refused "
  + "with the payment surfaced, never served before it is final";

export interface PendingOptions {
  network?: string;
  timeoutMs?: number;
  /** How many times the client retries while the facilitator keeps answering pending (default 3). */
  retries?: number;
}

interface Answer { status: number; served: boolean; surfaced: boolean; ref: string | null }

const served = (s: number) => s >= 200 && s < 300;

async function send(url: string, sig: string, refs: string[], t: number): Promise<Answer> {
  try {
    const r = await fetch(url, { headers: { "PAYMENT-SIGNATURE": sig }, signal: AbortSignal.timeout(t) });
    const body = await r.text();
    let ref: string | null = null;
    const pr = r.headers.get("payment-response");
    if (pr) { try { ref = String((decodePaymentResponseHeader(pr) as any)?.transaction ?? "") || null; } catch { ref = null; } }
    let headerText = "";
    r.headers.forEach((v) => { headerText += v + "\n"; });
    const surfaced = refs.some((x) => x && (body.includes(x) || headerText.includes(x)));
    return { status: r.status, served: served(r.status), surfaced, ref };
  } catch (e) {
    return { status: 0, served: false, surfaced: false, ref: `no answer: ${String(e).slice(0, 80)}` };
  }
}

const res = (pass: boolean, status: Result["status"], detail: unknown): Result => ({ check: R18, pass, status, detail });

/** R18 against `url`, a paid route on a server wired to `double`. */
export async function probePending(url: string, double: Double, opts: PendingOptions = {}): Promise<Result[]> {
  const t = opts.timeoutMs ?? 15_000;
  const retries = Math.max(1, opts.retries ?? 3);
  const first = await fetch(url, { signal: AbortSignal.timeout(t) }).catch(() => null);
  await first?.arrayBuffer().catch(() => null);
  const h = first?.headers.get("payment-required");
  let required: any = null;
  try { required = h ? decodePaymentRequiredHeader(h) : null; } catch { required = null; }
  const accepted = required?.accepts?.find((a: any) => a.scheme === "exact" && (!opts.network || a.network === opts.network));
  if (first?.status !== 402 || !accepted) {
    return [res(false, "unsupported", { unpaid_status: first?.status ?? null,
      error: "the route did not answer an unpaid request with 402 and an exact offer, so nothing was graded" })];
  }
  const payment = () => {
    const payload = freshPayload(accepted);
    const sig = encodePaymentSignatureHeader({ x402Version: 2, resource: required.resource, accepted, payload } as any);
    return { sig, refs: [doubleTransaction(payload), paymentRef(payload)].filter(Boolean) };
  };
  const scenarios: Record<string, any> = {};
  const problems: string[] = [];
  const settleCalls = () => double.calls.filter((c) => c.path === "/settle").length;

  // 1. Pending, then success on the retry: not served while pending, served once after, never a second grant.
  {
    const p = payment();
    double.mode = "settle_pending";
    const before = { ok: double.successes.length, calls: settleCalls() };
    const pending = await send(url, p.sig, p.refs, t);
    double.mode = "reference";
    const retry = await send(url, p.sig, p.refs, t);
    const again = await send(url, p.sig, p.refs, t);
    const charged = double.successes.length - before.ok;
    scenarios.pending_then_success = { pending, retry, again, successful_settles: charged, settle_calls: settleCalls() - before.calls };
    if (pending.served) problems.push("the content was served while the settlement was pending");
    else if (!pending.surfaced) problems.push("the pending answer surfaced neither the transaction nor the payment");
    if (!retry.served) problems.push(`the retry after the payment was final was not served (${retry.status})`);
    if (!again.served && !again.surfaced) problems.push("a further retry was refused without surfacing the payment");
    if (charged > 1) problems.push("one payment was settled successfully twice");
  }
  // 2. Pending until the deadline: every retry refused, every answer surfaces the payment.
  {
    const p = payment();
    double.mode = "settle_pending";
    const answers: Answer[] = [];
    for (let i = 0; i < retries; i++) answers.push(await send(url, p.sig, p.refs, t));
    double.mode = "reference";
    scenarios.pending_until_deadline = { answers };
    if (answers.some((a) => a.served)) problems.push("the content was served while the settlement was still pending");
    else if (answers.some((a) => !a.surfaced)) problems.push("an answer while pending surfaced neither the transaction nor the payment");
  }
  // 3. Settled, but the answer never arrived: the server's answer surfaces the payment, and the retries of the same
  //    payment are served at most once (the facilitator reports the duplicate) or refused with the payment surfaced.
  {
    const p = payment();
    double.mode = "reference";
    const before = double.successes.length;
    double.onSettled = async () => {};
    const lost = await send(url, p.sig, p.refs, t);
    double.onSettled = undefined;
    const retry = await send(url, p.sig, p.refs, t);
    const again = await send(url, p.sig, p.refs, t);
    const grants = [lost, retry, again].filter((a) => a.served).length;
    scenarios.late_success = { lost, retry, again, successful_settles: double.successes.length - before, served: grants };
    if (lost.served) problems.push("the content was served for a settlement the server never heard back on");
    else if (!lost.surfaced) problems.push("the unanswered settlement was refused without surfacing the payment");
    if (grants > 1) problems.push("the content was served more than once for one payment");
    for (const a of [retry, again]) if (!a.served && !a.surfaced) { problems.push("a retry after a lost answer was refused without surfacing the payment"); break; }
  }
  double.mode = "reference";
  const pass = problems.length === 0;
  return [res(pass, pass ? "pass" : "fail", { network: accepted.network, ...scenarios,
    ...(problems.length ? { error: [...new Set(problems)].join("; ") } : {}) })];
}
