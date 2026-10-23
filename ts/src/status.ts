// After a successful settle the paid response keeps the handler's 2xx status and headers.
// The probe pays each route with a fresh payment the local facilitator double accepts and compares
// the paid response with the status and headers the route's handler is known to send.
// Only 2xx statuses are graded: a paid 3xx, 4xx or 5xx is not settled at all (R15).
import { decodePaymentRequiredHeader, encodePaymentSignatureHeader } from "@x402/core/http";
import type { Double } from "./double.js";
import type { Result } from "./probe.js";
import { freshPayload } from "./retry.js";

export const R22 = "R22 after a successful settle the client receives the handler's own 2xx status code and headers, "
  + "never a rewritten 200";

/** A paid route, the 2xx status its handler answers, and the headers that handler sets. */
export interface StatusRoute { url: string; status: number; headers?: string[] }

/** Routes to pay, by name. */
export type StatusRoutes = Record<string, StatusRoute>;

export interface StatusOptions { network?: string; timeoutMs?: number }

async function payOnce(route: StatusRoute, double: Double, opts: StatusOptions) {
  const t = opts.timeoutMs ?? 15_000;
  const r = await fetch(route.url, { redirect: "manual", signal: AbortSignal.timeout(t) }).catch(() => null);
  const h = r?.headers.get("payment-required");
  let required: any = null;
  try { required = h ? decodePaymentRequiredHeader(h) : null; } catch { required = null; }
  const accepted = required?.accepts?.find((a: any) => a.scheme === "exact" && (!opts.network || a.network === opts.network));
  if (r?.status !== 402 || !accepted) return { graded: false, unpaid_status: r?.status ?? null } as const;
  double.mode = "reference";
  const before = { calls: double.calls.filter((c) => c.path === "/settle").length, ok: double.successes.length };
  const sig = encodePaymentSignatureHeader({ x402Version: 2, resource: required.resource, accepted,
    payload: freshPayload(accepted) } as any);
  const paid = await fetch(route.url, { headers: { "PAYMENT-SIGNATURE": sig }, redirect: "manual",
    signal: AbortSignal.timeout(t) }).catch((e) => ({ status: 0, headers: new Headers(), error: String(e) }) as any);
  await new Promise((ok) => setTimeout(ok, 250));
  const settleCalls = double.calls.filter((c) => c.path === "/settle").length - before.calls;
  const headers: Record<string, string> = {};
  for (const name of route.headers ?? []) headers[name.toLowerCase()] = paid.headers?.get?.(name) ?? "";
  return { graded: true, network: accepted.network, status: paid.status as number, headers,
    settle_calls: settleCalls, charged: double.successes.length - before.ok } as const;
}

/** Runs R22 against a server wired to `double`. */
export async function probeStatus(routes: StatusRoutes, double: Double, opts: StatusOptions = {}): Promise<Result[]> {
  const cases: Record<string, unknown> = {};
  const errors: string[] = [];
  let graded = 0;
  for (const [name, route] of Object.entries(routes)) {
    if (!route?.url) continue;
    if (!Number.isInteger(route.status) || route.status < 200 || route.status > 299) {
      errors.push(`${name}: expected status ${route.status} is not 2xx; a paid 3xx, 4xx or 5xx must not be settled (R15)`);
      continue;
    }
    const c = await payOnce(route, double, opts);
    cases[name] = { expected: route.status, ...c };
    if (!c.graded) { errors.push(`${name}: the route did not answer 402 with an exact offer the probe can pay`); continue; }
    graded++;
    const missing = Object.entries(c.headers).filter(([, v]) => !v).map(([k]) => k);
    if (c.settle_calls < 1 || c.charged < 1) errors.push(`${name}: settle did not succeed`);
    else if (c.status !== route.status) errors.push(`${name}: answered ${c.status}, the handler status is ${route.status}`);
    else if (missing.length) errors.push(`${name}: the handler header ${missing.join(", ")} is missing`);
  }
  const pass = graded > 0 && errors.length === 0;
  return [{ check: R22, pass, status: graded ? (pass ? "pass" : "fail") : "unsupported",
    detail: { cases, ...(errors.length ? { error: errors.join("; ") } : {}) } }];
}
