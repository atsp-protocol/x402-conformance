// A paid MCP tool on a live server, unpaid: X1 on the tool result, then P3, P4, P5 and P7 on the PaymentRequired it
// carries (the same object a 402 carries in PAYMENT-REQUIRED; P1, P2 and P6 are about the HTTP 402 and its header and
// do not apply). One tools/call, or three with initialize. Nothing is paid or signed.
import { unpaidToolCall, type McpOptions, type McpTarget, type RpcAnswer } from "./mcp-transport.js";
import { check402, P3, P4, P5, P7 } from "./resource.js";
import type { CheckResult } from "./report.js";
import type { Result } from "./probe.js";

const OFFER_CHECKS = new Set([P3, P4, P5, P7]);
const obj = (v: unknown): v is Record<string, any> => !!v && typeof v === "object" && !Array.isArray(v);

/** The PaymentRequired in an unpaid tool result: structuredContent, else the JSON in content[0].text. */
export function offerOf(a: RpcAnswer | null): Record<string, any> | null {
  const r = a?.result;
  if (obj(r?.structuredContent)) return r.structuredContent;
  try { const p = JSON.parse(r?.content?.[0]?.text ?? ""); return obj(p) ? p : null; } catch { return null; }
}

/** Grade the offer in a tool result with the HTTP offer checks P3, P4, P5 and P7. Pure: no network. */
export function checkMcpOffer(pr: Record<string, any>): CheckResult[] {
  const header = Buffer.from(JSON.stringify(pr), "utf8").toString("base64");
  return check402({ status: 402, headers: { "payment-required": header }, body: "" })
    .filter((c) => OFFER_CHECKS.has(c.check))
    .map((c) => ({ ...c, detail: { transport: "mcp", ...(obj(c.detail) ? c.detail : { value: c.detail }) } }));
}

/** X1, then the offer checks when the tool answered with an offer. */
export async function checkMcpSeller(target: McpTarget, opts: McpOptions = {}): Promise<Result[]> {
  const { results, answer } = await unpaidToolCall(target, opts);
  const pr = offerOf(answer);
  return pr ? [...results, ...(checkMcpOffer(pr) as Result[])] : results;
}
