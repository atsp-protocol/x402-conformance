#!/usr/bin/env node
// Which dependencies a registry can serve. One written as file:, link:, workspace:, a git or http URL, a path or a
// dist-tag installs only where it was published from: 1.6.0 went out with "x402-conformance-svm": "file:.." and could
// not be installed. This is the package's prepublishOnly script, so `npm publish` in this folder stops here.
//   node scripts/manifest.mjs [package.json]     exits 1 and names each dependency a registry cannot serve
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const FIELDS = ["dependencies", "optionalDependencies", "peerDependencies"];
// One comparator of a semver range: 1.2.3, ^1.2.3, ~1.2, >=1.0.0, 1.x, *
const COMPARATOR = /^(?:[\^~]|[<>]=?|=)?v?(?:\d+|[xX*])(?:\.(?:\d+|[xX*])){0,2}(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/;

// True only for a version or a range of versions. Anything this does not recognise is refused.
export function isRegistryRange(spec) {
  if (typeof spec !== "string" || spec.trim() === "") return false;
  return spec.split("||").every((alternative) => {
    const parts = alternative.trim().replace(/([<>=~^])\s+/g, "$1").split(/\s+/).filter((p) => p !== "-");
    return parts.length > 0 && parts.every((p) => COMPARATOR.test(p));
  });
}

// The dependencies of a manifest that a registry cannot serve, as "field.name: spec".
export function unservable(manifest) {
  const out = [];
  for (const field of FIELDS)
    for (const [name, spec] of Object.entries(manifest[field] ?? {}))
      if (!isRegistryRange(spec)) out.push(`${field}.${name}: ${JSON.stringify(spec)}`);
  return out;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const file = process.argv[2] ?? fileURLToPath(new URL("../package.json", import.meta.url));
  const manifest = JSON.parse(readFileSync(file, "utf8"));
  const bad = unservable(manifest);
  if (bad.length) {
    console.error(`${manifest.name}: a registry cannot serve these dependencies:\n  ${bad.join("\n  ")}\n` +
      "Publish with `npm run release`: it publishes a packed copy that names the released x402-conformance-svm.");
    process.exit(1);
  }
}
