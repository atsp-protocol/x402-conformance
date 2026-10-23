// R16: a HEAD request carrying a payment is never settled. A HEAD response carries no content (RFC 9110 9.3.2), so a
// server that settles one charges the client for nothing. The probe reads the route's offer with an unpaid GET, sends
// HEAD with a fresh well-formed payment the facilitator double accepts, and counts the /settle calls it causes. It
// passes when the HEAD is refused (not 2xx; a 402 asking for GET is the expected answer), with zero /settle calls and
// no PAYMENT-RESPONSE.
import { decodePaymentRequiredHeader, encodePaymentSignatureHeader } from "@x402/core/http";
import type { Double } from "./double.js";
import type { Result } from "./probe.js";
import { freshPayload } from "./retry.js";

export const R16 = "R16 a HEAD request carrying a payment is refused and never settled";

export async function probeHead(url: string, double: Double, opts: { network?: string; timeoutMs?: number } = {}): Promise<Result[]> {
  const t = opts.timeoutMs ?? 15_000;
  const r = await fetch(url, { signal: AbortSignal.timeout(t) }).catch(() => null);
  const h = r?.headers.get("payment-required");
  let required: any = null;
  try { required = h ? decodePaymentRequiredHeader(h) : null; } catch { required = null; }
  const accepted = required?.accepts?.find((a: any) => a.scheme === "exact" && (!opts.network || a.network === opts.network));
  if (r?.status !== 402 || !accepted) {
    return [{ check: R16, pass: false, status: "unsupported",
      detail: { get_status: r?.status ?? null, error: "the route did not answer GET with 402 and an exact offer the probe can pay" } }];
  }
  double.mode = "reference";
  const before = { calls: double.calls.filter((c) => c.path === "/settle").length, ok: double.successes.length };
  const sig = encodePaymentSignatureHeader({ x402Version: 2, resource: required.resource, accepted,
    payload: freshPayload(accepted) } as any);
  const head = await fetch(url, { method: "HEAD", headers: { "PAYMENT-SIGNATURE": sig }, signal: AbortSignal.timeout(t) })
    .catch((e) => ({ status: 0, headers: new Headers(), error: String(e) }) as any);
  await new Promise((ok) => setTimeout(ok, 250));
  const settleCalls = double.calls.filter((c) => c.path === "/settle").length - before.calls;
  const charged = double.successes.length - before.ok;
  const pr = !!head.headers?.get?.("payment-response");
  const refused = head.status >= 400;
  const pass = refused && settleCalls === 0 && charged === 0 && !pr;
  return [{ check: R16, pass, status: pass ? "pass" : "fail",
    detail: { network: accepted.network, head_status: head.status, settle_calls: settleCalls, charged, payment_response: pr,
      ...(settleCalls > 0 ? { error: "the server called /settle for a HEAD request, which delivers no content" }
        : !refused ? { error: `the paid HEAD was answered ${head.status}, not refused` } : {}) } }];
}
