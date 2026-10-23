// C1, a client never hands a 402 to its caller as a success. A client that receives 402 with payment requirements
// either pays and retries or surfaces a payment-required error, whatever its HTTP library's status validation is set
// to. checkClientHandles402 puts a recording proxy in front of a paid route (behind the facilitator double, which
// settles every well-formed payment) and runs the client once through it.
//
//   pass  the client was answered 402 with PAYMENT-REQUIRED, then either sent a paid attempt and resolved with a 2xx,
//         or its promise rejected (it surfaced an error to its caller)
//   fail  the client's promise resolved with the 402, or with anything else that is neither the paid content nor an
//         error. It also fails, grading nothing, when the route does not answer 402 with payment requirements or the
//         client never received that answer
import http from "node:http";
import type { AddressInfo } from "node:net";
import { decodePaymentRequiredHeader } from "@x402/core/http";
import type { Double } from "./double.js";
import type { Result } from "./probe.js";

/** A client under test: it fetches `url` with its own payment handling and returns what it hands its caller. */
export type PayingClient = (url: string) => Promise<Response>;

export interface ClientStatusOptions {
  /** How long the client may take before the check gives up on it (default 30 s). */
  timeoutMs?: number;
}

const C1 = "C1 a client that receives 402 pays and retries or surfaces an error; it never returns the 402 as a success";
const served = (s: number) => s >= 200 && s < 300;
const offers = (h: string | null) => {
  if (!h) return false;
  try { return ((decodePaymentRequiredHeader(h) as any)?.accepts?.length ?? 0) > 0; } catch { return false; }
};
const fail = (error: string, detail: Record<string, unknown> = {}): Result =>
  ({ check: C1, pass: false, status: "fail", detail: { ...detail, error } });

export async function checkClientHandles402(client: PayingClient, url: string, double: Double,
    opts: ClientStatusOptions = {}): Promise<Result> {
  const target = new URL(url);
  // The route must ask for payment, or there is nothing to grade.
  const probe = await fetch(url, { signal: AbortSignal.timeout(15_000) }).catch(() => null);
  await probe?.arrayBuffer().catch(() => null);
  if (probe?.status !== 402 || !offers(probe.headers.get("payment-required"))) {
    return fail("the route did not answer 402 with payment requirements, so nothing was graded",
      { route_status: probe?.status ?? 0 });
  }
  const seen: { paid: boolean; status: number; offer: boolean }[] = [];
  const proxy = http.createServer(async (rq, rs) => {
    const entry = { paid: typeof rq.headers["payment-signature"] === "string", status: 0, offer: false };
    seen.push(entry);
    const headers: Record<string, string> = {};
    for (const [k, v] of Object.entries(rq.headers)) {
      if (typeof v === "string" && !["host", "connection", "content-length", "transfer-encoding"].includes(k)) headers[k] = v;
    }
    try {
      const chunks: Buffer[] = [];
      for await (const c of rq) chunks.push(c as Buffer);
      const method = rq.method ?? "GET";
      const up = await fetch(new URL(rq.url ?? "/", target),
        { method, headers, body: method === "GET" || method === "HEAD" ? undefined : Buffer.concat(chunks) });
      entry.status = up.status;
      entry.offer = up.status === 402 && offers(up.headers.get("payment-required"));
      const out: Record<string, string> = {};
      up.headers.forEach((v, k) => { if (k !== "content-length" && k !== "transfer-encoding") out[k] = v; });
      rs.writeHead(up.status, out);
      rs.end(Buffer.from(await up.arrayBuffer()));
    } catch (e) {
      if (!rs.headersSent) rs.writeHead(502);
      rs.end(String(e));
    }
  });
  await new Promise<void>((ok) => proxy.listen(0, "127.0.0.1", ok));
  const front = `http://127.0.0.1:${(proxy.address() as AddressInfo).port}${target.pathname}${target.search}`;
  double.mode = "reference";
  double.settleDelayMs = 0;
  const before = double.successes.length;
  const wait = opts.timeoutMs ?? 30_000;
  let final: number | null = null;
  let rejected = false;
  let clientError: string | undefined;
  let timer: NodeJS.Timeout | undefined;
  const timeout = new Promise<"timeout">((ok) => { timer = setTimeout(() => ok("timeout"), wait); });
  try {
    const r = await Promise.race([client(front), timeout]);
    if (r !== "timeout") {
      final = r.status;
      await r.text().catch(() => "");
    }
  } catch (e) {
    rejected = true;
    clientError = String(e);
  } finally {
    clearTimeout(timer);
  }
  await new Promise<void>((ok) => { proxy.closeAllConnections(); proxy.close(() => ok()); });
  const asked = seen.some((s) => s.offer);
  const paid = seen.filter((s) => s.paid).length;
  const detail = { requests: seen.length, answered_402: seen.filter((s) => s.status === 402).length, paid_attempts: paid,
    final_status: final, rejected, ...(clientError ? { client_error: clientError } : {}),
    successful_settles: double.successes.length - before };
  let error: string | undefined;
  if (!asked) error = "the client never received a 402 with payment requirements, so nothing was graded";
  else if (rejected) error = undefined;
  else if (final === null) error = `the client neither resolved nor rejected within ${wait} ms`;
  else if (final === 402) {
    error = paid ? "the client paid, then returned a 402 to its caller as a success"
      : "the client returned the 402 to its caller as a success without paying";
  } else if (!served(final)) error = `the client resolved with status ${final}: neither the paid content nor an error`;
  else if (!paid) error = "the client resolved with a 2xx but never sent a paid attempt";
  return error ? fail(error, detail) : { check: C1, pass: true, status: "pass", detail };
}
