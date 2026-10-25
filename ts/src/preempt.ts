// R21, settlement preemption for caller-unbound settlement (Permit2 on EVM). In the exact scheme's Permit2 method the
// signed transfer names the x402ExactPermit2Proxy as spender, not the facilitator, so anyone holding the signature can
// submit it. A third party who sees the payment can settle it first: the funds still reach payTo, but the server's own
// settle then fails on the spent nonce. The server must not grant on a settlement it did not make, and a spent payment
// must not unlock the resource a second time.
//
// Base Sepolia only, against the facilitator double; nothing is signed and no chain is touched. The probe pays a route
// whose offer declares extra.assetTransferMethod "permit2":
//   preempted        /verify passes, then a third party wins: /settle answers permit2_invalid_nonce. Not served.
//   preempted_resend the same payment again, the facilitator healthy: the nonce is spent. Not served.
//   reference        a fresh payment the server settles itself: served, with PAYMENT-RESPONSE naming its transaction.
//   resend           that settled payment again: /settle answers permit2_invalid_nonce. Not served, unless the server
//                    replays its own record of the first grant (the same transaction) and settles nothing new.
import { randomBytes } from "node:crypto";
import { decodePaymentRequiredHeader, decodePaymentResponseHeader, encodePaymentSignatureHeader } from "@x402/core/http";
import { BASE_SEPOLIA, doubleTransaction, type Double } from "./double.js";
import type { Result } from "./probe.js";

export const R21 = "R21 a Permit2 payment a third party settled first is not granted, and a spent Permit2 payment is "
  + "not granted twice";

/** The canonical x402ExactPermit2Proxy, the spender in every exact Permit2 authorization. */
export const PERMIT2_PROXY = "0x402085c248EeA27D92E8b30b2C58ed07f9E20001";

export interface PreemptOptions { timeoutMs?: number }

/** A Permit2 payload in the exact EVM shape (permitWitnessTransferFrom). The signature is random: the double never
 * checks it, and nothing here can move funds. */
export function permit2Payload(accepted: any): Record<string, unknown> {
  const now = Math.floor(Date.now() / 1000);
  return { signature: "0x" + randomBytes(65).toString("hex"),
    permit2Authorization: { from: "0x" + "ab".repeat(20), permitted: { token: accepted.asset, amount: accepted.amount },
      spender: PERMIT2_PROXY, nonce: BigInt("0x" + randomBytes(16).toString("hex")).toString(),
      deadline: String(now + Number(accepted.maxTimeoutSeconds ?? 60)),
      witness: { to: accepted.payTo, validAfter: String(now - 60) } } };
}

async function get(url: string, headers: Record<string, string>, timeoutMs: number) {
  try {
    const r = await fetch(url, { headers, redirect: "manual", signal: AbortSignal.timeout(timeoutMs) });
    const body = (await r.text()).slice(0, 300);
    return { status: r.status, body, paymentResponse: r.headers.get("payment-response") };
  } catch (e) {
    return { status: 0, body: String(e).slice(0, 200), paymentResponse: null as string | null };
  }
}

const settles = (d: Double) => d.calls.filter((c) => c.path === "/settle").length;

/** Runs R21 against a server wired to `double`. */
export async function probePreempt(url: string, double: Double, opts: PreemptOptions = {}): Promise<Result[]> {
  const t = opts.timeoutMs ?? 15_000;
  const unpaid = { status: 0 };
  let required: any = null;
  try {
    const r = await fetch(url, { redirect: "manual", signal: AbortSignal.timeout(t) });
    unpaid.status = r.status;
    const h = r.headers.get("payment-required");
    required = h ? decodePaymentRequiredHeader(h) : null;
  } catch { required = null; }
  const accepted = required?.accepts?.find((a: any) => a.scheme === "exact" && a.network === BASE_SEPOLIA
    && a.extra?.assetTransferMethod === "permit2");
  if (unpaid.status !== 402 || !accepted) {
    return [{ check: R21, pass: false, status: "unsupported", detail: { unpaid_status: unpaid.status,
      error: `the route did not answer 402 with an exact offer on ${BASE_SEPOLIA} whose extra.assetTransferMethod is `
        + "permit2; preemption applies to caller-unbound settlement only, and nothing was paid" } }];
  }
  const header = (payload: Record<string, unknown>) => encodePaymentSignatureHeader({ x402Version: 2,
    resource: required.resource, accepted, payload } as any);
  const cases: Record<string, unknown> = {};
  const errors: string[] = [];
  const pay = async (name: string, mode: Double["mode"], payload: Record<string, unknown>) => {
    double.mode = mode;
    const before = { settles: settles(double), ok: double.successes.length };
    const a = await get(url, { "PAYMENT-SIGNATURE": header(payload) }, t);
    await new Promise((ok) => setTimeout(ok, 250));
    let pr: any = null;
    try { pr = a.paymentResponse ? decodePaymentResponseHeader(a.paymentResponse) : null; } catch { pr = null; }
    const row = { status: a.status, served: a.status >= 200 && a.status < 300, settle_calls: settles(double) - before.settles,
      charged: double.successes.length - before.ok, payment_response: pr };
    cases[name] = row;
    return row;
  };
  const first = permit2Payload(accepted);
  const pre = await pay("preempted", "settle_preempted", first);
  if (pre.served) errors.push("preempted: served on a settlement a third party made, after this server's own settle failed");
  const again = await pay("preempted_resend", "reference", first);
  if (again.served) errors.push("preempted_resend: served a payment whose Permit2 nonce a third party had spent");
  const second = permit2Payload(accepted);
  const ref = await pay("reference", "reference", second);
  const tx = doubleTransaction(second);
  if (!ref.served) errors.push(`reference: a payment the server settled was not served (status ${ref.status})`);
  else if (ref.charged !== 1) errors.push("reference: served without a successful /settle of its own");
  else if (ref.payment_response?.transaction !== tx) errors.push("reference: PAYMENT-RESPONSE does not name the settlement");
  const resend = await pay("resend", "reference", second);
  if (resend.served && (resend.payment_response?.transaction !== tx || resend.charged !== 0)) {
    errors.push("resend: a spent Permit2 payment was granted a second time, not replayed from the first grant");
  }
  const pass = errors.length === 0;
  return [{ check: R21, pass, status: pass ? "pass" : "fail", detail: { network: BASE_SEPOLIA, cases,
    third_party_settlements: double.preempted.length, ...(pass ? {} : { error: errors.join("; ") }) } }];
}
