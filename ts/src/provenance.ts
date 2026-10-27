/** Who made the tool that wrote a results document (XC-95): the suite, its version, the publisher and the repo. */
const REPO = "https://github.com/atsp-protocol/x402-conformance";

export interface Provenance {
  suite: "x402-conformance";
  version: string;
  publisher: "Optitransfer";
  repo: string;
}

export function provenance(version: string): Provenance {
  return { suite: "x402-conformance", version, publisher: "Optitransfer", repo: REPO };
}
