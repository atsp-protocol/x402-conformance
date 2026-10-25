// The one report format every entry point emits: the CLI, the Action, the test-framework matchers, the MCP server,
// the agent tools and the Docker image. Same check IDs, same fields, so a result from any of them is comparable with
// any other and can become a corpus case unchanged.
import { readFileSync } from "node:fs";
import { CATALOG } from "./catalog.js";
import { provenance, type Provenance } from "./provenance.js";

export const VERSION: string = JSON.parse(readFileSync(new URL("../../package.json", import.meta.url), "utf8")).version;
export const REPO = "https://github.com/atsp-protocol/x402-conformance";
export const LINKS = {
  repo: REPO,
  fixes: `${REPO}/blob/main/docs/FIXES.md`,
  corpus: `${REPO}/tree/main/corpus`,
  contribute: `${REPO}/issues/new?template=corpus-case.yml`,
  using: `${REPO}/blob/main/docs/USING.md`,
  badge: `[![Tested with x402-conformance](https://img.shields.io/badge/tested%20with-x402--conformance-2ea44f)](${REPO})`,
} as const;
export const REPORT_SCHEMA = "x402-conformance.report/1";

/**
 * Which entry point produced a run. It goes into the User-Agent and the report, and nowhere else: no machine id, no
 * user id, nothing is sent anywhere by default. It lets public signals (shared corpus cases, committed reports) be
 * counted per ecosystem.
 */
export type Via = "cli-ts" | "cli-py" | "action" | "testing" | "vitest" | "jest" | "node-test" | "mcp" | "ai-sdk"
  | "langchain" | "pytest" | "docker" | "gitlab" | "library";
export const VIAS: readonly Via[] = ["cli-ts", "cli-py", "action", "testing", "vitest", "jest", "node-test", "mcp",
  "ai-sdk", "langchain", "pytest", "docker", "gitlab", "library"];

export function userAgent(via: Via = "library"): string {
  return `x402-conformance/${VERSION} (+${REPO}; via=${via})`;
}

export type Severity = "error" | "warning";
export type Status = "pass" | "fail" | "unsupported" | "not_applicable";
export interface CheckResult {
  check: string; pass: boolean; status: Status; severity: Severity; detail: unknown;
  /** Evidence v2 labels from spec.CATALOG: normative, security-profile or resilience, and the spec basis. */
  profile?: string; basis?: string;
}
export type Kind = "resource-402" | "resource-server" | "facilitator-supported" | "self-test";

export interface Report {
  schema: typeof REPORT_SCHEMA;
  tool: string;
  version: string;
  via: Via;
  kind: Kind;
  run_at: string;
  target: string;
  /** Who made the tool that wrote this report (XC-95). */
  provenance: Provenance;
  results: CheckResult[];
  summary: { checks: number; failed: number; failed_ids: string[]; unsupported: boolean; not_applicable?: string[] };
  error?: string;
  links: typeof LINKS;
}

/** The ID at the start of a check name, e.g. "P4" or "R11a". */
export const checkId = (check: string): string => check.split(" ")[0];
export const fixUrl = (id: string): string => `${LINKS.fixes}#${id.toLowerCase()}`;

export function normalise(r: { check: string; pass: boolean; status?: Status; severity?: Severity; detail?: unknown }):
    CheckResult {
  const e = CATALOG[checkId(r.check).replace(/:$/, "")];
  return { check: r.check, pass: r.pass, status: r.status ?? (r.pass ? "pass" : "fail"),
    severity: r.severity ?? "error", detail: r.detail ?? null, ...(e ? { profile: e.profile, basis: e.basis } : {}) };
}

export function makeReport(kind: Kind, target: string, results: Array<Parameters<typeof normalise>[0]>,
    via: Via = "library", error?: string): Report {
  const rs = results.map(normalise);
  const failed = rs.filter((r) => !r.pass && r.status !== "unsupported" && r.status !== "not_applicable");
  const na = rs.filter((r) => r.status === "not_applicable").map((r) => checkId(r.check));
  return {
    schema: REPORT_SCHEMA, tool: "x402-conformance-svm", version: VERSION, via, kind, run_at: new Date().toISOString(),
    target, provenance: provenance(VERSION), results: rs,
    summary: { checks: rs.length, failed: failed.length, failed_ids: failed.map((r) => checkId(r.check)),
      unsupported: rs.some((r) => r.status === "unsupported"), ...(na.length ? { not_applicable: na } : {}) },
    ...(error ? { error } : {}), links: LINKS,
  };
}

/** True when nothing failed at error severity and the run completed. Warnings never fail. */
export const passed = (r: Report): boolean =>
  !r.error && !r.summary.unsupported
    && r.results.every((x) => x.pass || x.severity === "warning" || x.status === "not_applicable");

/** A short human summary ending with where to go next. Used by every integration's failure message. */
export function explain(r: Report): string {
  const lines = [`x402-conformance ${r.version} (${r.kind}, via ${r.via}) on ${r.target}: ` +
    (r.error ? `could not complete: ${r.error}` : `${r.summary.checks} checks, ${r.summary.failed} failed`
      + (r.summary.not_applicable?.length ? `, ${r.summary.not_applicable.length} not applicable` : ""))];
  for (const x of r.results.filter((x) => x.status === "not_applicable")) {
    lines.push(`  N/A ${x.check}`);
    lines.push(`    why: ${JSON.stringify((x.detail as any)?.reason ?? x.detail).slice(0, 300)}`);
  }
  for (const x of r.results.filter((x) => !x.pass && x.status !== "not_applicable")) {
    lines.push(`  ${x.status === "unsupported" ? "UNSUPPORTED" : x.severity.toUpperCase()} ${x.check}`);
    lines.push(`    detail: ${JSON.stringify(x.detail).slice(0, 300)}`);
    lines.push(`    how to fix: ${fixUrl(checkId(x.check))}`);
  }
  if (r.summary.failed) {
    lines.push(`Think this failure is real and new? Share an anonymised case (opt-in): ${LINKS.contribute}`);
    lines.push(`False positive? ${LINKS.repo}/issues/new?template=false-positive.yml`);
  }
  return lines.join("\n");
}
