// R24, a malformed payment header is a 4xx. The probe sends a paid route payment headers that are not base64, base64
// that is not JSON, JSON that is not an object, the JSON literals null, true and false, an empty object, an object whose
// required members are null, an empty value and a blank one, and reads each answer.
//
//   R24  every one gets 402 (or 400) with a structured error: a PAYMENT-REQUIRED header that decodes to a
//        PaymentRequired object, a JSON body with an error field, or a V1 JSON body with accepts. Never a 5xx, never a
//        dropped connection (an unhandled exception), never the content and never a /verify or /settle on the
//        facilitator. The unpaid request is the control: it gets 402 before the batch and still gets 402 after it.
//
// The header follows what the route advertises in its unpaid 402: PAYMENT-SIGNATURE for V2 (a PAYMENT-REQUIRED that
// decodes), X-PAYMENT for V1 (a JSON body with x402Version 1 and accepts), and both, one request each, when it
// advertises both. fetch trims leading and trailing whitespace from header values, so the blank value reaches the
// server as an empty one.
import { decodePaymentRequiredHeader } from "@x402/core/http";
import type { Double } from "./double.js";
import type { Result } from "./probe.js";
import { RequestBudgetExceeded } from "./pace.js";

const CHECK = "R24 a malformed, non-base64 or non-object payment header gets 402 or 400 with a structured error, "
  + "never a 5xx or an unhandled exception";
const b64 = (s: string) => Buffer.from(s, "utf8").toString("base64");

/** The five values R24 sent before XC-90, unchanged. */
export const ORIGINAL_MALFORMED_HEADERS: Record<string, string> = {
  not_base64: "%%%not-base64%%%",
  base64_not_json: b64("this is not json"),
  json_array: b64("[1,2,3]"),
  json_string: b64("\"payment\""),
  json_number: b64("42"),
};

/** The malformed payment header values the probe sends, by name. */
export const MALFORMED_HEADERS: Record<string, string> = {
  ...ORIGINAL_MALFORMED_HEADERS,
  json_null: b64("null"),
  json_true: b64("true"),
  json_false: b64("false"),
  json_empty_object: b64("{}"),
  json_null_members: b64(JSON.stringify({ x402Version: 2, accepted: null, payload: null })),
  empty: "",
  whitespace: " ",
};

export type PaymentHeaderName = "PAYMENT-SIGNATURE" | "X-PAYMENT";

const res = (pass: boolean, detail: unknown): Result => ({ check: CHECK, pass, status: pass ? "pass" : "fail", detail });

function json(body: string): any {
  try { return JSON.parse(body); } catch { return undefined; }
}

const isObject = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);

/** The x402 versions an unpaid 402 advertises: V2 by a PAYMENT-REQUIRED that decodes to an object, V1 by a JSON body
 * with x402Version 1 and an accepts array. */
export function advertised(paymentRequired: string | null, body: string): { v1: boolean; v2: boolean } {
  let v2 = false;
  if (paymentRequired) {
    try { v2 = isObject(decodePaymentRequiredHeader(paymentRequired)); } catch { /* not a V2 header */ }
  }
  const j = json(body);
  return { v1: isObject(j) && j.x402Version === 1 && Array.isArray(j.accepts), v2 };
}

function structured(status: number, header: string | null, body: string): boolean {
  if (header) {
    try {
      if (isObject(decodePaymentRequiredHeader(header))) return true;
    } catch { /* not a structured PAYMENT-REQUIRED; try the body */ }
  }
  if (status === 400 || status === 402) {
    const j = json(body);
    return isObject(j) && ("error" in j || (j.x402Version === 1 && Array.isArray(j.accepts)));
  }
  return false;
}

export interface UnpaidAnswer { status: number; paymentRequired: string | null; body: string }

export interface MalformedHeaderOptions {
  /** The fetch to send with, e.g. a paced one from createPacedFetch for a live target. Defaults to global fetch. */
  fetch?: typeof fetch;
  /** The unpaid answer the caller already has for this URL. The probe then sends only the malformed values and the
   * control after them. */
  unpaid?: UnpaidAnswer;
  /** The status of an unpaid GET the caller already sent. Anything but 402 ends the probe with no request. A 402 is not
   * enough to pick the header, so the probe then sends its own unpaid GET (pass `unpaid` to save it). */
  unpaidGetStatus?: number;
  /** The values to send, by name. Defaults to MALFORMED_HEADERS; ORIGINAL_MALFORMED_HEADERS is R24 before XC-90. */
  values?: Record<string, string>;
  /** The headers to send each value in, instead of the ones the route advertises. */
  headers?: PaymentHeaderName[];
}

async function getUnpaid(f: typeof fetch, url: string): Promise<UnpaidAnswer | null> {
  const r = await f(url, { signal: AbortSignal.timeout(15_000) })
    .catch((e) => { if (e instanceof RequestBudgetExceeded) throw e; return null; });
  if (!r) return null;
  const body = await r.text().catch(() => "");
  return { status: r.status, paymentRequired: r.headers.get("payment-required"), body };
}

/** R24. `double` is the facilitator double the server uses, to count /verify and /settle calls; against a live server
 * that does not use it, pass `{ calls: [] }`. */
export async function probeMalformedHeader(url: string, double: Pick<Double, "calls">,
    opts: MalformedHeaderOptions = {}): Promise<Result[]> {
  const f = opts.fetch ?? fetch;
  if (opts.unpaidGetStatus !== undefined && opts.unpaidGetStatus !== 402 && !opts.unpaid) {
    return [res(false, { status: opts.unpaidGetStatus,
      error: "the route did not answer an unpaid request with 402, so nothing was graded" })];
  }
  const unpaid = opts.unpaid ?? await getUnpaid(f, url);
  // the unpaid GETs this probe sent itself: the one before the batch unless the caller passed its answer, and the control
  let unpaidRequests = opts.unpaid ? 0 : 1;
  if (unpaid?.status !== 402) {
    return [res(false, { status: unpaid?.status ?? null, unpaid_requests: unpaidRequests,
      error: "the route did not answer an unpaid request with 402, so nothing was graded" })];
  }
  const versions = advertised(unpaid.paymentRequired, unpaid.body);
  const headers: PaymentHeaderName[] = opts.headers
    ?? [...(versions.v2 ? ["PAYMENT-SIGNATURE" as const] : []), ...(versions.v1 ? ["X-PAYMENT" as const] : [])];
  if (!headers.length) {
    return [res(false, { status: 402, advertised: versions, unpaid_requests: unpaidRequests,
      error: "the unpaid 402 advertises no version (no PAYMENT-REQUIRED "
      + "that decodes, no V1 body with accepts), so the payment header to send is unknown and nothing was graded" })];
  }
  const facilitator = () => double.calls.filter((c) => c.path === "/verify" || c.path === "/settle").length;
  const cases: Record<string, unknown>[] = [];
  for (const [name, value] of Object.entries(opts.values ?? MALFORMED_HEADERS)) {
    for (const sentIn of headers) {
      const before = facilitator();
      try {
        const r = await f(url, { headers: { [sentIn]: value }, signal: AbortSignal.timeout(15_000) });
        const body = await r.text();
        const calls = facilitator() - before;
        const isStructured = structured(r.status, r.headers.get("payment-required"), body);
        const ok = (r.status === 402 || r.status === 400) && isStructured && calls === 0;
        cases.push({ header: name, sent_in: sentIn, status: r.status, structured_error: isStructured, facilitator_calls: calls,
          pass: ok, ...(ok ? {} : { body: body.slice(0, 200) }) });
      } catch (e) {
        if (e instanceof RequestBudgetExceeded) throw e;
        cases.push({ header: name, sent_in: sentIn, status: 0, structured_error: false, facilitator_calls: facilitator() - before,
          pass: false, error: `no answer: ${String(e).slice(0, 160)}` });
      }
    }
  }
  const after = await getUnpaid(f, url);
  unpaidRequests += 1;
  const controlAfter = { status: after?.status ?? 0 };
  const failed = cases.filter((c) => !c.pass);
  const facilitatorCalls = cases.reduce((n, c) => n + (c.facilitator_calls as number), 0);
  const worst = failed.find((c) => (c.status as number) >= 500) ?? failed.find((c) => c.status === 0)
    ?? failed.find((c) => (c.facilitator_calls as number) > 0) ?? failed[0];
  const what = (c: Record<string, unknown>) => `a malformed header (${c.header} in ${c.sent_in})`;
  const error = worst
    ? ((worst.status as number) >= 500 ? `${what(worst)} got ${worst.status}`
      : worst.status === 0 ? `${what(worst)} got no answer: the connection was dropped`
        : (worst.facilitator_calls as number) > 0 ? `${what(worst)} reached the facilitator's /verify or /settle`
          : `${what(worst)} got ${worst.status} without a structured error`)
    : controlAfter.status !== 402 ? `after the batch the unpaid control got ${controlAfter.status || "no answer"}, not 402` : undefined;
  return [res(!failed.length && controlAfter.status === 402,
    { advertised: versions, sent_in: headers, cases, unpaid_requests: unpaidRequests, facilitator_calls: facilitatorCalls,
      control_after: controlAfter,
      ...(error ? { error } : {}) })];
}
