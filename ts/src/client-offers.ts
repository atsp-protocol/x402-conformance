// C2, a client pays an offer within its own policy. Given several offers a client chooses one within its configured
// networks and maximum amount, not the first, and never signs for a network outside its configured set.
//
// checkClientOfferPolicy puts a recording proxy in front of a paid route (as checkClientRetry does) and rewrites the
// route's 402 so two decoys come before the route's own offers:
//   outside_network  the route's offer on a network outside the client's configured set (the same family first, so
//                    the decoy differs from the route's offer only in its network)
//   over_max         the route's offer on its own network, for more than the client's maximum
// It reads the `accepted` of every payment the client signs. A payment for one of the route's own offers goes on to
// the route; a payment for a decoy is answered 402 and never reaches /settle. It passes when every payment the client
// signed is within its policy and the request was served.
import http from "node:http";
import type { AddressInfo } from "node:net";
import { decodePaymentRequiredHeader, decodePaymentSignatureHeader, encodePaymentRequiredHeader } from "@x402/core/http";
import { BASE_SEPOLIA, DEVNET, type Double } from "./double.js";
import type { Result } from "./probe.js";

/** The client's own configuration: the networks it pays on, and its maximum per payment in atomic units. */
export interface OfferPolicy { networks: string[]; maxAmount: string }

/** What the caller says about the client under test. signsPayments: false declares a client that, by design, has no
 * payment path: it surfaces a 402 to its caller (C1 grades that) and never signs. When such a client signs nothing,
 * C2 and C3 are graded not_applicable rather than failed; if it signs anyway, it is graded as usual. */
export interface ClientSigningOptions { signsPayments?: boolean }

/** The not_applicable result for a client declared not to sign that signed nothing. */
export function notApplicable(check: string, finalStatus: number, thrown: string | undefined): Result {
  return { check, pass: false, status: "not_applicable", detail: {
    reason: "the client is declared not to sign x402 payments (signsPayments: false) and signed none, so there is no "
      + "offer choice or payment version to grade", final_status: finalStatus,
    ...(thrown ? { client_error: thrown.slice(0, 300) } : {}) } };
}

/** A client under test: it fetches `url`, pays an offer it chooses, and returns the final response. */
export type OfferClient = (url: string) => Promise<Response>;

const CHECK = "C2 given several offers the client pays one within its configured networks and maximum, not the first";
const OUTSIDE = ["solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp", "eip155:8453", DEVNET, BASE_SEPOLIA, "eip155:1"];
const DECOYS = ["outside_network", "over_max"] as const;

const res = (pass: boolean, detail: unknown): Result => ({ check: CHECK, pass, status: pass ? "pass" : "fail", detail });
const served = (s: number) => s >= 200 && s < 300;
const atomic = (s: unknown): s is string => typeof s === "string" && /^\d+$/.test(s);
const within = (a: any, p: OfferPolicy) =>
  p.networks.includes(a?.network) && atomic(a?.amount) && BigInt(a.amount) <= BigInt(p.maxAmount);
const key = (a: any) =>
  [a?.scheme, a?.network, a?.amount, a?.asset, a?.payTo].map((x) => String(x ?? "").toLowerCase()).join("|");

/** A network outside the client's set, in the route's own family when there is one. */
function outsideNetwork(route: string, allowed: string[]): string | undefined {
  const ns = route.split(":")[0] + ":";
  return [...OUTSIDE.filter((n) => n.startsWith(ns)), ...OUTSIDE].find((n) => !allowed.includes(n));
}

/** C2. Puts a recording proxy in front of `url` (a paid route behind `double`), offers the client two decoys before
 * the route's own offer, and reads which offer it signs. `policy` is the client's own declared configuration. */
export async function checkClientOfferPolicy(client: OfferClient, url: string, double: Double,
    policy: OfferPolicy, opts: ClientSigningOptions = {}): Promise<Result> {
  if (!atomic(policy.maxAmount) || policy.networks.length === 0) {
    return res(false, { policy, error: "the policy needs at least one network and a maximum in atomic units" });
  }
  const target = new URL(url);
  // The route's own offers, read unpaid. This also lets a server that syncs with its facilitator on first use do so.
  const r = await fetch(url, { signal: AbortSignal.timeout(15_000) }).catch(() => null);
  await r?.arrayBuffer().catch(() => null);
  let required: any = null;
  try {
    const h = r?.headers.get("payment-required");
    required = h ? decodePaymentRequiredHeader(h) : null;
  } catch { required = null; }
  const own: any[] = Array.isArray(required?.accepts) ? required.accepts : [];
  const route = own.find((a) => within(a, policy));
  const outside = route ? outsideNetwork(String(route.network), policy.networks) : undefined;
  if (r?.status !== 402 || !route || !outside) {
    return res(false, { status: r?.status ?? null, policy,
      error: "the route has no offer within the client's policy, so nothing was graded" });
  }
  const decoys = [{ ...route, network: outside }, { ...route, amount: String((BigInt(policy.maxAmount) + 1n) * 100n) }];
  const offers = [...decoys, ...own];
  const offered = offers.map((a, index) =>
    ({ index, role: DECOYS[index] ?? "route", network: a.network, amount: a.amount }));
  const rewrite = (h: string) => {
    try {
      const pr = decodePaymentRequiredHeader(h);
      return encodePaymentRequiredHeader({ ...pr, accepts: [...decoys, ...pr.accepts] });
    } catch { return h; }
  };
  const refusal = encodePaymentRequiredHeader({ ...required, error: "payment does not match an offer", accepts: offers });

  const payments: { index: number; network: string; amount: string; within_policy: boolean }[] = [];
  const proxy = http.createServer(async (rq, rs) => {
    const headers: Record<string, string> = {};
    for (const [k, v] of Object.entries(rq.headers)) if (typeof v === "string" && k !== "host") headers[k] = v;
    const sig = rq.headers["payment-signature"];
    if (typeof sig === "string") {
      let p: any = null;
      try { p = decodePaymentSignatureHeader(sig); } catch { p = null; }
      const a = p?.accepted;
      const index = offers.findIndex((o) => key(o) === key(a));
      payments.push({ index, network: String(a?.network ?? ""), amount: String(a?.amount ?? ""),
        within_policy: within(a, policy) });
      // Only a payment for one of the route's own offers goes on; a decoy, or anything never offered, stops here.
      if (index < decoys.length) {
        rs.writeHead(402, { "content-type": "application/json", "payment-required": refusal });
        rs.end("{}");
        return;
      }
    }
    try {
      const up = await fetch(new URL(rq.url ?? "/", target), { headers });
      const out: Record<string, string> = {};
      up.headers.forEach((v, k) => { if (k !== "content-length" && k !== "transfer-encoding") out[k] = v; });
      if (out["payment-required"]) out["payment-required"] = rewrite(out["payment-required"]);
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
  const before = double.successes.length;
  let status = 0;
  let thrown: string | undefined;
  try {
    const final = await client(front);
    status = final.status;
    await final.arrayBuffer().catch(() => null);
  } catch (e) { thrown = String(e); }
  await new Promise<void>((ok) => { proxy.closeAllConnections(); proxy.close(() => ok()); });

  if (opts.signsPayments === false && payments.length === 0) return notApplicable(CHECK, status, thrown);
  const bad = payments.find((p) => !p.within_policy);
  const chosen = bad ?? payments[0];
  let error: string | undefined;
  if (bad && !policy.networks.includes(bad.network)) {
    error = `signed an offer on ${bad.network}, outside its configured networks`;
  } else if (bad) {
    error = `signed an offer for ${bad.amount}, over its maximum of ${policy.maxAmount}`;
  } else if (payments.length === 0) {
    error = "a payable offer within policy was ignored";
  } else if (!served(status)) {
    error = "paid an offer within policy, but the request was not served";
  }
  return res(!error, { policy, offers: offered,
    chosen: chosen ? { index: chosen.index, network: chosen.network, amount: chosen.amount } : null,
    payments, final_status: status, successful_settles: double.successes.length - before,
    ...(thrown ? { client_error: thrown.slice(0, 300) } : {}), ...(error ? { error } : {}) });
}
