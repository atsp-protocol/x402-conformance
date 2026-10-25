// R16a: an unpaid HEAD on a paid route never reaches the protected handler. The paywall must cover every method that
// reaches the handler; a router that serves HEAD from the GET handler while the paywall matches only GET hands out the
// handler's status and headers, and runs its side effects, for free. The probe sends an unpaid GET and an unpaid HEAD.
// It passes when the HEAD is answered 402 with a PAYMENT-REQUIRED header that decodes to an offer, like GET, or when
// the server refuses HEAD outright with 405 Method Not Allowed and no PAYMENT-RESPONSE: a 405 is decided by the router
// before any handler runs (RFC 9110 15.5.6), so it meets the property too, and no x402 clause requires HEAD to be priced.
import { decodePaymentRequiredHeader } from "@x402/core/http";
import type { Result } from "./probe.js";
import { isLoopback, RequestBudgetExceeded } from "./pace.js";

/** HEAD is not a GET: off loopback the probe sends it only with the operator's written permission
 * (`--operator-permission REF`, the convention of the devnet runner), and skips R16a without it. */
export function headNeedsPermission(url: string, permission?: string): boolean {
  return !isLoopback(url) && !(permission ?? "").trim();
}

const keepBudget = (e: unknown): null => { if (e instanceof RequestBudgetExceeded) throw e; return null; };

export const R16A = "R16a an unpaid HEAD on a paid route never reaches the handler: 402 with PAYMENT-REQUIRED like GET, "
  + "or refused with 405";

export interface UnpaidHeadOptions {
  timeoutMs?: number;
  /** The fetch to send with, e.g. a paced one from createPacedFetch for a live target. Defaults to global fetch. */
  fetch?: typeof fetch;
  /** The status of an unpaid GET the caller already sent to this URL; the probe then sends only the HEAD. */
  unpaidGetStatus?: number;
}

export async function probeUnpaidHead(url: string, opts: UnpaidHeadOptions = {}): Promise<Result[]> {
  const t = opts.timeoutMs ?? 15_000;
  const f = opts.fetch ?? fetch;
  let getStatus = opts.unpaidGetStatus;
  if (getStatus === undefined) {
    const get = await f(url, { redirect: "manual", signal: AbortSignal.timeout(t) }).catch(keepBudget);
    await get?.arrayBuffer().catch(() => null);
    getStatus = get?.status;
  }
  if (getStatus !== 402) {
    return [{ check: R16A, pass: false, status: "unsupported",
      detail: { get_status: getStatus ?? null, error: "the route did not answer an unpaid GET with 402" } }];
  }
  const head = await f(url, { method: "HEAD", redirect: "manual", signal: AbortSignal.timeout(t) }).catch(keepBudget);
  const h = head?.headers.get("payment-required");
  let offers = 0;
  try { offers = h ? ((decodePaymentRequiredHeader(h) as any)?.accepts?.length ?? 0) : 0; } catch { offers = 0; }
  const paymentResponse = !!head?.headers.get("payment-response");
  const refused = head?.status === 405 && !paymentResponse;
  const pass = (head?.status === 402 && offers > 0) || refused;
  return [{ check: R16A, pass, status: pass ? "pass" : "fail",
    detail: { get_status: getStatus, head_status: head?.status ?? null, head_payment_required: !!h, head_offers: offers,
      ...(head?.status === 405 ? { allow: head.headers.get("allow"), head_payment_response: paymentResponse } : {}),
      ...(refused ? { note: "HEAD is refused with 405 before any handler runs, so it is never served for free" } : {}),
      ...(head && head.status >= 200 && head.status < 300 ? { error: "an unpaid HEAD reached the protected handler" }
        : !pass ? { error: "the unpaid HEAD was neither answered 402 with a PAYMENT-REQUIRED offer nor refused with 405" }
          : {}) } }];
}
