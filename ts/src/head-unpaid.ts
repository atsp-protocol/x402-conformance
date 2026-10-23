// R16a: an unpaid HEAD on a paid route gets the same 402 as GET. The paywall must cover every method that reaches the
// protected handler; a router that serves HEAD from the GET handler while the paywall matches only GET hands out the
// handler's status and headers, and runs its side effects, for free. The probe sends an unpaid GET and an unpaid HEAD
// and passes when both are 402 and the HEAD carries a PAYMENT-REQUIRED header that decodes to an offer.
import { decodePaymentRequiredHeader } from "@x402/core/http";
import type { Result } from "./probe.js";

export const R16A = "R16a an unpaid HEAD on a paid route is answered 402 with PAYMENT-REQUIRED, like GET";

export async function probeUnpaidHead(url: string, opts: { timeoutMs?: number } = {}): Promise<Result[]> {
  const t = opts.timeoutMs ?? 15_000;
  const get = await fetch(url, { redirect: "manual", signal: AbortSignal.timeout(t) }).catch(() => null);
  if (get?.status !== 402) {
    return [{ check: R16A, pass: false, status: "unsupported",
      detail: { get_status: get?.status ?? null, error: "the route did not answer an unpaid GET with 402" } }];
  }
  const head = await fetch(url, { method: "HEAD", redirect: "manual", signal: AbortSignal.timeout(t) }).catch(() => null);
  const h = head?.headers.get("payment-required");
  let offers = 0;
  try { offers = h ? ((decodePaymentRequiredHeader(h) as any)?.accepts?.length ?? 0) : 0; } catch { offers = 0; }
  const pass = head?.status === 402 && offers > 0;
  return [{ check: R16A, pass, status: pass ? "pass" : "fail",
    detail: { get_status: get.status, head_status: head?.status ?? null, head_payment_required: !!h, head_offers: offers,
      ...(head && head.status >= 200 && head.status < 300 ? { error: "an unpaid HEAD reached the protected handler" }
        : !pass ? { error: "the unpaid HEAD was not answered 402 with a PAYMENT-REQUIRED offer" } : {}) } }];
}
