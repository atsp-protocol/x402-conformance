// R15: no settlement when the paid handler fails. The probe pays a route whose handler answers 5xx, one that
// redirects (3xx) and one that throws, each with a fresh well-formed payment the facilitator double accepts, and
// counts the /settle calls the server makes for it. In the authorization flow funds move only after the resource
// completes successfully (V2 6.1), so each must end with zero /settle calls and no PAYMENT-RESPONSE.
import { decodePaymentRequiredHeader, encodePaymentSignatureHeader } from "@x402/core/http";
import type { Double } from "./double.js";
import type { Result } from "./probe.js";
import { freshPayload } from "./retry.js";

export const R15 = "R15 a paid request whose handler fails (5xx), redirects (3xx) or throws makes no /settle call and "
  + "charges nothing";

/** The failing routes to pay: any subset; a route left out is reported as not graded. */
export interface FailingRoutes { error?: string; redirect?: string; throws?: string }

export interface DeliveryOptions { network?: string; timeoutMs?: number }

async function payOnce(url: string, double: Double, opts: DeliveryOptions) {
  const t = opts.timeoutMs ?? 15_000;
  const r = await fetch(url, { redirect: "manual", signal: AbortSignal.timeout(t) }).catch(() => null);
  const h = r?.headers.get("payment-required");
  let required: any = null;
  try { required = h ? decodePaymentRequiredHeader(h) : null; } catch { required = null; }
  const accepted = required?.accepts?.find((a: any) => a.scheme === "exact" && (!opts.network || a.network === opts.network));
  if (r?.status !== 402 || !accepted) return { graded: false, unpaid_status: r?.status ?? null } as const;
  double.mode = "reference";
  const before = { calls: double.calls.filter((c) => c.path === "/settle").length, ok: double.successes.length };
  const sig = encodePaymentSignatureHeader({ x402Version: 2, resource: required.resource, accepted,
    payload: freshPayload(accepted) } as any);
  const paid = await fetch(url, { headers: { "PAYMENT-SIGNATURE": sig }, redirect: "manual", signal: AbortSignal.timeout(t) })
    .catch((e) => ({ status: 0, headers: new Headers(), error: String(e) }) as any);
  await new Promise((ok) => setTimeout(ok, 250));   // a server that settles after it answered has done so by now
  const settleCalls = double.calls.filter((c) => c.path === "/settle").length - before.calls;
  return { graded: true, network: accepted.network, status: paid.status, settle_calls: settleCalls,
    charged: double.successes.length - before.ok, payment_response: !!paid.headers?.get?.("payment-response") } as const;
}

/** Runs R15 against the failing routes of a server wired to `double`. */
export async function probeDelivery(routes: FailingRoutes, double: Double, opts: DeliveryOptions = {}): Promise<Result[]> {
  const cases: Record<string, unknown> = {};
  let graded = 0;
  let pass = true;
  for (const [name, url] of Object.entries(routes)) {
    if (!url) continue;
    const c = await payOnce(url, double, opts);
    cases[name] = c;
    if (!c.graded) { pass = false; continue; }
    graded++;
    const status = c.status as number;
    const failed = name === "redirect" ? status >= 300 && status < 400 : status >= 400 || status === 0;
    if (c.settle_calls > 0 || c.charged > 0 || c.payment_response || !failed) pass = false;
  }
  const errors: string[] = [];
  for (const [name, c] of Object.entries(cases) as [string, any][]) {
    if (!c.graded) errors.push(`${name}: the route did not answer 402 with an exact offer the probe can pay`);
    else if (c.settle_calls > 0) errors.push(`${name}: the server called /settle for a request it did not serve (answered ${c.status})`);
  }
  if (!graded) pass = false;
  return [{ check: R15, pass, status: graded ? (pass ? "pass" : "fail") : "unsupported",
    detail: { cases, ...(errors.length ? { error: errors.join("; ") } : {}) } }];
}
