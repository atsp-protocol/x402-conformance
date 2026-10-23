// After a successful settle the paid response keeps the handler's status and Location.
// The probe pays one route whose handler answers 201 and one whose handler answers 302
// with a Location, each with a fresh payment the local facilitator double accepts.
import { decodePaymentRequiredHeader, encodePaymentSignatureHeader } from "@x402/core/http";
import type { Double } from "./double.js";
import type { Result } from "./probe.js";
import { freshPayload } from "./retry.js";

export const R22 = "R22 after a successful settle the client receives the handler's own status code and Location, "
  + "never a rewritten 200";

/** Routes to pay. Either may be omitted. */
export interface StatusRoutes { created?: string; redirect?: string }

export interface StatusOptions { network?: string; timeoutMs?: number }

const EXPECTED: Record<string, number> = { created: 201, redirect: 302 };

async function payOnce(url: string, double: Double, opts: StatusOptions) {
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
  await new Promise((ok) => setTimeout(ok, 250));
  const settleCalls = double.calls.filter((c) => c.path === "/settle").length - before.calls;
  const location = paid.headers?.get?.("location") ?? "";
  return { graded: true, network: accepted.network, status: paid.status as number, location,
    settle_calls: settleCalls, charged: double.successes.length - before.ok } as const;
}

/** Runs R22 against a server wired to `double`. */
export async function probeStatus(routes: StatusRoutes, double: Double, opts: StatusOptions = {}): Promise<Result[]> {
  const cases: Record<string, unknown> = {};
  let graded = 0;
  let pass = true;
  for (const [name, url] of Object.entries(routes)) {
    if (!url) continue;
    const c = await payOnce(url, double, opts);
    cases[name] = c;
    if (!c.graded) { pass = false; continue; }
    graded++;
    const want = EXPECTED[name];
    const locationOk = name !== "redirect" || (typeof c.location === "string" && c.location.length > 0);
    if (c.settle_calls < 1 || c.charged < 1 || c.status !== want || !locationOk) pass = false;
  }
  const errors: string[] = [];
  for (const [name, c] of Object.entries(cases) as [string, any][]) {
    if (!c.graded) errors.push(`${name}: the route did not answer 402 with an exact offer the probe can pay`);
    else if (c.settle_calls < 1 || c.charged < 1) errors.push(`${name}: settle did not succeed`);
    else if (c.status !== EXPECTED[name]) errors.push(`${name}: answered ${c.status}, the handler status is ${EXPECTED[name]}`);
    else if (name === "redirect" && !c.location) errors.push(`${name}: the Location header is missing`);
  }
  if (!graded) pass = false;
  return [{ check: R22, pass, status: graded ? (pass ? "pass" : "fail") : "unsupported",
    detail: { cases, ...(errors.length ? { error: errors.join("; ") } : {}) } }];
}
