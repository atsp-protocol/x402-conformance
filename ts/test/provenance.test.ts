import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { provenance } from "../src/provenance.js";
import { makeReport } from "../src/report.js";

const VERSION: string = JSON.parse(readFileSync(new URL("../../package.json", import.meta.url), "utf8")).version;

test("provenance: names the suite, version, publisher and repository", () => {
  assert.deepEqual(provenance("9.9.9"), { suite: "x402-conformance", version: "9.9.9", publisher: "Optitransfer",
    repo: "https://github.com/atsp-protocol/x402-conformance" });
});

test("provenance: every report carries it, at the package version", () => {
  const r = makeReport("resource-402", "http://127.0.0.1:1/paid", []);
  assert.equal(r.provenance.suite, "x402-conformance");
  assert.equal(r.provenance.version, VERSION);
  assert.equal(r.provenance.publisher, "Optitransfer");
  assert.equal(r.provenance.repo, "https://github.com/atsp-protocol/x402-conformance");
});
