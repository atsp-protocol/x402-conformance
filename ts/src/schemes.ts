// U1-U3 for the upto scheme and B1-B3 for the batch-settlement scheme, from the scheme specs (specs/schemes/upto and
// specs/schemes/batch-settlement in the x402 repository), on Solana devnet and Base Sepolia, against a facilitator
// double on loopback. Nothing is signed and no chain is touched: the payloads carry random signatures, and the double
// settles whatever amount it is asked to settle, so the probe can see what the server asked for.
//
// upto (scheme_upto.md, Core Properties 4 and 5, and Payment Flow):
//   U1  every settle after the handler runs asks for an amount at or below the authorised maximum (the signed
//       permit2Authorization.permitted.amount on EVM, maxAmount on Solana)
//   U2  the paid response reports the amount it settled: PAYMENT-RESPONSE carries `amount`, equal to the settled amount,
//       with the settle's transaction (SettlementResponse extension)
//   U3  the offer's payment flow is one upto allows on its network: never upfront, authorization for Permit2 on EVM,
//       escrow for the Solana channel (P7's paymentFlow rule, graded for upto: an absent flow on Solana is escrow)
// batch-settlement (scheme_batch_settlement.md and the EVM and SVM bindings):
//   B1  a commitment is accepted and served at once with a non-empty commitment identifier and a charge at or below
//       the per-request amount, and the same voucher presented again is not served a second time
//   B2  one redemption run claims each channel once, at its latest voucher, and a run with nothing new claims nothing
//   B3  when part of a redemption run fails, the run reports each item with its own outcome, and the next run claims
//       the failed items again and only those
import { randomBytes } from "node:crypto";
import http from "node:http";
import type { AddressInfo, Socket } from "node:net";
import { decodePaymentRequiredHeader, decodePaymentResponseHeader, encodePaymentSignatureHeader } from "@x402/core/http";
import { BASE_SEPOLIA, DEVNET, DOUBLE_EVM_SIGNER, DOUBLE_FEE_PAYER } from "./double.js";
import type { Result } from "./probe.js";

export const U1 = "U1 an upto settlement never exceeds the authorised maximum";
export const U2 = "U2 the paid response reports the amount an upto payment settled";
export const U3 = "U3 an upto offer declares only a payment flow upto allows on its network, never upfront";
export const B1 = "B1 a batch-settlement commitment is served once, with its commitment identifier and charge";
export const B2 = "B2 one redemption run claims each channel once, at its latest voucher";
export const B3 = "B3 a partly failed redemption run reports each item, and only the failed items are claimed again";

/** The canonical x402UptoPermit2Proxy, the spender in every upto Permit2 authorization on EVM. */
export const UPTO_PERMIT2_PROXY = "0x4020A4f3b7b90ccA423B9fabCc0CE57C6C240002";
/** A syntactically valid Solana key the double advertises as its receiverAuthorizer; it holds and signs nothing. */
export const DOUBLE_RECEIVER_AUTHORIZER = "SysvarRent111111111111111111111111111111111";

/** The payment flows each network binding of upto supports (Permit2 on EVM, the payment channel on Solana). */
export const UPTO_FLOWS: Record<string, string[]> = { [BASE_SEPOLIA]: ["authorization"], [DEVNET]: ["escrow"] };

export interface SettleRecord {
  scheme: string; network: string; type: string;
  /** The settlement-time requirements.amount the server sent. */
  amount: string;
  /** The authorised maximum in the signed payload (upto), or "" when there is none. */
  max: string;
  /** The claim rows of a batch-settlement claim. */
  claims: { channelId: string; maxClaimableAmount: string }[];
  success: boolean; transaction: string;
}

export interface SchemeDouble {
  url: string;
  /** Every /settle, in order. */
  settles: SettleRecord[];
  verifies: number;
  /** A batch-settlement claim /settle that names this channel fails as a whole (one transaction of the run). */
  failClaimOf: string | null;
  close(): Promise<void>;
}

let txSerial = 0;
const tx = (net: string) => net.startsWith("eip155:") ? "0x" + randomBytes(32).toString("hex")
  : `double-sig-${(++txSerial).toString(16)}-${randomBytes(8).toString("hex")}`;

/** A facilitator double for the upto and batch-settlement schemes on Solana devnet and Base Sepolia. */
export async function startSchemeDouble(port = 0): Promise<SchemeDouble> {
  const sockets = new Set<Socket>();
  const d: SchemeDouble = { url: "", settles: [], verifies: 0, failClaimOf: null, close: async () => {} };
  const server = http.createServer(async (rq, rs) => {
    const json = (code: number, obj: unknown) => {
      rs.writeHead(code, { "content-type": "application/json" });
      rs.end(JSON.stringify(obj));
    };
    let data = "";
    for await (const c of rq) data += c;
    const path = rq.url ?? "";
    if (rq.method === "GET" && path === "/supported") {
      const svm = { feePayer: DOUBLE_FEE_PAYER, receiverAuthorizer: DOUBLE_RECEIVER_AUTHORIZER };
      return json(200, {
        kinds: [
          { x402Version: 2, scheme: "upto", network: DEVNET, extra: svm },
          { x402Version: 2, scheme: "upto", network: BASE_SEPOLIA, extra: { facilitatorAddress: DOUBLE_EVM_SIGNER } },
          { x402Version: 2, scheme: "batch-settlement", network: DEVNET, extra: svm },
          { x402Version: 2, scheme: "batch-settlement", network: BASE_SEPOLIA,
            extra: { receiverAuthorizer: DOUBLE_EVM_SIGNER } },
        ],
        extensions: [], signers: { "solana:*": [DOUBLE_FEE_PAYER], "eip155:*": [DOUBLE_EVM_SIGNER] },
      });
    }
    let body: any;
    try { body = JSON.parse(data); } catch { return json(400, { isValid: false, invalidReason: "invalid_payload" }); }
    const req = body?.paymentRequirements ?? {};
    const network = String(req.network ?? DEVNET);
    const p = body?.paymentPayload?.payload ?? {};
    const payer = network.startsWith("eip155:") ? String(p.permit2Authorization?.from ?? p.channelConfig?.payer
      ?? DOUBLE_EVM_SIGNER) : String(p.from ?? p.channelConfig?.payer ?? "double-payer");
    if (path === "/verify") { d.verifies++; return json(200, { isValid: true, payer }); }
    if (path !== "/settle") return json(404, { error: "not found" });
    const scheme = String(req.scheme ?? body?.paymentPayload?.accepted?.scheme ?? "");
    const rec: SettleRecord = { scheme, network, type: String(p.type ?? ""), amount: String(req.amount ?? ""),
      max: String(p.permit2Authorization?.permitted?.amount ?? p.maxAmount ?? ""),
      claims: Array.isArray(p.claims) ? p.claims.map((c: any) => ({ channelId: String(c?.channelId ?? ""),
        maxClaimableAmount: String(c?.maxClaimableAmount ?? "") })) : [],
      success: true, transaction: tx(network) };
    d.settles.push(rec);
    if (scheme === "batch-settlement") {
      if (rec.type === "claim" && d.failClaimOf && rec.claims.some((c) => c.channelId === d.failClaimOf)) {
        rec.success = false;
        rec.transaction = "";
        return json(200, { success: false, errorReason: "invalid_transaction_state", transaction: "", network, payer });
      }
      const extra = rec.type === "deposit" ? { channelState: { channelId: String(p.channelConfig?.channelId
        ?? p.voucher?.channelId ?? ""), balance: String(p.deposit?.amount ?? "0"), totalClaimed: "0" } } : {};
      return json(200, { success: true, transaction: rec.transaction, network, payer,
        amount: rec.type === "deposit" ? String(p.deposit?.amount ?? "") : "", extra });
    }
    // upto: settle whatever was asked, and say so (the SettlementResponse extension carries the settled amount). A
    // real facilitator refuses an amount above the maximum; the double does not, so the probe sees the request.
    const amount = rec.type === "deposit" ? rec.max : rec.amount;
    return json(200, { success: true, transaction: rec.transaction, network, payer, amount });
  });
  server.on("connection", (s: Socket) => { sockets.add(s); s.on("close", () => sockets.delete(s)); });
  await new Promise<void>((ok) => server.listen(port, "127.0.0.1", ok));
  d.url = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  d.close = () => new Promise((ok) => { for (const s of sockets) s.destroy(); server.close(() => ok()); });
  return d;
}

const isUint = (s: unknown): s is string => typeof s === "string" && /^(0|[1-9][0-9]*)$/.test(s);
const hex = (n: number) => "0x" + randomBytes(n).toString("hex");
const b58 = (n: number) => {
  const A = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
  return Array.from(randomBytes(n), (b) => A[b % 58]).join("");
};

/** An upto payload in the network's shape, authorising `accepted.amount` as the maximum. Random signatures: the double
 * never checks them and nothing here can move funds. */
export function uptoPayload(accepted: any): Record<string, unknown> {
  const now = Math.floor(Date.now() / 1000);
  if (String(accepted.network).startsWith("eip155:")) {
    return { signature: hex(65), permit2Authorization: { from: "0x" + "ab".repeat(20),
      permitted: { token: accepted.asset, amount: accepted.amount }, spender: UPTO_PERMIT2_PROXY,
      nonce: BigInt(hex(16)).toString(), deadline: String(now + Number(accepted.maxTimeoutSeconds ?? 60)),
      witness: { to: accepted.payTo, facilitator: accepted.extra?.facilitatorAddress ?? DOUBLE_EVM_SIGNER,
        validAfter: String(now - 60) } } };
  }
  return { from: b58(44), maxAmount: accepted.amount, deposit: accepted.amount,
    expiresAt: now + Number(accepted.maxTimeoutSeconds ?? 60), validAfter: now - 60,
    nonce: BigInt(hex(8)).toString(), openSlot: 341000000, channelId: b58(44),
    authorizedSigner: accepted.extra?.receiverAuthorizer ?? DOUBLE_RECEIVER_AUTHORIZER,
    openTransaction: randomBytes(96).toString("base64") };
}

async function get(url: string, headers: Record<string, string>, timeoutMs: number) {
  try {
    const r = await fetch(url, { headers, redirect: "manual", signal: AbortSignal.timeout(timeoutMs) });
    const body = (await r.text()).slice(0, 300);
    let pr: any = null;
    const h = r.headers.get("payment-response");
    try { pr = h ? decodePaymentResponseHeader(h) : null; } catch { pr = { undecodable: h }; }
    let required: any = null;
    const q = r.headers.get("payment-required");
    try { required = q ? decodePaymentRequiredHeader(q) : null; } catch { required = null; }
    return { status: r.status, body, paymentResponse: pr, required };
  } catch (e) {
    return { status: 0, body: String(e).slice(0, 200), paymentResponse: null as any, required: null as any };
  }
}

async function offer(url: string, scheme: string, network: string | undefined, t: number) {
  const r = await get(url, {}, t);
  const accepted = (r.required?.accepts ?? []).find((a: any) => a?.scheme === scheme
    && (network ? a.network === network : a.network === DEVNET || a.network === BASE_SEPOLIA));
  return { status: r.status, required: r.required, accepted };
}

const unsupported = (ids: string[], detail: Record<string, unknown>): Result[] =>
  ids.map((check) => ({ check, pass: false, status: "unsupported", detail }));

export interface UptoOptions { network?: string; timeoutMs?: number }

/** Runs U1, U2 and U3 against a paid route whose 402 offers upto, served by a server wired to `double`. One paid GET
 * of `url`: point it at a request whose metered usage you want graded (a request that uses more than the maximum
 * shows whether the server caps the charge). */
export async function probeUpto(url: string, double: SchemeDouble, opts: UptoOptions = {}): Promise<Result[]> {
  const t = opts.timeoutMs ?? 15_000;
  const o = await offer(url, "upto", opts.network, t);
  if (o.status !== 402 || !o.accepted) {
    return unsupported([U1, U2, U3], { unpaid_status: o.status, error: "the route did not answer 402 with an upto offer "
      + `on ${opts.network ?? `${DEVNET} or ${BASE_SEPOLIA}`}; nothing was paid` });
  }
  const accepted = o.accepted;
  const network = String(accepted.network);
  const max = String(accepted.amount);
  // U3: the declared flow, graded against the scheme text and the network binding.
  const flow = accepted.extra?.paymentFlow;
  const allowed = UPTO_FLOWS[network] ?? [];
  const u3err = flow === "upfront" ? "the upto offer declares the upfront flow; upto settles after the handler runs, "
    + "so it cannot be upfront (scheme_upto.md, Payment Flow)"
    : flow !== undefined && !allowed.includes(String(flow)) ? `the upto offer declares paymentFlow ${JSON.stringify(flow)}`
      + ` on ${network}, where the binding supports only ${allowed.join(", ")}` : "";
  const u3: Result = { check: U3, pass: !u3err, status: u3err ? "fail" : "pass", detail: { network,
    declared_flow: flow ?? null, supported: allowed,
    ...(flow === undefined ? { note: `no extra.paymentFlow: ${allowed[0]} by default (P7 warns where V2 6.1 asks for it)` } : {}),
    ...(u3err ? { error: u3err } : {}) } };
  const header = encodePaymentSignatureHeader({ x402Version: 2, resource: o.required.resource, accepted,
    payload: uptoPayload(accepted) } as any);
  const before = double.settles.length;
  const paid = await get(url, { "PAYMENT-SIGNATURE": header }, t);
  await new Promise((ok) => setTimeout(ok, 200));
  const settles = double.settles.slice(before);
  const finals = settles.filter((s) => s.type !== "deposit");
  const served = paid.status >= 200 && paid.status < 300;
  const settled = finals.at(-1);
  const common = { network, max, status: paid.status, served,
    settles: settles.map((s) => ({ type: s.type || "settle", amount: s.amount })) };
  // U1: every final settle at or below the maximum.
  const over = finals.filter((s) => !isUint(s.amount) || BigInt(s.amount) > BigInt(max));
  const u1err = !served && !settled ? `the paid request was not served (status ${paid.status}) and nothing was settled`
    : !settled ? "the paid request was served without a settle" : over.length
      ? `asked the facilitator to settle ${over.map((s) => s.amount).join(", ")} against an authorised maximum of ${max}`
      : "";
  const u1: Result = { check: U1, pass: !u1err, status: u1err ? "fail" : "pass", detail: { ...common,
    ...(u1err ? { error: u1err } : {}) } };
  // U2: the settled amount is reported.
  const pr = paid.paymentResponse;
  const u2err = !served || !settled ? "no paid response to read (see U1)"
    : !pr ? "the paid response has no PAYMENT-RESPONSE"
      : !isUint(pr.amount) ? "PAYMENT-RESPONSE has no amount; upto's SettlementResponse requires the amount charged"
        : BigInt(pr.amount) !== BigInt(settled.amount) ? `PAYMENT-RESPONSE reports ${pr.amount}, the settle charged `
          + settled.amount
          : pr.transaction !== settled.transaction ? "PAYMENT-RESPONSE does not name the settle's transaction" : "";
  const u2: Result = { check: U2, pass: !u2err, status: u2err ? "fail" : "pass", detail: { ...common,
    reported: pr ? { amount: pr.amount ?? null, transaction: pr.transaction ?? null } : null,
    ...(u2err ? { error: u2err } : {}) } };
  return [u1, u2, u3];
}

/** One item of a redemption run, as the server reports it. */
export interface RedeemItem { channelId: string; ok: boolean; maxClaimableAmount?: string; error?: string }

export interface BatchOptions {
  network?: string;
  timeoutMs?: number;
  /** Runs the server's redemption (claim) once and returns its report, one item per channel it tried. */
  redeem: () => Promise<RedeemItem[]>;
}

/** A batch-settlement payload. The first request on a channel is a deposit that opens it; later ones are vouchers. */
export function batchPayload(accepted: any, channelId: string, maxClaimableAmount: string, deposit?: string) {
  const evm = String(accepted.network).startsWith("eip155:");
  const voucher = { channelId, maxClaimableAmount, signature: evm ? hex(65) : b58(88) };
  const channelConfig = evm ? { payer: "0x" + "ab".repeat(20), payerAuthorizer: "0x" + "cd".repeat(20),
    receiver: accepted.payTo, receiverAuthorizer: accepted.extra?.receiverAuthorizer, token: accepted.asset,
    withdrawDelay: accepted.extra?.withdrawDelay ?? 900, salt: hex(32) }
    : { channelId, payer: b58(44), payerAuthorizer: b58(44), receiverAuthorizer: accepted.extra?.receiverAuthorizer,
      mint: accepted.asset, withdrawDelay: accepted.extra?.withdrawDelay ?? 900 };
  return deposit ? { type: "deposit", channelConfig, voucher,
    deposit: { amount: deposit, ...(evm ? { authorization: hex(65) } : { transaction: randomBytes(96).toString("base64") }) } }
    : { type: "voucher", channelConfig, voucher };
}

/** Runs B1, B2 and B3 against a paid route whose 402 offers batch-settlement, served by a server wired to `double`. */
export async function probeBatch(url: string, double: SchemeDouble, opts: BatchOptions): Promise<Result[]> {
  const t = opts.timeoutMs ?? 15_000;
  const o = await offer(url, "batch-settlement", opts.network, t);
  if (o.status !== 402 || !o.accepted) {
    return unsupported([B1, B2, B3], { unpaid_status: o.status, error: "the route did not answer 402 with a "
      + `batch-settlement offer on ${opts.network ?? `${DEVNET} or ${BASE_SEPOLIA}`}; nothing was paid` });
  }
  const accepted = o.accepted;
  const network = String(accepted.network);
  const amount = BigInt(accepted.amount);
  const evm = network.startsWith("eip155:");
  const channels = [0, 1, 2].map(() => evm ? hex(32) : b58(44));
  const charged: Record<string, bigint> = Object.fromEntries(channels.map((c) => [c, 0n]));
  const latest: Record<string, string> = {};
  const opened = new Set<string>();
  const b1errs: string[] = [];
  const requests: unknown[] = [];
  const pay = async (ch: string, cumulative?: bigint) => {
    const max = cumulative ?? charged[ch] + amount;
    const deposit = opened.has(ch) ? undefined : String(amount * 10n);
    const header = encodePaymentSignatureHeader({ x402Version: 2, resource: o.required.resource, accepted,
      payload: batchPayload(accepted, ch, String(max), deposit) } as any);
    const r = await get(url, { "PAYMENT-SIGNATURE": header }, t);
    const served = r.status >= 200 && r.status < 300;
    const pr = r.paymentResponse;
    const row = { channel: ch.slice(0, 10), voucher: String(max), status: r.status, served,
      charged: pr?.extra?.chargedAmount ?? null, commitment: pr?.extra?.commitmentId ?? pr?.extra?.channelState?.channelId ?? null };
    requests.push(row);
    if (served) {
      opened.add(ch);
      const c = pr?.extra?.chargedAmount;
      const id = pr?.extra?.commitmentId ?? pr?.extra?.channelState?.channelId;
      if (!pr || pr.success !== true) b1errs.push(`${row.channel}: served without a successful PAYMENT-RESPONSE`);
      else if (typeof id !== "string" || !id) b1errs.push(`${row.channel}: the PAYMENT-RESPONSE has no commitment identifier`);
      else if (!isUint(c) || BigInt(c) > amount) b1errs.push(`${row.channel}: extra.chargedAmount ${JSON.stringify(c)} is not `
        + `a charge at or below the per-request amount ${amount}`);
      else { charged[ch] += BigInt(c); latest[ch] = String(max); }
    }
    return { served, row };
  };
  // B1: open each channel and pay once more on it; then present the first channel's last voucher again.
  for (const ch of channels) {
    const a = await pay(ch);
    if (!a.served) b1errs.push(`${a.row.channel}: a valid deposit and voucher was not served (status ${a.row.status})`);
    const b = await pay(ch);
    if (!b.served) b1errs.push(`${b.row.channel}: a valid voucher was not served (status ${b.row.status})`);
  }
  const replay = await pay(channels[0], BigInt(latest[channels[0]] ?? "0"));
  if (replay.served) b1errs.push("a voucher already spent was served a second time");
  const b1: Result = { check: B1, pass: b1errs.length === 0, status: b1errs.length ? "fail" : "pass",
    detail: { network, amount: String(amount), requests, ...(b1errs.length ? { error: b1errs.join("; ") } : {}) } };
  // B2: one run claims each channel once, at its latest voucher; a second run with nothing new claims nothing.
  const claimsSince = (i: number) => double.settles.slice(i).filter((s) => s.type === "claim");
  const rows = (cs: SettleRecord[]) => cs.flatMap((s) => s.claims);
  const b2errs: string[] = [];
  let i = double.settles.length;
  const run1 = await opts.redeem().catch((e) => [{ channelId: "", ok: false, error: String(e) }] as RedeemItem[]);
  const r1 = rows(claimsSince(i));
  for (const ch of channels) {
    const mine = r1.filter((r) => r.channelId === ch);
    if (mine.length !== 1) b2errs.push(`run 1 claimed channel ${ch.slice(0, 10)} ${mine.length} times`);
    else if (latest[ch] && mine[0].maxClaimableAmount !== latest[ch]) b2errs.push(`run 1 claimed channel ${ch.slice(0, 10)} `
      + `at ${mine[0].maxClaimableAmount}, not at its latest voucher ${latest[ch]}`);
  }
  i = double.settles.length;
  const run2 = await opts.redeem().catch((e) => [{ channelId: "", ok: false, error: String(e) }] as RedeemItem[]);
  const r2 = rows(claimsSince(i));
  if (r2.length) b2errs.push(`run 2, with no new voucher, claimed ${r2.length} row(s) again`);
  const b2: Result = { check: B2, pass: b2errs.length === 0, status: b2errs.length ? "fail" : "pass",
    detail: { network, run1: { claims: r1.length, report: run1 }, run2: { claims: r2.length, report: run2 },
      ...(b2errs.length ? { error: b2errs.join("; ") } : {}) } };
  // B3: a new voucher on every channel, then a run in which the claim naming the middle channel fails.
  for (const ch of channels) await pay(ch);
  const b3errs: string[] = [];
  double.failClaimOf = channels[1];
  i = double.settles.length;
  const run3 = await opts.redeem().catch((e) => [{ channelId: "", ok: false, error: String(e) }] as RedeemItem[]);
  double.failClaimOf = null;
  const c3 = claimsSince(i);
  const outcome: Record<string, boolean> = {};
  for (const s of c3) for (const c of s.claims) outcome[c.channelId] = (outcome[c.channelId] ?? false) || s.success;
  const failed = channels.filter((ch) => outcome[ch] === false);
  if (!failed.length) b3errs.push("run 3 sent no claim naming the channel whose claim fails");
  for (const ch of channels) {
    const item = run3.find((x) => x.channelId === ch);
    if (!item) b3errs.push(`run 3's report has no item for channel ${ch.slice(0, 10)}`);
    else if (ch in outcome && item.ok !== outcome[ch]) b3errs.push(`run 3 reports channel ${ch.slice(0, 10)} as `
      + `${item.ok ? "claimed" : "failed"}, but its claim ${outcome[ch] ? "succeeded" : "failed"}`);
  }
  i = double.settles.length;
  const run4 = await opts.redeem().catch((e) => [{ channelId: "", ok: false, error: String(e) }] as RedeemItem[]);
  const r4 = rows(claimsSince(i)).map((r) => r.channelId).sort();
  if (JSON.stringify(r4) !== JSON.stringify([...failed].sort())) b3errs.push(`run 4 sent ${r4.length} claim row(s); `
    + `it must claim again exactly the ${failed.length} whose claim failed`);
  const b3: Result = { check: B3, pass: b3errs.length === 0, status: b3errs.length ? "fail" : "pass",
    detail: { network, failed_claims: failed.length, run3: { claims: c3.length, report: run3 }, run4: { claimed: r4.length },
      ...(b3errs.length ? { error: b3errs.join("; ") } : {}) } };
  return [b1, b2, b3];
}
