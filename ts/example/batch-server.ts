// A resource server for B1-B3, the batch-settlement scheme, on Solana devnet or Base Sepolia. One paid GET route,
// /api, at most 1000 atomic units a request (the actual charge is 700), plus a redemption run, redeem(), that claims
// the stored vouchers through the facilitator in batches of at most two channels (one claim /settle per batch).
//
// It keeps the per-channel state the bindings require of the server: the first request on a channel is a deposit
// that the facilitator settles and opens the channel; after that the server takes a voucher only when its
// maxClaimableAmount is the charged total plus the per-request amount (anything else gets a corrective 402), runs the
// handler, then commits the charge. A redemption run claims each channel's latest voucher above what it has already
// claimed and reports one item per channel. Every payload is checked with the facilitator's /verify first.
// BATCH_FAULT shows what B1-B3 catch:
//   accept_replay        takes any voucher whose amount is within the channel's latest, so a spent voucher is served
//                        again (B1)
//   claim_every_voucher  claims every voucher it ever stored, not only each channel's latest, and never records a claim
//                        (B2)
//   drop_failed          records a failed batch's channels as claimed and reports them claimed (B3)
import http from "node:http";
import type { AddressInfo } from "node:net";
import { decodePaymentSignatureHeader, encodePaymentRequiredHeader, encodePaymentResponseHeader } from "@x402/core/http";

export const DEVNET = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1";
export const BASE_SEPOLIA = "eip155:84532";
export const BATCH_FAULTS = ["accept_replay", "claim_every_voucher", "drop_failed"] as const;
export type BatchFault = "" | (typeof BATCH_FAULTS)[number];
export const PER_REQUEST = 1000n;
export const CHARGE = 700n;

interface ChannelState { charged: bigint; latest: bigint; claimed: bigint; vouchers: bigint[]; payer: string }
export interface RedeemItem { channelId: string; ok: boolean; maxClaimableAmount?: string; error?: string }
export interface BatchServer {
  base: string; handled: number; channels: Map<string, ChannelState>;
  redeem(): Promise<RedeemItem[]>; close(): Promise<void>;
}

export async function startBatchServer(facilitatorUrl: string, fault: BatchFault = "", network = DEVNET,
    port = 0): Promise<BatchServer> {
  const evm = network === BASE_SEPOLIA;
  const accepted = evm
    ? { scheme: "batch-settlement", network, amount: String(PER_REQUEST), asset: "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
      payTo: "0x209693Bc6afc0C5328bA36FaF03C514EF312287C", maxTimeoutSeconds: 300,
      extra: { receiverAuthorizer: "0x000000000000000000000000000000000000dEaD", withdrawDelay: 900, name: "USDC",
        version: "2" } }
    : { scheme: "batch-settlement", network, amount: String(PER_REQUEST), asset: "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU",
      payTo: "11111111111111111111111111111112", maxTimeoutSeconds: 300,
      extra: { feePayer: "11111111111111111111111111111111", receiverAuthorizer: "SysvarRent111111111111111111111111111111111",
        withdrawDelay: 900, tokenProgram: "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA" } };
  const resource = { url: "", description: "batch-settlement example", mimeType: "application/json" };
  const channels = new Map<string, ChannelState>();
  const facilitator = async (path: string, paymentPayload: unknown, paymentRequirements: unknown) => {
    const r = await fetch(`${facilitatorUrl}${path}`, { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ x402Version: 2, paymentPayload, paymentRequirements }), signal: AbortSignal.timeout(3000) });
    return await r.json() as any;
  };
  const state: BatchServer = { base: "", handled: 0, channels, close: async () => {},
    redeem: async () => {
      const due = [...channels.entries()].filter(([, c]) => fault === "claim_every_voucher" ? c.vouchers.length > 0
        : c.latest > c.claimed);
      const rows = due.flatMap(([id, c]) => fault === "claim_every_voucher"
        ? c.vouchers.map((v) => ({ channelId: id, maxClaimableAmount: String(v) }))
        : [{ channelId: id, maxClaimableAmount: String(c.latest) }]);
      const report: RedeemItem[] = [];
      for (let i = 0; i < rows.length; i += 2) {
        const batch = rows.slice(i, i + 2);
        let ok = false;
        let error = "";
        try {
          const s = await facilitator("/settle", { x402Version: 2, accepted, payload: { type: "claim", claims: batch } },
            accepted);
          ok = s?.success === true;
          if (!ok) error = String(s?.errorReason ?? "claim failed");
        } catch (e) { error = String(e).slice(0, 120); }
        for (const row of batch) {
          const c = channels.get(row.channelId)!;
          if ((ok || fault === "drop_failed") && fault !== "claim_every_voucher") {
            c.claimed = BigInt(row.maxClaimableAmount) > c.claimed ? BigInt(row.maxClaimableAmount) : c.claimed;
          }
          if (!report.some((x) => x.channelId === row.channelId)) {
            report.push({ channelId: row.channelId, ok: ok || fault === "drop_failed",
              maxClaimableAmount: row.maxClaimableAmount, ...(ok || fault === "drop_failed" ? {} : { error }) });
          }
        }
      }
      return report;
    } };
  const server = http.createServer(async (rq, res) => {
    const url = new URL(rq.url ?? "/", "http://127.0.0.1");
    const send = (status: number, headers: Record<string, string>, body: unknown) => {
      res.writeHead(status, { "content-type": "application/json", ...headers });
      res.end(JSON.stringify(body));
    };
    if (url.pathname !== "/api") return send(404, {}, { error: "not found" });
    resource.url = url.toString();
    const required = (error: string, extra: Record<string, unknown> = {}) => send(402, {
      "PAYMENT-REQUIRED": encodePaymentRequiredHeader({ x402Version: 2, error, resource,
        accepts: [{ ...accepted, extra: { ...accepted.extra, ...extra } }] } as any) }, { error });
    const h = rq.headers["payment-signature"];
    if (typeof h !== "string") return required("payment required");
    let p: any;
    try { p = decodePaymentSignatureHeader(h); } catch { return required("invalid_payload"); }
    const pl = p?.payload ?? {};
    const id = String(pl.voucher?.channelId ?? "");
    const max = /^[0-9]{1,30}$/.test(String(pl.voucher?.maxClaimableAmount)) ? BigInt(pl.voucher.maxClaimableAmount) : -1n;
    if (p?.accepted?.scheme !== "batch-settlement" || p?.accepted?.network !== network || !id || max < 0n) {
      return required("invalid_payload");
    }
    try {
      const v = await facilitator("/verify", p, accepted);
      if (v?.isValid !== true) return required(String(v?.invalidReason ?? "invalid_payload"));
      let c = channels.get(id);
      if (!c && pl.type !== "deposit") return required("invalid_batch_settlement_channel_not_found");
      const charged = c?.charged ?? 0n;
      const fresh = max === charged + PER_REQUEST;
      const replayable = fault === "accept_replay" && c && max <= c.latest && max > 0n;
      if (!fresh && !replayable) {
        return required("invalid_batch_settlement_cumulative_amount_mismatch",
          { channelState: { channelId: id, chargedCumulativeAmount: String(charged) } });
      }
      let depositTx = "";
      if (pl.type === "deposit") {
        const s = await facilitator("/settle", p, accepted);
        if (s?.success !== true) return required(String(s?.errorReason ?? "deposit failed"));
        depositTx = String(s.transaction ?? "");
        if (!c) {
          c = { charged: 0n, latest: 0n, claimed: 0n, vouchers: [], payer: String(s.payer ?? "") };
          channels.set(id, c);
        }
      }
      // The handler runs, then the charge is committed.
      state.handled++;
      const ch = c!;
      if (fresh) {
        ch.charged += CHARGE;
        ch.latest = max;
        ch.vouchers.push(max);
      }
      const response = { success: true, transaction: depositTx, network, payer: ch.payer, amount: "",
        extra: { commitmentId: `${id}:${max}`, chargedAmount: String(CHARGE),
          channelState: { channelId: id, chargedCumulativeAmount: String(ch.charged), totalClaimed: String(ch.claimed) } } };
      return send(200, { "PAYMENT-RESPONSE": encodePaymentResponseHeader(response as any) }, { content: "paid content" });
    } catch (e) {
      send(500, {}, { error: String(e).slice(0, 200) });
    }
  });
  await new Promise<void>((ok) => server.listen(port, "127.0.0.1", ok));
  state.base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  state.close = () => new Promise((ok) => { server.closeAllConnections(); server.close(() => ok()); });
  return state;
}
