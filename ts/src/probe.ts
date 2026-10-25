// The resource-server probe. With the server's facilitator URL pointed at the double, it requests the paid route with
// a payment for each fault mode and checks that content is served only on a final, well-formed, first-time success.
//
//   R0  an unpaid request gets 402 with a decodable PAYMENT-REQUIRED header offering a network the probe can grade
//       (Solana devnet or Base Sepolia); a server that offers neither is "unsupported", not failed
//   R1  a paid request is served when the facilitator settles it, and the double saw the server's /verify or /settle
//       (otherwise the server is not using X402_FACILITATOR_URL, nothing after this would mean anything, and the probe stops)
//   R2  the same payment presented twice is served at most once (F3)
//   R3  /settle never answers: not served (F6)       R4  /settle HTML 502: not served (F6)
//   R5  /settle 503 with a success body: not served (F9)
//   R6  /settle non-JSON 200: not served (F9)        R7  /settle truncated body: not served (F9)
//   R8  settlement_pending: not served until final (F5)
//   R9  invalid_transaction_state: not served (F8)
//   R10 the served response carries a PAYMENT-RESPONSE header that decodes to success=true (V2 HTTP transport)
import { randomBytes } from "node:crypto";
import { decodePaymentRequiredHeader, decodePaymentResponseHeader, encodePaymentSignatureHeader } from "@x402/core/http";
import { BASE_SEPOLIA, DEVNET, NETWORKS, type Double, type Mode, type Network } from "./double.js";
import { userAgent, type Via } from "./report.js";

/** "unsupported": the target cannot be graded by this check (e.g. no network the suite pays on). "not_applicable": the
 * property does not apply to this implementation by design (e.g. C2 and C3 on a client that never signs payments). */
export type Status = "pass" | "fail" | "unsupported" | "not_applicable";
export interface Result { check: string; pass: boolean; status: Status; detail: unknown }
export interface ProbeOptions {
  /** Which network to pay on when the server offers several; "auto" takes the first of NETWORKS it offers. */
  network?: Network | "auto";
  /** How long one request may take. A server still holding the request at the deadline has served nothing. */
  deadlineMs?: number;
  /** Which entry point runs the probe; it goes into the User-Agent only. */
  via?: Via;
}

let UA = userAgent("library");
async function get(url: string, headers: Record<string, string>, timeoutMs: number) {
  const r = await fetch(url, { headers: { "user-agent": UA, ...headers }, signal: AbortSignal.timeout(timeoutMs) });
  const h: Record<string, string> = {};
  r.headers.forEach((v, k) => { h[k] = v; });
  return { status: r.status, body: (await r.text()).slice(0, 500), headers: h };
}
const served = (a: { status: number }) => a.status >= 200 && a.status < 300;
const res = (check: string, pass: boolean, detail: unknown, status?: Status): Result =>
  ({ check, pass, status: status ?? (pass ? "pass" : "fail"), detail });

function payloadFor(network: string, accepted: any): Record<string, unknown> {
  if (network.startsWith("eip155:")) {
    const now = Math.floor(Date.now() / 1000);
    // EIP-3009 transferWithAuthorization shape (EVM exact). The signature is random: the double never checks it.
    return {
      signature: "0x" + randomBytes(65).toString("hex"),
      authorization: { from: "0x" + randomBytes(20).toString("hex"), to: accepted.payTo, value: accepted.amount,
        validAfter: String(now - 60), validBefore: String(now + Number(accepted.maxTimeoutSeconds ?? 60)),
        nonce: "0x" + randomBytes(32).toString("hex") },
    };
  }
  return { transaction: randomBytes(160).toString("base64") };
}

export async function probe(resourceUrl: string, double: Double, opts: ProbeOptions = {}): Promise<Result[]> {
  const deadline = opts.deadlineMs ?? 60_000;
  UA = userAgent(opts.via ?? "library");
  const want: readonly string[] = !opts.network || opts.network === "auto" ? NETWORKS : [opts.network];
  const out: Result[] = [];
  const unpaid = await get(resourceUrl, {}, deadline);
  const prHeader = unpaid.headers["payment-required"];
  let required: any = null;
  try { required = prHeader ? decodePaymentRequiredHeader(prHeader) : null; } catch { required = null; }
  const offered: [string, string][] = required?.accepts?.map((a: any) => [a.scheme, a.network]) ?? [];
  let accepted: any;
  for (const n of want) {
    accepted = required?.accepts?.find((a: any) => a.network === n && a.scheme === "exact");
    if (accepted) break;
  }
  const r0 = "R0 unpaid request: 402 with a PAYMENT-REQUIRED header offering a network the probe grades";
  if (unpaid.status !== 402 || !required) {
    out.push(res(r0, false, { status: unpaid.status, payment_required_header: !!prHeader, accepts: offered }));
    return out;
  }
  if (!accepted) {
    out.push(res(r0, false, { status: unpaid.status, accepts: offered, gradable: want,
      note: "this server offers no exact payment on a network the probe can grade; nothing was tested. Offer " +
        `${DEVNET} or ${BASE_SEPOLIA} on a test build of the route.` }, "unsupported"));
    return out;
  }
  out.push(res(r0, true, { status: unpaid.status, accepts: offered, graded_on: accepted.network }));
  const pay = () => encodePaymentSignatureHeader({ x402Version: 2, resource: required.resource, accepted,
    payload: payloadFor(accepted.network, accepted) } as any);
  const paid = async (mode: Mode, header = pay()) => {
    double.mode = mode;
    const before = double.calls.length;
    try {
      const r = await get(resourceUrl, { "PAYMENT-SIGNATURE": header }, deadline);
      return { ...r, settles: double.calls.slice(before).filter((c) => c.path === "/settle" || c.path === "/verify").length };
    } catch (e) {
      // No answer by the deadline: nothing was served.
      return { status: 0, body: String(e), headers: {} as Record<string, string>, settles: 0 };
    } finally {
      double.mode = "reference";
    }
  };
  const ok = await paid("reference");
  const wired = ok.settles > 0;  // the server called /verify or /settle on the double
  out.push(res("R1 a settled payment is served, and the server used the facilitator double", served(ok) && wired,
    { status: ok.status, facilitator_calls_seen: ok.settles,
      ...(served(ok) && !wired ? { error: "content was served but the double saw no /verify or /settle: the server is " +
        "not using X402_FACILITATOR_URL. The remaining checks would be meaningless, so they were not run." } : {}) }));
  if (!wired) return out;
  const h = pay();
  const a = await paid("reference", h);
  const b = await paid("reference", h);
  out.push(res("R2 the same payment presented twice is served at most once (F3)",
    Number(served(a)) + Number(served(b)) <= 1, { first: a.status, second: b.status }));
  const faults: [string, Mode][] = [
    ["R3 /settle never answers: content not served (F6)", "settle_timeout"],
    ["R4 /settle HTML 502: content not served (F6)", "settle_502"],
    ["R5 /settle 503 with a success body: content not served (F9)", "settle_503"],
    ["R6 /settle non-JSON 200: content not served (F9)", "settle_non_json"],
    ["R7 /settle truncated body: content not served (F9)", "settle_truncated"],
    ["R8 settlement_pending: content not served before the payment is final (F5)", "settle_pending"],
    ["R9 invalid_transaction_state: content not served (F8)", "settle_failed"],
  ];
  for (const [check, mode] of faults) {
    const r = await paid(mode);
    out.push(res(check, !served(r), { status: r.status, body: r.body.slice(0, 120),
      ...(r.status === 0 ? { note: `no answer within ${deadline} ms; nothing served` } : {}) }));
  }
  let pr: any = null;
  try { pr = ok.headers["payment-response"] ? decodePaymentResponseHeader(ok.headers["payment-response"]) : null; } catch { pr = null; }
  out.push(res("R10 the served response carries a PAYMENT-RESPONSE header that decodes to success=true (V2 HTTP transport)",
    pr?.success === true, { header: !!ok.headers["payment-response"], decoded: pr }));
  return out;
}
