#!/usr/bin/env node
// Publishes x402-conformance-mcp. In this repository the package depends on the core package beside it
// ("x402-conformance-svm": "file:.."), so its tests run against this checkout. A registry cannot serve that, so this
// script packs the package, names the core package's released range in the packed copy, and publishes the copy.
// The working tree is not changed.
//   npm run release -- [npm publish options]            --otp 123456, --tag next, --registry URL, --dry-run
//   node scripts/publish.mjs --stage DIR [--no-build]   writes DIR/package and DIR/<name>-<version>.tgz; publishes nothing
// Publish x402-conformance-svm first: this refuses when that version is not on the registry.
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { isRegistryRange, unservable } from "./manifest.mjs";

const HERE = fileURLToPath(new URL("..", import.meta.url));
const CORE = "x402-conformance-svm";
const args = process.argv.slice(2);
const fail = (msg) => { console.error(`publish: ${msg}`); process.exit(1); };
const npm = (argv, opts = {}) =>
  execFileSync("npm", argv, { cwd: HERE, encoding: "utf8", shell: process.platform === "win32", ...opts });
// Runs npm quietly and shows what it printed only when it fails (tsc reports errors on stdout).
const quiet = (argv) => {
  try { npm(argv, { stdio: ["ignore", "pipe", "pipe"] }); }
  catch (e) { fail(`npm ${argv[0]} failed:\n${e.stdout ?? ""}${e.stderr ?? ""}`); }
};

let stageOnly = false, stage, build = true;
if (args.includes("--stage")) {
  stageOnly = true;
  stage = args.splice(args.indexOf("--stage"), 2)[1];
  if (!stage || stage.startsWith("-")) fail("--stage needs a folder");
}
if (args.includes("--no-build")) { build = false; args.splice(args.indexOf("--no-build"), 1); }
stage = resolve(stage ?? mkdtempSync(join(tmpdir(), "x402-mcp-")));

// 1. Pack as npm would (prepack builds), into a folder of its own, and unpack it.
const raw = join(stage, "raw");
for (const d of ["raw", "package"]) rmSync(join(stage, d), { recursive: true, force: true });
mkdirSync(raw, { recursive: true });
quiet(["pack", "--pack-destination", raw, ...(build ? [] : ["--ignore-scripts"])]);
const [packed, ...more] = readdirSync(raw).filter((f) => f.endsWith(".tgz"));
if (!packed || more.length) fail(`expected one tarball in ${raw}`);
execFileSync("tar", ["-xzf", join(raw, packed), "-C", stage]);
rmSync(raw, { recursive: true });

// 2. In the copy, the core package is the released one.
const core = JSON.parse(readFileSync(join(HERE, "..", "package.json"), "utf8"));
if (core.name !== CORE) fail(`${join(HERE, "..", "package.json")} is ${core.name}, not ${CORE}`);
const file = join(stage, "package", "package.json");
const manifest = JSON.parse(readFileSync(file, "utf8"));
if (!manifest.dependencies?.[CORE]) fail(`${manifest.name} does not depend on ${CORE}`);
if (!isRegistryRange(manifest.dependencies[CORE])) manifest.dependencies[CORE] = `^${core.version}`;
const bad = unservable(manifest);
if (bad.length) fail(`a registry cannot serve these dependencies:\n  ${bad.join("\n  ")}`);
writeFileSync(file, JSON.stringify(manifest, null, 2) + "\n");
const id = `${manifest.name}@${manifest.version}`;

// 3. The tarball that is published, and that CI installs in an empty folder.
quiet(["pack", join(stage, "package"), "--ignore-scripts", "--pack-destination", stage]);
const tarball = join(stage, packed);
console.log(`${id}: ${CORE} ${manifest.dependencies[CORE]}\n${tarball}`);
if (stageOnly) process.exit(0);

// 4. Publish, then read it back from the registry and install it as a user does.
const dry = args.includes("--dry-run");
let onRegistry = "";
try { onRegistry = npm(["view", `${CORE}@${core.version}`, "version", ...args], { stdio: ["ignore", "pipe", "ignore"] }).trim(); } catch { /* not there */ }
if (onRegistry !== core.version) fail(`${CORE}@${core.version} is not on the registry: publish it first, then run this again`);
npm(["publish", tarball, ...args], { stdio: "inherit" });
if (dry) process.exit(0);
const reg = args.flatMap((a, i) => (a === "--registry" || a === "--userconfig") ? [a, args[i + 1]] : /^--(registry|userconfig)=/.test(a) ? [a] : []);
const node = (argv) => execFileSync(process.execPath, argv, { cwd: HERE, stdio: "inherit" });
for (let attempt = 1; ; attempt++) {
  try {
    const deps = JSON.parse(npm(["view", id, "dependencies", "--json", ...reg], { stdio: ["ignore", "pipe", "ignore"] }));
    const served = unservable({ dependencies: deps });
    if (served.length) fail(`${id} is published, and the registry lists ${served.join(", ")}. Deprecate it and publish a fixed version.`);
    node([join(HERE, "scripts", "verify-install.mjs"), id, ...reg]);
    break;
  } catch (e) {
    if (attempt === 6) fail(`${id} is published, but it did not install from the registry: ${e.message}`);
    console.error(`publish: ${id} is not readable from the registry yet (attempt ${attempt} of 6), waiting 10 s`);
    await new Promise((ok) => setTimeout(ok, 10_000));
  }
}
console.log(`published and installed from the registry: ${id}`);
