// R24, a malformed payment header is a 4xx. The probe sends a paid route payment headers that are not base64, base64
// that is not JSON, and JSON that is not an object, and reads each answer.
//
//   R24  every one gets 402 (or 400) with a structured error: a PAYMENT-REQUIRED header that decodes to a
//        PaymentRequired object, or a JSON body with an error field. Never a 5xx, never a dropped connection (an
//        unhandled exception), and never the content
import { decodePaymentRequiredHeader } from "@x402/core/http";
import type { Double } from "./double.js";
import type { Result } from "./probe.js";

const CHECK = "R24 a malformed, non-base64 or non-object payment header gets 402 or 400 with a structured error, "
  + "never a 5xx or an unhandled exception";
const b64 = (s: string) => Buffer.from(s, "utf8").toString("base64");

/** The malformed PAYMENT-SIGNATURE values the probe sends, by name. */
export const MALFORMED_HEADERS: Record<string, string> = {
  not_base64: "%%%not-base64%%%",
  base64_not_json: b64("this is not json"),
  json_array: b64("[1,2,3]"),
  json_string: b64("\"payment\""),
  json_number: b64("42"),
};

const res = (pass: boolean, detail: unknown): Result => ({ check: CHECK, pass, status: pass ? "pass" : "fail", detail });

function structured(status: number, header: string | null, body: string): boolean {
  if (header) {
    try {
      const pr = decodePaymentRequiredHeader(header) as any;
      if (pr && typeof pr === "object" && !Array.isArray(pr)) return true;
    } catch { /* not a structured PAYMENT-REQUIRED; try the body */ }
  }
  if (status === 400 || status === 402) {
    try {
      const j = JSON.parse(body);
      return !!j && typeof j === "object" && !Array.isArray(j) && "error" in j;
    } catch { return false; }
  }
  return false;
}

export async function probeMalformedHeader(url: string, double: Double): Promise<Result[]> {
  const unpaid = await fetch(url, { signal: AbortSignal.timeout(15_000) }).catch(() => null);
  await unpaid?.arrayBuffer().catch(() => null);
  if (unpaid?.status !== 402) {
    return [res(false, { status: unpaid?.status ?? null,
      error: "the route did not answer an unpaid request with 402, so nothing was graded" })];
  }
  const before = double.calls.filter((c) => c.path === "/verify" || c.path === "/settle").length;
  const cases: Record<string, unknown>[] = [];
  for (const [name, value] of Object.entries(MALFORMED_HEADERS)) {
    try {
      const r = await fetch(url, { headers: { "PAYMENT-SIGNATURE": value }, signal: AbortSignal.timeout(15_000) });
      const body = await r.text();
      const ok = (r.status === 402 || r.status === 400) && structured(r.status, r.headers.get("payment-required"), body);
      cases.push({ header: name, status: r.status, structured_error: ok || structured(r.status, r.headers.get("payment-required"), body),
        pass: ok, ...(ok ? {} : { body: body.slice(0, 200) }) });
    } catch (e) {
      cases.push({ header: name, status: 0, structured_error: false, pass: false, error: `no answer: ${String(e).slice(0, 160)}` });
    }
  }
  const failed = cases.filter((c) => !c.pass);
  const facilitatorCalls = double.calls.filter((c) => c.path === "/verify" || c.path === "/settle").length - before;
  const worst = failed.find((c) => (c.status as number) >= 500) ?? failed.find((c) => c.status === 0) ?? failed[0];
  const error = !worst ? undefined
    : (worst.status as number) >= 500 ? `a malformed header (${worst.header}) got ${worst.status}`
      : worst.status === 0 ? `a malformed header (${worst.header}) got no answer: the connection was dropped`
        : `a malformed header (${worst.header}) got ${worst.status} without a structured error`;
  return [res(failed.length === 0, { cases, facilitator_calls: facilitatorCalls, ...(error ? { error } : {}) })];
}
