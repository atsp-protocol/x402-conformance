// R14: a crash between a successful /settle and the response. The client has paid; the server dies before the
// response reaches it, comes back, and the client presents the same payment again (a client retry with the same
// PAYMENT-SIGNATURE, and with the same payment-identifier id when the server advertises that extension).
//
// The probe crashes the server at two points, each with a fresh payment:
//   settle    the facilitator double commits the settlement, then kills the server before /settle answers, so the
//             server never learns the payment settled (a record written only after /settle returns is lost)
//   response  /settle answers success; the probe kills the server as the first byte of its response arrives, and
//             discards that response, so the client got nothing
// After each crash the server is restarted and the same payment presented again. The check passes when, at both
// points, the server never calls /settle for that payment again, never answers with a new 402 challenge (that asks
// the client to pay twice for one purchase), and ends in a defined outcome: it delivers (a 2xx, from its idempotency
// record) or it refuses and names the payment (transaction, payment id, signature or nonce) so it can be reconciled.
//
// The spec basis: the payment-identifier extension ("Same `id`, same payload | Return cached response"), V2 6.1 (in
// the default authorization flow funds move only after the resource completes, so the server owns delivery once it
// has settled), V2 9 settlement_pending (a transaction surfaced "so the caller can reconcile on chain before deciding
// whether to retry") and the SVM exact duplicate-settlement mitigation ("Merchants and/or Facilitators SHOULD
// maintain a short-term, in-memory cache"). The probe sends nothing beyond loopback and the URL it is given.
import { spawn, type ChildProcess } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import http from "node:http";
import https from "node:https";
import { decodePaymentRequiredHeader, decodePaymentResponseHeader, encodePaymentSignatureHeader } from "@x402/core/http";
import { BASE_SEPOLIA, DEVNET, NETWORKS, type Double, type Network } from "./double.js";
import type { Result } from "./probe.js";
import { userAgent, type Via } from "./report.js";

export const R14 = "R14 a crash between a successful /settle and the response settles once, never asks the client " +
  "to pay again, and ends delivered once or refused with the payment surfaced";
export const PAYMENT_IDENTIFIER = "payment-identifier";
export type CrashPoint = "settle" | "response";
export const CRASH_POINTS: CrashPoint[] = ["settle", "response"];

/** How the probe takes your server down and brings it back. kill() must not resolve until the server is gone. */
export interface ServerControl {
  kill(): Promise<void>;
  restart(): Promise<void>;
}

export interface CrashOptions {
  /** Which entry point runs the probe; it goes into the User-Agent only. */
  via?: Via;
  network?: Network | "auto";
  /** How long one request may take (default 30 s). */
  deadlineMs?: number;
  /** How long the restarted server has to answer again (default 60 s). */
  upMs?: number;
}

const B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
export function base58(b: Uint8Array): string {
  let n = BigInt("0x" + (Buffer.from(b).toString("hex") || "0"));
  let s = "";
  while (n > 0n) { s = B58[Number(n % 58n)] + s; n /= 58n; }
  for (const x of b) { if (x !== 0) break; s = "1" + s; }
  return s;
}

/** The on-chain reference a payment is known by before anything settles: the first signature of a Solana
 *  transaction (base58), or the EIP-3009 authorization nonce of an EVM exact payment. */
export function paymentRef(payload: any): string {
  if (typeof payload?.authorization?.nonce === "string") return payload.authorization.nonce;
  if (typeof payload?.transaction === "string") {
    const raw = Buffer.from(payload.transaction, "base64");
    if (raw.length >= 65 && raw[0] >= 1) return base58(raw.subarray(1, 65));
    return createHash("sha256").update(raw).digest("hex");
  }
  return "";
}

function payloadFor(network: string, accepted: any): Record<string, unknown> {
  if (network.startsWith("eip155:")) {
    const now = Math.floor(Date.now() / 1000);
    return {
      signature: "0x" + randomBytes(65).toString("hex"),
      authorization: { from: "0x" + randomBytes(20).toString("hex"), to: accepted.payTo, value: accepted.amount,
        validAfter: String(now - 60), validBefore: String(now + Number(accepted.maxTimeoutSeconds ?? 60)),
        nonce: "0x" + randomBytes(32).toString("hex") },
    };
  }
  // A Solana wire transaction starts with the signature count (1) and the first signature: random bytes the double
  // never checks, but shaped so a server can derive the signature it will later find on chain.
  const tx = randomBytes(200);
  tx[0] = 1;
  return { transaction: tx.toString("base64") };
}

interface Answer { status: number; headers: Record<string, string>; body: string; error?: string; killed?: boolean }

let UA = userAgent("library");

/** One GET. With onFirstByte, the callback runs as the response headers arrive and the response is then discarded. */
function request(url: string, headers: Record<string, string>, timeoutMs: number,
    onFirstByte?: () => Promise<void>): Promise<Answer> {
  return new Promise((done) => {
    const u = new URL(url);
    const mod = u.protocol === "https:" ? https : http;
    let settled = false;
    const finish = (a: Answer) => { if (!settled) { settled = true; clearTimeout(timer); done(a); } };
    const rq = mod.request(u, { method: "GET", headers: { "user-agent": UA, ...headers }, agent: false }, (rs) => {
      const h: Record<string, string> = {};
      for (const [k, v] of Object.entries(rs.headers)) if (v !== undefined) h[k] = Array.isArray(v) ? v.join(", ") : v;
      if (onFirstByte) {
        onFirstByte().then(() => { rq.destroy(); finish({ status: rs.statusCode ?? 0, headers: h, body: "", killed: true }); },
          (e) => { rq.destroy(); finish({ status: 0, headers: h, body: "", error: `kill failed: ${e}` }); });
        return;
      }
      let body = "";
      rs.setEncoding("utf8");
      rs.on("data", (c: string) => { if (body.length < 65536) body += c; });
      rs.on("end", () => finish({ status: rs.statusCode ?? 0, headers: h, body }));
      rs.on("error", (e) => finish({ status: 0, headers: h, body, error: String(e) }));
    });
    const timer = setTimeout(() => { rq.destroy(); finish({ status: 0, headers: {}, body: "", error: "no answer by the deadline" }); }, timeoutMs);
    rq.on("error", (e) => finish({ status: 0, headers: {}, body: "", error: String(e.message ?? e) }));
    rq.end();
  });
}

async function waitUp(url: string, ms: number): Promise<boolean> {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const a = await request(url, {}, 2000);
    if (a.status > 0) return true;
    await new Promise((ok) => setTimeout(ok, 250));
  }
  return false;
}

function surfaced(a: Answer, tokens: string[]): string[] {
  let decoded = "";
  const pr = a.headers["payment-response"];
  if (pr) { try { decoded = JSON.stringify(decodePaymentResponseHeader(pr)); } catch { decoded = ""; } }
  const hay = a.body + "\n" + Object.values(a.headers).join("\n") + "\n" + decoded;
  return tokens.filter((t) => t && hay.includes(t));
}

const ok2xx = (s: number) => s >= 200 && s < 300;

async function crashAt(point: CrashPoint, url: string, double: Double, control: ServerControl,
    required: any, accepted: any, opts: Required<CrashOptions>): Promise<{ pass: boolean; ran: boolean; detail: Record<string, unknown> }> {
  const payload = payloadFor(accepted.network, accepted);
  const ref = paymentRef(payload);
  const advertised = required.extensions?.[PAYMENT_IDENTIFIER];
  const id = advertised ? "pay_" + randomBytes(16).toString("hex") : undefined;
  const extensions = advertised
    ? { [PAYMENT_IDENTIFIER]: { ...advertised, info: { ...(advertised.info ?? {}), required: !!advertised.info?.required, id } } }
    : undefined;
  const header = encodePaymentSignatureHeader({ x402Version: 2, resource: required.resource, accepted, payload,
    ...(extensions ? { extensions } : {}) } as any);
  const detail: Record<string, unknown> = { crash_after: point === "settle"
    ? "/settle committed, before it answered the server" : "/settle answered success, at the first byte of the response",
    payment_identifier: id ? "sent" : "not advertised by the server" };
  double.mode = "reference";
  const settledBefore = double.successes.length;
  let killed = false;
  let hook: Promise<void> | null = null;
  const kill = () => (hook ??= control.kill().then(() => { killed = true; }));
  if (point === "settle") double.onSettled = () => kill();
  const first = await request(url, { "PAYMENT-SIGNATURE": header }, opts.deadlineMs, point === "response"
    ? async () => { if (double.successes.length > settledBefore) await kill(); }
    : undefined);
  double.onSettled = undefined;
  // The client can see the connection drop before the kill has finished; wait for it.
  if (hook) { try { await hook; } catch (e) { first.error = `kill failed: ${e instanceof Error ? e.message : String(e)}`; } }
  const settledFirst = double.successes.slice(settledBefore);
  if (!killed) {
    detail.first_attempt = { status: first.status, error: first.error };
    detail.note = settledFirst.length === 0
      ? "the server answered without a successful /settle, so there was no settled payment to crash after; R1 shows why"
      : "the server could not be killed at the crash point";
    if (first.error?.startsWith("kill failed")) detail.note = first.error;
    return { pass: false, ran: false, detail };
  }
  detail.first_attempt = "no response (server killed)";
  const tx = settledFirst[0];
  try {
    await control.restart();
  } catch (e) {
    detail.note = `the restart failed: ${e instanceof Error ? e.message : String(e)}`;
    return { pass: false, ran: false, detail };
  }
  if (!await waitUp(url, opts.upMs)) {
    detail.note = `the restarted server did not answer within ${Math.round(opts.upMs / 1000)} s`;
    return { pass: false, ran: false, detail };
  }
  const callsBefore = double.calls.length;
  const again = await request(url, { "PAYMENT-SIGNATURE": header }, opts.deadlineMs);
  const settleCalls = double.calls.slice(callsBefore).filter((c) => c.path === "/settle").length;
  const settlements = double.successes.length - settledBefore;
  const tokens = [tx, id ?? "", ref];
  const found = surfaced(again, tokens);
  // A 402 is a request for payment: with a new challenge, or naming nothing the client already paid, it asks the
  // client to pay again for what it bought.
  const askedToPay = again.status === 402 && (!!again.headers["payment-required"] || found.length === 0);
  const delivered = ok2xx(again.status);
  const outcome = delivered ? "delivered" : askedToPay ? "asked to pay again"
    : found.length ? "refused, payment surfaced" : again.status === 0 ? "no answer" : "refused, nothing surfaced";
  Object.assign(detail, { settlements, settle_calls_after_restart: settleCalls,
    after_restart: { status: again.status, outcome, surfaced: found.map((t) => t === tx ? "transaction" : t === id ? "payment id" : "signature or nonce"),
      ...(again.error ? { error: again.error } : {}), ...(delivered ? {} : { body: again.body.slice(0, 300) }) } });
  const problems: string[] = [];
  if (settleCalls > 0) problems.push("it called /settle again for a payment that had already settled");
  if (settlements > 1) problems.push("the payment settled twice");
  if (askedToPay) problems.push("it answered 402 to a payment that had settled: the client is asked to pay again for what it bought");
  else if (!delivered && !found.length) problems.push("it refused without naming the transaction, payment id, signature or nonce, so nobody can reconcile the payment");
  if (problems.length) detail.problems = problems;
  return { pass: problems.length === 0, ran: true, detail };
}

/** Runs R14. The server at url must be up, pointed at double, and controlled by control. */
export async function probeCrash(url: string, double: Double, control: ServerControl, opts: CrashOptions = {}): Promise<Result[]> {
  UA = userAgent(opts.via ?? "library");
  const o: Required<CrashOptions> = { via: opts.via ?? "library", network: opts.network ?? "auto", deadlineMs: opts.deadlineMs ?? 30_000,
    upMs: opts.upMs ?? 60_000 };
  const want: readonly string[] = o.network === "auto" ? NETWORKS : [o.network];
  // Do not inherit a fault mode from a preceding probe when negotiating the unpaid 402.
  double.mode = "reference";
  const unpaid = await request(url, {}, o.deadlineMs);
  let required: any = null;
  try { required = unpaid.headers["payment-required"] ? decodePaymentRequiredHeader(unpaid.headers["payment-required"]) : null; }
  catch { required = null; }
  let accepted: any;
  for (const n of want) {
    accepted = required?.accepts?.find((a: any) => a.network === n && a.scheme === "exact");
    if (accepted) break;
  }
  if (unpaid.status !== 402 || !required || !accepted) {
    return [{ check: R14, pass: false, status: required && !accepted ? "unsupported" : "fail",
      detail: { status: unpaid.status, note: required && !accepted
        ? `no exact payment on ${DEVNET} or ${BASE_SEPOLIA} is offered; nothing was tested`
        : "the unpaid request did not get a decodable 402; R0 shows why" } }];
  }
  const points: Record<string, unknown> = {};
  let pass = true;
  for (const p of CRASH_POINTS) {
    const r = await crashAt(p, url, double, control, required, accepted, o);
    points[p] = r.detail;
    pass &&= r.pass;
    if (!r.ran) break;  // the crash could not be set up, or the server did not come back: the next point would not either
  }
  return [{ check: R14, pass, status: pass ? "pass" : "fail", detail: { graded_on: accepted.network, crash_points: points } }];
}

/** A server the probe starts itself with a shell command: kill() SIGKILLs its process group, restart() runs the
 *  command again with the same environment. An exit the probe did not cause is reported through unexpected(). */
export class SpawnedServer implements ServerControl {
  child: ChildProcess | null = null;
  private expecting = false;
  unexpectedExit: string | null = null;
  constructor(private cmd: string, private env: NodeJS.ProcessEnv, private stdio: "inherit" | "ignore" = "inherit") {}

  start(): void {
    this.expecting = false;
    this.unexpectedExit = null;
    const c = spawn(this.cmd, { shell: true, stdio: this.stdio, detached: true, env: this.env });
    this.child = c;
    c.on("exit", (code, sig) => {
      if (!this.expecting && this.child === c) this.unexpectedExit = `your server (--start) exited with ${sig ?? `code ${code}`}`;
    });
    c.on("error", (e) => { if (this.child === c) this.unexpectedExit = `your server (--start) could not start: ${e.message}`; });
  }

  async kill(): Promise<void> {
    const c = this.child;
    if (!c?.pid) return;
    this.expecting = true;
    if (c.exitCode !== null || c.signalCode !== null) return;
    const gone = new Promise<void>((ok) => c.once("exit", () => ok()));
    try { process.kill(-c.pid, "SIGKILL"); } catch { c.kill("SIGKILL"); }
    await gone;
  }

  async restart(): Promise<void> {
    await this.kill();
    this.start();
  }

  /** Stop for good (SIGTERM to the process group). */
  stop(): void {
    const c = this.child;
    this.expecting = true;
    if (!c?.pid || c.exitCode !== null || c.signalCode !== null) return;
    try { process.kill(-c.pid, "SIGTERM"); } catch { c.kill("SIGTERM"); }
  }
}

function run(cmd: string, what: string, timeoutMs: number, env: NodeJS.ProcessEnv): Promise<void> {
  return new Promise((ok, fail) => {
    const c = spawn(cmd, { shell: true, stdio: ["ignore", "ignore", "inherit"], env });
    const t = setTimeout(() => { c.kill("SIGKILL"); fail(new Error(`${what} did not finish within ${timeoutMs / 1000} s`)); }, timeoutMs);
    c.on("exit", (code, sig) => { clearTimeout(t); code === 0 ? ok() : fail(new Error(`${what} exited with ${sig ?? `code ${code}`}`)); });
    c.on("error", (e) => { clearTimeout(t); fail(e); });
  });
}

/** A server someone else runs: two shell commands, one that kills it hard (and returns once it is gone) and one that
 *  starts it again in the background (and returns). Both get X402_FACILITATOR_URL. */
export function commandControl(killCmd: string, restartCmd: string, env: NodeJS.ProcessEnv, timeoutMs = 60_000): ServerControl {
  return {
    kill: () => run(killCmd, "--crash-kill", timeoutMs, env),
    restart: () => run(restartCmd, "--crash-restart", timeoutMs, env),
  };
}
