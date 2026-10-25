// P1-P7: the 402 answer of any paid URL, from one unpaid GET. Nothing is paid or signed. This is the TypeScript port of
// check_402 in src/x402conf/harness.py, with the same check IDs and names; test/resource.test.ts runs both on the same
// answers and fails if they ever disagree.
import { makeReport, userAgent, type CheckResult, type Report, type Via } from "./report.js";

export const P1 = "P1 an unpaid GET answers HTTP 402 (V2 HTTP transport)";
export const P2 = "P2 the PaymentRequired object is present and decodes (V2: base64 JSON in PAYMENT-REQUIRED; V1: JSON body)";
export const P3 = "P3 PaymentRequired has x402Version, resource and a non-empty accepts[] (V2 5.1.2; V1 5.1)";
export const P4 = "P4 every accepts[] entry has the required fields with valid types (V2 5.1.2; V1 5.1)";
export const P5 = "P5 scheme-specific extra fields are present (EVM exact: name and version; SVM exact: feePayer)";
export const P6 = "P6 the PAYMENT-REQUIRED header fits common client limits (warning above 8 KB, error above 16 KB)";
export const P7 = "P7 an accepts[] entry whose payment flow is not authorization declares extra.paymentFlow (V2 6.1)";
export const HEADER_WARN = 8 * 1024, HEADER_ERROR = 16 * 1024;
/** Scheme and network prefixes whose default payment flow is not authorization, as in harness.py. */
const NON_AUTHORIZATION_DEFAULTS: [string, string][] = [["upto", "solana:"]];

const CAIP2 = /^[-a-z0-9]{3,8}:[-_a-zA-Z0-9]{1,32}$/;
const DIGITS = /^[0-9]+$/;
const SOLANA_V1 = new Set(["solana", "solana-devnet", "solana-mainnet", "solana-testnet"]);
const EVM_V1 = new Set(["base", "base-sepolia", "avalanche", "avalanche-fuji", "polygon", "polygon-amoy", "ethereum",
  "sepolia", "iotex", "sei", "sei-testnet"]);
const B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
const MAX_BYTES = 1 << 20;

export interface Answer { status: number; headers: Record<string, string>; body: string }

function b58len(s: string): number {
  let n = 0n;
  for (const ch of s) {
    const i = B58.indexOf(ch);
    if (i < 0) return -1;
    n = n * 58n + BigInt(i);
  }
  const lead = s.length - s.replace(/^1+/, "").length;
  return lead + (n === 0n ? 0 : Math.ceil(n.toString(16).length / 2));
}
export const isSolanaPubkey = (s: unknown): boolean =>
  typeof s === "string" && s.length >= 32 && s.length <= 44 && b58len(s) === 32;

function decodeHeader(v: string): unknown {
  const s = v + "=".repeat((4 - (v.length % 4)) % 4);
  if (/^[A-Za-z0-9+/]*={0,3}$/.test(s)) return JSON.parse(Buffer.from(s, "base64").toString("utf8"));
  if (/^[A-Za-z0-9_-]*={0,3}$/.test(s)) return JSON.parse(Buffer.from(s, "base64url").toString("utf8"));
  throw new Error("Error");
}

const obj = (x: unknown): x is Record<string, any> => typeof x === "object" && x !== null && !Array.isArray(x);
const str = (x: unknown): x is string => typeof x === "string" && x.length > 0;

function acceptProblems(a: unknown, version: number): string[] {
  if (!obj(a)) return ["entry is not an object"];
  const p: string[] = [];
  const amountKey = version === 2 ? "amount" : "maxAmountRequired";
  for (const k of ["scheme", "network", "asset", "payTo"]) if (!str(a[k])) p.push(`${k} missing or not a non-empty string`);
  const amt = a[amountKey];
  if (!(typeof amt === "string" && DIGITS.test(amt) && BigInt(amt) > 0n)) {
    p.push(`${amountKey} must be a string of atomic units greater than 0`);
  }
  const mts = a.maxTimeoutSeconds;
  if (!(typeof mts === "number" && Number.isInteger(mts) && mts > 0)) p.push("maxTimeoutSeconds must be a positive integer");
  if ("extra" in a && a.extra !== null && a.extra !== undefined && !obj(a.extra)) p.push("extra must be an object");
  if (version === 2 && typeof a.network === "string" && !CAIP2.test(a.network)) p.push("network is not CAIP-2");
  if (version === 1) for (const k of ["resource", "description"]) if (typeof a[k] !== "string") p.push(`${k} missing (required in V1)`);
  return p;
}

function extraProblems(a: Record<string, any>): string[] {
  const net = String(a.network ?? "");
  const extra = a.extra ?? {};
  if (a.scheme !== "exact" || !obj(extra)) return [];
  if (net.startsWith("eip155:") || EVM_V1.has(net)) {
    const method = extra.assetTransferMethod ?? "eip3009";
    if (method === "eip3009" && !(typeof extra.name === "string" && typeof extra.version === "string")) {
      return ["EVM exact (eip3009) needs extra.name and extra.version, the token's EIP-712 domain"];
    }
    if (!["eip3009", "permit2", "erc7710"].includes(method)) {
      return [`EVM exact extra.assetTransferMethod '${method}' is not eip3009, permit2 or erc7710`];
    }
  }
  if (net.startsWith("solana:") || SOLANA_V1.has(net)) {
    if (!isSolanaPubkey(extra.feePayer)) return ["SVM exact needs extra.feePayer, a 32-byte base58 key"];
  }
  return [];
}

const r = (check: string, pass: boolean, detail: unknown, severity: "error" | "warning" = "error"): CheckResult =>
  ({ check, pass, status: pass ? "pass" : "fail", severity, detail });

/** Grade one unpaid answer. Pure: no network. */
export function check402(resp: Answer): CheckResult[] {
  const out: CheckResult[] = [r(P1, resp.status === 402, { http: resp.status })];
  if (resp.status !== 402) return out;
  let pr: unknown = null;
  let where: string | null = null, err: string | null = null;
  const hv = resp.headers["payment-required"];
  if (hv) {
    where = "PAYMENT-REQUIRED header";
    try { pr = decodeHeader(hv.trim()); } catch (e) {
      err = `header does not decode as base64 JSON: ${e instanceof SyntaxError ? "JSONDecodeError" : "Error"}`;
    }
  } else {
    let body: unknown = null;
    try { body = JSON.parse(resp.body || "null"); } catch { body = null; }
    if (obj(body) && body.x402Version === 1) { where = "JSON body (V1)"; pr = body; }
    else err = "no PAYMENT-REQUIRED header, and the body is not a V1 PaymentRequired";
  }
  out.push(r(P2, obj(pr), { found_in: where, error: err }));
  if (hv) {
    const size = Buffer.byteLength(hv, "utf8");
    out.push(r(P6, size <= HEADER_WARN, { bytes: size, warn_above: HEADER_WARN, error_above: HEADER_ERROR },
      size > HEADER_ERROR ? "error" : "warning"));
  }
  if (!obj(pr)) return out;
  const version = pr.x402Version;
  const accepts = pr.accepts;
  const probs: string[] = [];
  if (version !== 1 && version !== 2) probs.push(`x402Version is ${JSON.stringify(version) ?? "None"}, not 1 or 2`);
  if (version === 2 && !(obj(pr.resource) && typeof pr.resource.url === "string")) probs.push("resource.url missing (V2 ResourceInfo)");
  if (version === 2 && where !== "PAYMENT-REQUIRED header") probs.push("V2 carries PaymentRequired in the PAYMENT-REQUIRED header");
  const hasAccepts = Array.isArray(accepts) && accepts.length > 0;
  if (!hasAccepts) probs.push("accepts[] missing or empty");
  out.push(r(P3, probs.length === 0, { x402Version: version ?? null, problems: probs }));
  if ((version !== 1 && version !== 2) || !hasAccepts) return out;
  const entries = (accepts as unknown[]).map((a, i) => ({ index: i, scheme: obj(a) ? a.scheme ?? null : null,
    network: obj(a) ? a.network ?? null : null, problems: acceptProblems(a, version) }));
  const bad = entries.filter((e) => e.problems.length);
  out.push(r(P4, bad.length === 0, { accepts: entries.length, problems: bad.slice(0, 10) }));
  const xb = (accepts as unknown[]).flatMap((a, i) => {
    if (!obj(a)) return [];
    const pp = extraProblems(a);
    return pp.length ? [{ index: i, network: a.network ?? null, problems: pp }] : [];
  });
  out.push(r(P5, xb.length === 0, { problems: xb.slice(0, 10) }));
  if (version === 2) {
    const flow: { index: number; problem: string }[] = [];
    (accepts as unknown[]).forEach((a, i) => {
      if (!obj(a)) return;
      const extra = obj(a.extra) ? a.extra : {};
      const pf = extra.paymentFlow;
      if (pf !== undefined && pf !== null && !str(pf)) {
        flow.push({ index: i, problem: "extra.paymentFlow is present but not a non-empty string" });
      } else if ((pf === undefined || pf === null) &&
          NON_AUTHORIZATION_DEFAULTS.some(([sc, net]) => a.scheme === sc && String(a.network ?? "").startsWith(net))) {
        flow.push({ index: i, problem: `${a.scheme} on ${a.network} defaults to a non-authorization flow, so V2 6.1 ` +
          "requires extra.paymentFlow" });
      }
    });
    // A warning: the upto SVM scheme spec lets paymentFlow be omitted, while V2 6.1 says it MUST be present.
    out.push(r(P7, flow.length === 0, { problems: flow.slice(0, 10) }, "warning"));
  }
  return out;
}

/** One unpaid GET. Redirects are followed, as the Python CLI does. */
export async function fetch402(url: string, opts: { timeoutMs?: number; via?: Via; fetch?: typeof fetch } = {}):
    Promise<Answer> {
  const res = await (opts.fetch ?? fetch)(url, { method: "GET", headers: { accept: "application/json", "user-agent": userAgent(opts.via) },
    signal: AbortSignal.timeout(opts.timeoutMs ?? 15_000) });
  const headers: Record<string, string> = {};
  res.headers.forEach((v, k) => { headers[k.toLowerCase()] = v; });
  const buf = Buffer.from(await res.arrayBuffer()).subarray(0, MAX_BYTES);
  return { status: res.status, headers, body: buf.toString("utf8") };
}

/** P1-P7 against a URL: one unpaid GET, never a payment. */
export async function checkPaymentRequired(url: string, opts: { timeoutMs?: number; via?: Via; fetch?: typeof fetch } = {}):
    Promise<Report> {
  const via = opts.via ?? "library";
  try {
    return makeReport("resource-402", url, check402(await fetch402(url, opts)), via);
  } catch (e) {
    const msg = String(e instanceof Error ? e.message : e).slice(0, 200);
    return makeReport("resource-402", url, [r(P1, false, { error: msg })], via);
  }
}
