// The tools, defined once and shared by the MCP server, the Vercel AI SDK adapter and the LangChain adapter. Each one
// is a thin call into x402-conformance-svm: the same checks, the same report, the same corpus. None of them pays,
// signs, or sends anything anywhere except the requests the tool's description names.
import { readFileSync } from "node:fs";
import { z } from "zod";
import {
  anonymise, checkPaymentRequired, explain, funnelFooter, LINKS, makeReport, probe, shareUrl, startDouble,
  NETWORKS, type Double, type Report, type Via,
} from "x402-conformance-svm";
import { startDemoServer } from "./demo.js";

export interface ToolDef<S extends z.ZodRawShape = z.ZodRawShape> {
  name: string;
  title: string;
  description: string;
  input: S;
  readOnly: boolean;
  run: (args: z.infer<z.ZodObject<S>>, via: Via) => Promise<ToolOutput>;
}
export interface ToolOutput { text: string; data: unknown }

const LOOPBACK = new Set(["127.0.0.1", "localhost", "[::1]"]);
const isLoopback = (u: string) => { try { return LOOPBACK.has(new URL(u).hostname); } catch { return false; } };
const isHttp = (u: string) => { try { return ["http:", "https:"].includes(new URL(u).protocol); } catch { return false; } };

function out(report: Report): ToolOutput {
  return { text: `${explain(report)}\n\n${funnelFooter(report)}\n\n${JSON.stringify(report, null, 1)}`, data: report };
}

let double: Double | null = null;

const fixesPath = new URL("../FIXES.md", import.meta.url);
function fixSection(id: string): string | null {
  let md: string;
  try { md = readFileSync(fixesPath, "utf8"); } catch { return null; }
  const re = new RegExp(`^## ${id.replace(/[^A-Za-z0-9]/g, "")}\\s*$([\\s\\S]*?)(?=^## |$(?![\\s\\S]))`, "mi");
  const m = md.match(re);
  return m ? `## ${id}\n${m[1].trim()}` : null;
}

export const checkPaymentRequiredTool: ToolDef<{ url: z.ZodString }> = {
  name: "x402_check_payment_required",
  title: "Check an x402 402 answer (P1-P7)",
  description: "Sends ONE unpaid GET to an x402 paid URL and checks its 402 answer against the x402 spec (P1-P7): HTTP " +
    "402, a decodable PAYMENT-REQUIRED header (V2) or JSON body (V1), x402Version, resource, accepts[], amounts in " +
    "atomic units, CAIP-2 networks, and scheme fields (EVM name/version, Solana feePayer). Never pays or signs. Use " +
    "it before paying an unfamiliar x402 endpoint, or to check your own route.",
  input: { url: z.string().describe("The paid URL, http or https") },
  readOnly: true,
  async run({ url }, via) {
    if (!isHttp(url)) throw new Error("url must be an http or https URL");
    return out(await checkPaymentRequired(url, { via }));
  },
};

export const startDoubleTool: ToolDef<{ port: z.ZodOptional<z.ZodNumber> }> = {
  name: "x402_start_facilitator_double",
  title: "Start the facilitator double",
  description: "Starts the x402 facilitator double on 127.0.0.1 and returns its URL. Start YOUR resource server with " +
    "this URL as its facilitator (for example X402_FACILITATOR_URL) and offering Solana devnet or Base Sepolia, then " +
    "call x402_probe_resource_server. The double never touches a chain, key or network beyond loopback.",
  input: { port: z.number().int().min(0).max(65535).optional().describe("Loopback port; 0 or omitted picks a free one") },
  readOnly: false,
  async run({ port }) {
    if (double) return { text: `The facilitator double is already running at ${double.url}`, data: { url: double.url } };
    double = await startDouble(port ?? 0);
    return { text: `Facilitator double running at ${double.url}. Start your server with X402_FACILITATOR_URL=${double.url}, ` +
      "then call x402_probe_resource_server with your paid route.", data: { url: double.url } };
  },
};

export const probeTool: ToolDef<{ resource_url: z.ZodString; network: z.ZodOptional<z.ZodEnum<any>> }> = {
  name: "x402_probe_resource_server",
  title: "Probe your resource server (R0-R10)",
  description: "Grades your x402 resource server under fault injection (R0-R10): it must never serve content on a " +
    "/settle timeout, an HTML 502, a 503 with a success body, a non-JSON or truncated answer, settlement_pending, a " +
    "failed transaction or a duplicate payment. Pays with test payloads through the facilitator double only; the URL " +
    "must be on loopback and your server must use the double (x402_start_facilitator_double) as its facilitator.",
  input: {
    resource_url: z.string().describe("Your paid route on loopback, e.g. http://127.0.0.1:4020/paid"),
    network: z.enum(["auto", ...NETWORKS] as [string, ...string[]]).optional().describe("Network to pay on; default auto"),
  },
  readOnly: false,
  async run({ resource_url, network }, via) {
    if (!isLoopback(resource_url)) throw new Error("resource_url must be on loopback (127.0.0.1 or localhost): the probe only grades a server you run against the double");
    if (!double) throw new Error("start the facilitator double first (x402_start_facilitator_double) and point your server at it");
    const results = await probe(resource_url, double, { network: (network ?? "auto") as any, via });
    return out(makeReport("resource-server", resource_url, results, via));
  },
};

export const stopDoubleTool: ToolDef<{}> = {
  name: "x402_stop_facilitator_double",
  title: "Stop the facilitator double",
  description: "Stops the facilitator double started by x402_start_facilitator_double.",
  input: {},
  readOnly: false,
  async run() {
    if (!double) return { text: "No facilitator double is running.", data: { stopped: false } };
    await double.close();
    double = null;
    return { text: "Facilitator double stopped.", data: { stopped: true } };
  },
};

export const demoTool: ToolDef<{ fault: z.ZodOptional<z.ZodEnum<any>> }> = {
  name: "x402_demo",
  title: "Run the suite end to end on a built-in demo server",
  description: "Runs P1-P7 and R0-R10 against a built-in demo x402 server on loopback, with no wallet, no keys and no " +
    "network. fault=serve_on_any_settle shows what a failing server looks like. Use it to see what the suite checks.",
  input: { fault: z.enum(["none", "serve_on_any_settle"]).optional().describe("none (default) or serve_on_any_settle") },
  readOnly: true,
  async run({ fault }, via) {
    const d = await startDouble(0);
    const srv = await startDemoServer(d.url, (fault ?? "none") as any);
    try {
      const p = await checkPaymentRequired(srv.url, { via });
      const r = await probe(srv.url, d, { via, deadlineMs: 20_000 });
      const report = makeReport("resource-server", srv.url, [...p.results, ...r], via);
      return out(report);
    } finally {
      await srv.close();
      await d.close();
    }
  },
};

export const explainTool: ToolDef<{ id: z.ZodString }> = {
  name: "x402_explain_check",
  title: "Explain a check and how to fix it",
  description: "Returns what a check (S0-S4, P1-P7, F1-F11, R0-R11) tests, why it matters for the seller's money, and " +
    "how to fix a failure, from the suite's FIXES.md.",
  input: { id: z.string().regex(/^[A-Za-z]{1,2}[0-9X]{0,2}[a-z]?$/).describe("Check id, e.g. R3 or P5") },
  readOnly: true,
  async run({ id }) {
    const s = fixSection(id);
    if (!s) throw new Error(`no check ${id}; see ${LINKS.fixes}`);
    return { text: `${s}\n\nFull text: ${LINKS.fixes}#${id.toLowerCase()}`, data: { id, text: s } };
  },
};

const reportShape = z.object({ schema: z.literal("x402-conformance.report/1") }).passthrough();
export const shareTool: ToolDef<{ report: typeof reportShape; framework: z.ZodOptional<z.ZodString>;
    sdk: z.ZodOptional<z.ZodString>; sdk_version: z.ZodOptional<z.ZodString>; network: z.ZodOptional<z.ZodString> }> = {
  name: "x402_share_case",
  title: "Prepare an anonymised corpus case",
  description: "Turns a failing report into an anonymised case for the public x402 failure corpus (no URLs, hosts, IPs, " +
    "addresses or transaction data) and returns a link to a pre-filled GitHub issue. Sends nothing: show the case and " +
    "the link to the user, who decides whether to submit it.",
  input: { report: reportShape.describe("A report returned by another x402 tool"),
    framework: z.string().max(80).optional(), sdk: z.string().max(80).optional(), sdk_version: z.string().max(40).optional(),
    network: z.string().max(80).optional() },
  readOnly: true,
  async run({ report, framework, sdk, sdk_version, network }) {
    const c = anonymise(report as unknown as Report, { framework, sdk, sdk_version, network });
    const link = shareUrl(c);
    return { text: link ? `Anonymised case below. Review it with the user; if they agree, they open this link and submit ` +
      `it themselves (nothing was sent):\n${link}\n\n${JSON.stringify(c, null, 1)}`
      : "Nothing failed in this report, so there is no case to share.", data: { case: c, share_url: link } };
  },
};

/** Every tool, for the MCP server. */
export const ALL_TOOLS: ToolDef<any>[] = [checkPaymentRequiredTool, demoTool, explainTool, shareTool, startDoubleTool,
  probeTool, stopDoubleTool];
/** The tools safe to give an autonomous agent: read-only, no listener, no shell. */
export const AGENT_TOOLS: ToolDef<any>[] = [checkPaymentRequiredTool, demoTool, explainTool, shareTool];

export async function shutdown(): Promise<void> {
  if (double) { await double.close(); double = null; }
}
