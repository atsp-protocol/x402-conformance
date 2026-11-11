// What reaches the registry. In this repository the package depends on the core package beside it ("file:.."), which no
// registry can serve: 1.6.0 was published that way and could not be installed. A bare `npm publish` is refused, and the
// copy that `npm run release` publishes names the core package's released range.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, describe, test } from "node:test";
import { fileURLToPath } from "node:url";

const PKG = fileURLToPath(new URL("../../", import.meta.url));
const CORE = "x402-conformance-svm";
const read = (file: string) => JSON.parse(readFileSync(file, "utf8"));
const { isRegistryRange, unservable } = await import(new URL("../../scripts/manifest.mjs", import.meta.url).href);

describe("npm package: what a registry can serve", () => {
  test("npm package: a version or a range of versions is served by a registry", () => {
    for (const spec of ["1.32.1", "^1.6.0", "~1.2", ">=0.3.0", ">= 1.2.3", ">=1.0.0 <2", "1.x", "*", "^1.0.0 || ^2.0.0",
      "1.0.0 - 2.0.0", "1.0.0-rc.1"])
      assert.equal(isRegistryRange(spec), true, spec);
  });
  test("npm package: a path, a link, a workspace, a URL or a tag is not", () => {
    for (const spec of ["file:..", "file:../core", "link:../core", "workspace:*", "../core", "./core", "/abs/core",
      "git+https://github.com/a/b.git", "github:a/b", "a/b", "https://example.com/core.tgz", "latest", "", " "])
      assert.equal(isRegistryRange(spec), false, JSON.stringify(spec));
  });
  test("npm package: every field a consumer installs is read, devDependencies are not", () => {
    assert.deepEqual(unservable({ dependencies: { a: "file:.." }, optionalDependencies: { b: "link:../b" },
      peerDependencies: { c: "workspace:*", d: ">=1" }, devDependencies: { e: "file:../e" } }),
    ['dependencies.a: "file:.."', 'optionalDependencies.b: "link:../b"', 'peerDependencies.c: "workspace:*"']);
  });
});

describe("npm package: publishing", () => {
  const stage = mkdtempSync(join(tmpdir(), "x402-mcp-test-"));
  after(() => rmSync(stage, { recursive: true, force: true }));

  test("npm package: npm publish stops at the prepublishOnly guard while a dependency is file:..", () => {
    assert.equal(read(join(PKG, "package.json")).scripts.prepublishOnly, "node scripts/manifest.mjs");
    const r = spawnSync(process.execPath, ["scripts/manifest.mjs"], { cwd: PKG, encoding: "utf8" });
    assert.equal(r.status, 1, r.stderr);
    assert.match(r.stderr, new RegExp(`dependencies\\.${CORE}: "file:\\.\\."`));
  });

  test("npm package: the released copy names the released core package and the checkout is left as it was", () => {
    const before = readFileSync(join(PKG, "package.json"), "utf8");
    // dist/ is already built by `npm test`; building again here would rewrite the files the other tests are running.
    const r = spawnSync(process.execPath, ["scripts/publish.mjs", "--stage", stage, "--no-build"], { cwd: PKG, encoding: "utf8" });
    assert.equal(r.status, 0, r.stderr);
    const staged = read(join(stage, "package", "package.json"));
    assert.equal(staged.dependencies[CORE], `^${read(join(PKG, "..", "package.json")).version}`);
    assert.deepEqual(unservable(staged), []);
    assert.deepEqual({ ...staged, dependencies: { ...staged.dependencies, [CORE]: "file:.." } }, JSON.parse(before));
    for (const f of ["dist/src/index.js", "dist/src/bin.js", "dist/src/ai-sdk.js", "dist/src/langchain.js", "dist/FIXES.md",
      "README.md", "server.json"])
      assert.ok(existsSync(join(stage, "package", f)), `${f} is in the package`);
    assert.ok(existsSync(join(stage, `${staged.name}-${staged.version}.tgz`)), "the tarball to publish");
    assert.equal(readFileSync(join(PKG, "package.json"), "utf8"), before);
  });
});
