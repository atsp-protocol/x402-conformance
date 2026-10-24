// R19, upfront and escrow flows. V2 6.1: at least one check must run before the resource executes, and a server must
// reject an unsupported flow. On a route whose offer declares extra.paymentFlow upfront or escrow, funds move before
// the resource runs, so the check that gates execution is the settle itself. The probe pays the route with the
// facilitator double failing the settle (no content may come back, and the refusal must say why), with it succeeding
// (content once, one settle), and with payments signed for a flow the route did not offer (refused, no settle).
//
// What the probe can see is the protocol boundary: content that came back without a passing check. Whether the
// resource ran behind a refusal is visible only from inside the server, so a caller that can read its own execution
// count passes it as `executed`, and the probe then grades that too.
import { decodePaymentRequiredHeader, decodePaymentResponseHeader, encodePaymentSignatureHeader } from "@x402/core/http";
import type { Double } from "./double.js";
import type { Result } from "./probe.js";
import { freshPayload } from "./retry.js";

export const R19 = "R19 an upfront or escrow route never executes before a check has passed, and a payment for a flow "
  + "the route did not offer is refused without a settle";

export const FLOWS = ["upfront", "escrow"] as const;

export interface FlowOptions {
  network?: string;
  timeoutMs?: number;
  /** How many times the resource has executed so far, read from the server under test. Optional. */
  executed?: () => number | Promise<number>;
}

const served = (s: number) => s >= 200 && s < 300;
const res = (pass: boolean, status: Result["status"], detail: unknown): Result => ({ check: R19, pass, status, detail });

/** R19 against `url`, a paid route with an upfront or escrow offer on a server wired to `double`. */
export async function probeFlows(url: string, double: Double, opts: FlowOptions = {}): Promise<Result[]> {
  const t = opts.timeoutMs ?? 15_000;
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
  const declared = accepted.extra?.paymentFlow;
  if (!FLOWS.includes(declared)) {
    return [res(false, "unsupported", { network: accepted.network, declared_flow: declared ?? null,
      error: "the offer does not declare an upfront or escrow payment flow, so nothing was graded" })];
  }
  const count = async () => (opts.executed ? await opts.executed() : null);
  const pay = async (flow: string, mode: Double["mode"]) => {
    double.mode = mode;
    const offer = flow === declared ? accepted : { ...accepted, extra: { ...(accepted.extra ?? {}), paymentFlow: flow } };
    const sig = encodePaymentSignatureHeader({ x402Version: 2, resource: required.resource, accepted: offer,
      payload: freshPayload(offer) } as any);
    const before = { calls: double.calls.filter((c) => c.path === "/settle").length, ok: double.successes.length,
      executed: await count() };
    let status = 0;
    let body = "";
    let reason: string | null = null;
    let paymentResponse = false;
    try {
      const r = await fetch(url, { headers: { "PAYMENT-SIGNATURE": sig }, signal: AbortSignal.timeout(t) });
      status = r.status;
      body = await r.text();
      const settlement = r.headers.get("payment-response");
      paymentResponse = !!settlement;
      // The reason can come in PAYMENT-REQUIRED (error), in PAYMENT-RESPONSE (a failed settlement's errorReason), or
      // in a JSON body with an error field.
      const pr = r.headers.get("payment-required");
      try { reason = pr ? String((decodePaymentRequiredHeader(pr) as any)?.error ?? "") || null : null; } catch { reason = null; }
      if (!reason && settlement) {
        try {
          const sr: any = decodePaymentResponseHeader(settlement);
          if (sr && sr.success === false) reason = String(sr.errorReason ?? "") || null;
        } catch { reason = null; }
      }
      if (!reason) { try { reason = String(JSON.parse(body)?.error ?? "") || null; } catch { reason = null; } }
    } catch (e) { body = String(e); }
    await new Promise((ok) => setTimeout(ok, 150));
    const after = await count();
    return { flow, status, served: served(status), reason, payment_response: paymentResponse,
      settle_calls: double.calls.filter((c) => c.path === "/settle").length - before.calls,
      charged: double.successes.length - before.ok,
      executed: before.executed === null || after === null ? null : after - before.executed };
  };
  const other = declared === "upfront" ? "escrow" : "upfront";
  const cases = {
    check_fails: await pay(declared, "settle_failed"),
    check_passes: await pay(declared, "reference"),
    wrong_flow: await pay(other, "reference"),
    unknown_flow: await pay("bogus", "reference"),
  };
  double.mode = "reference";
  const problems: string[] = [];
  const f = cases.check_fails;
  if (f.served) problems.push("the content was served although the check (the settle) failed");
  else if (f.status !== 402 || !f.reason) problems.push(`a failed check was answered ${f.status} without a reason`);
  if (f.executed) problems.push("the resource executed before a check had passed");
  const p = cases.check_passes;
  if (!p.served) problems.push(`a payment the check passed was not served (${p.status})`);
  if (p.charged !== 1) problems.push(`a served payment was settled ${p.charged} times, not once`);
  if (p.executed !== null && p.executed !== 1) problems.push(`the resource executed ${p.executed} times for one served payment`);
  for (const [name, c] of [["wrong_flow", cases.wrong_flow], ["unknown_flow", cases.unknown_flow]] as const) {
    if (c.served) problems.push(`a payment signed for the ${c.flow} flow, which the route did not offer, was served (${name})`);
    else if (c.status !== 402 && c.status !== 400) problems.push(`a payment for the ${c.flow} flow got ${c.status}, not 402 or 400`);
    if (c.settle_calls > 0) problems.push(`a payment for the ${c.flow} flow, which the route did not offer, reached /settle`);
    if (c.executed) problems.push(`the resource executed for a payment signed for the ${c.flow} flow`);
  }
  const pass = problems.length === 0;
  return [res(pass, pass ? "pass" : "fail", { network: accepted.network, declared_flow: declared,
    execution_observed: !!opts.executed, cases, ...(problems.length ? { error: [...new Set(problems)].join("; ") } : {}) })];
}
