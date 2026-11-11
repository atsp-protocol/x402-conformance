#!/usr/bin/env node
// Installs x402-conformance-mcp the way a user does and loads it: an empty folder, `npm init -y`, `npm install`.
//   node scripts/verify-install.mjs x402-conformance-mcp@1.6.1        from the registry
//   node scripts/verify-install.mjs core.tgz mcp.tgz                  from packed tarballs, before a release
// Options (--registry URL, --userconfig FILE) go to npm install. Exits 1 at the first thing that does not work.
import { execFileSync, spawn } from "node:child_process";
import { lstatSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { unservable } from "./manifest.mjs";

const NAME = "x402-conformance-mcp", CORE = "x402-conformance-svm";
const args = process.argv.slice(2);
const opts = args.filter((a, i) => a.startsWith("--") || (i > 0 && /^--(registry|userconfig)$/.test(args[i - 1])));
const specs = args.filter((a) => !opts.includes(a)).map((s) => (s.endsWith(".tgz") ? resolve(s) : s));
if (!specs.length) { console.error("usage: verify-install.mjs <package spec or tarball>... [--registry URL]"); process.exit(1); }

const dir = mkdtempSync(join(tmpdir(), "x402-mcp-install-"));
const run = (cmd, argv) => execFileSync(cmd, argv, { cwd: dir, encoding: "utf8", shell: cmd === "npm" && process.platform === "win32" });
const load = (code) => run(process.execPath, ["--input-type=module", "-e", code]).trim();
const step = async (what, fn) => {
  try { await fn(); console.log(`ok    ${what}`); }
  catch (e) { console.error(`FAIL  ${what}\n${String(e.stderr ?? e.message ?? e).trim()}\n(left in ${dir})`); process.exit(1); }
};

let manifest;
await step(`npm install ${specs.join(" ")} in an empty folder`, () => {
  run("npm", ["init", "-y"]);
  run("npm", ["install", ...specs, ...opts, "--no-audit", "--no-fund"]);
  manifest = JSON.parse(readFileSync(join(dir, "node_modules", NAME, "package.json"), "utf8"));
});
await step(`${NAME}@${manifest.version} names only dependencies a registry can serve`, () => {
  const bad = unservable(manifest);
  if (bad.length) throw new Error(bad.join("\n"));
  if (lstatSync(join(dir, "node_modules", CORE)).isSymbolicLink()) throw new Error(`${CORE} is a link, not an installed package`);
});
await step("the command prints its version", () => {
  const v = run(join(dir, "node_modules", ".bin", NAME), ["--version"]).trim();
  if (v !== manifest.version) throw new Error(`--version printed ${v}, the package is ${manifest.version}`);
});
await step(`import "${NAME}"`, () => {
  const out = load(`const m = await import("${NAME}"); console.log(typeof m.createServer, m.ALL_TOOLS.length, m.VERSION);`);
  if (!out.startsWith("function ") || !out.endsWith(` ${manifest.version}`)) throw new Error(`unexpected exports: ${out}`);
});
await step("the server answers initialize on stdio", () => new Promise((ok, no) => {
  const child = spawn(join(dir, "node_modules", ".bin", NAME), [], { cwd: dir, shell: process.platform === "win32" });
  let out = "";
  const timer = setTimeout(() => { child.kill(); no(new Error(`no answer in 30 s; got: ${out}`)); }, 30_000);
  child.stdout.on("data", (d) => {
    out += d;
    if (out.includes('"name":"x402-conformance"')) { clearTimeout(timer); child.stdin.end(); ok(); }
  });
  child.on("error", no);
  child.stdin.write(JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize",
    params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "verify-install", version: "0" } } }) + "\n");
}));
// The two tool entry points need their optional peer; install the versions this release was tested with.
for (const [entry, peer] of [["ai-sdk", "ai"], ["langchain", "@langchain/core"]]) {
  const tested = manifest.devDependencies?.[peer], spec = tested ? `${peer}@${tested}` : peer;
  await step(`import "${NAME}/${entry}" with ${spec}`, () => {
    run("npm", ["install", spec, ...opts, "--no-audit", "--no-fund"]);
    const out = load(`const m = await import("${NAME}/${entry}"); const t = m.x402ConformanceTools(); console.log(Array.isArray(t) ? t.length : Object.keys(t).length);`);
    if (!(Number(out) > 0)) throw new Error(`x402ConformanceTools() returned no tools: ${out}`);
  });
}
rmSync(dir, { recursive: true, force: true });
console.log(`${NAME}@${manifest.version} installs and loads`);
