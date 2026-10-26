// Writes docs/parity/vectors.json, the shared parity vector set. Deterministic: the same file on every run.
//
//   cd ts/parity-harness && npx tsc -p . && node dist/src/make-vectors.js ../../docs/parity/vectors.json
//
// The signed vectors carry EIP-3009 TransferWithAuthorization signatures over the USDC EIP-712 domain on Base
// Sepolia. The signing key is derived from the public label below: anyone can derive it, it has never been funded and
// it is not used on any network. It exists only so that a vector can reach the checks that come after signature
// recovery (amount, recipient, expiry) with no chain. Only the signatures and the address are written.
import { writeFileSync } from "node:fs";
import { keccak256, toBytes, type Hex } from "viem";
import { privateKeyToAccount } from "viem/accounts";

const LABEL = "x402-conformance parity vectors: a public test key that holds nothing on any network";
const account = privateKeyToAccount(keccak256(toBytes(LABEL)));
const NETWORK = "eip155:84532";
const ASSET = "0x036CbD53842c5426634e7929541eC2318f3dCF7e";
const PAY_TO = "0x209693Bc6afc0C5328bA36FaF03C514EF312287C";
const OTHER = "0x000000000000000000000000000000000000dEaD";
const AMOUNT = "1000";
const FAR = "4102444800"; // 2100-01-01T00:00:00Z

type Auth = { from: Hex; to: Hex; value: string; validAfter: string; validBefore: string; nonce: Hex };

const requirements = (over: Record<string, unknown> = {}) => ({
  scheme: "exact", network: NETWORK, amount: AMOUNT, asset: ASSET, payTo: PAY_TO, maxTimeoutSeconds: 60,
  extra: { name: "USDC", version: "2" }, ...over,
});

async function signed(id: string, over: Partial<Auth> = {}, chainId = 84532): Promise<{ signature: Hex; authorization: Auth }> {
  const authorization: Auth = { from: account.address, to: PAY_TO, value: AMOUNT, validAfter: "0", validBefore: FAR,
    nonce: keccak256(toBytes(`parity nonce ${id}`)), ...over };
  const signature = await account.signTypedData({
    domain: { name: "USDC", version: "2", chainId, verifyingContract: ASSET },
    types: { TransferWithAuthorization: [
      { name: "from", type: "address" }, { name: "to", type: "address" }, { name: "value", type: "uint256" },
      { name: "validAfter", type: "uint256" }, { name: "validBefore", type: "uint256" }, { name: "nonce", type: "bytes32" },
    ] },
    primaryType: "TransferWithAuthorization",
    message: { ...authorization, value: BigInt(authorization.value), validAfter: BigInt(authorization.validAfter),
      validBefore: BigInt(authorization.validBefore) },
  });
  return { signature, authorization };
}

const payload = (req: Record<string, unknown>, inner: unknown) =>
  ({ x402Version: 2, resource: { url: "http://127.0.0.1/paid" }, accepted: req, payload: inner });
const b64 = (s: string) => Buffer.from(s, "utf8").toString("base64");

const REJECT = { isValid: false, threw: false };
const MALFORMED = { ...REJECT, invalidReason: ["invalid_payload"] };
const NETWORK_REJECT = { ...REJECT, invalidReason: ["invalid_network", "unsupported_scheme"] };
const ROUTE_4XX = { status: [400, 402], content_type: "application/json", threw: false };

async function main(out: string) {
  const R = requirements();
  const good = await signed("good");
  const vectors: Record<string, unknown>[] = [];
  const verify = (id: string, tags: string[], anchor: string, profile: string, p: unknown, req: unknown,
    expect: Record<string, unknown>, note: string) =>
    vectors.push({ id, target: "verify", tags, anchor, profile, note, input: { payload: p, requirements: req }, expect });
  const route = (id: string, header: string, note: string) =>
    vectors.push({ id, target: "paid-route", tags: ["status-mapping", "error-content-type", "malformed"], anchor: "P1",
      profile: "normative", note, input: { header }, expect: ROUTE_4XX });

  const malformed: [string, unknown, string][] = [
    ["verify-payload-array", [1, 2, 3], "the payment payload is a JSON array"],
    ["verify-payload-string", "payment", "the payment payload is a JSON string"],
    ["verify-payload-number", 42, "the payment payload is a JSON number"],
    ["verify-payload-null", null, "the payment payload is JSON null"],
    ["verify-payload-empty-object", {}, "the payment payload is an empty object"],
    ["verify-no-inner-payload", { x402Version: 2, resource: { url: "http://127.0.0.1/paid" }, accepted: R },
      "x402Version and accepted, but no payload"],
    ["verify-no-authorization", payload(R, { signature: good.signature }), "a signature but no authorization"],
    ["verify-authorization-less", payload(R, { scheme: "exact", network: NETWORK }),
      "the inner payload names the scheme and network but carries no authorization, signature or transaction"],
    ["verify-authorization-not-object", payload(R, { signature: good.signature, authorization: "x" }),
      "the authorization is a string"],
    ["verify-value-not-integer", payload(R, { signature: good.signature,
      authorization: { ...good.authorization, value: "ten" } }), "the authorization value is not an integer"],
  ];
  for (const [id, p, note] of malformed) {
    verify(id, ["malformed", "F15"], "F1", "normative", p, R, MALFORMED, note);
  }

  const sepolia = requirements({ network: "eip155:11155111" });
  const onSepolia = await signed("unregistered", {}, 11155111);
  verify("verify-unregistered-network", ["unregistered-network", "wildcard-network", "F16"], "F12", "security-profile",
    payload(sepolia, onSepolia), sepolia, NETWORK_REJECT,
    "registered for eip155:84532 only; a correctly signed payment for eip155:11155111, a testnet of the same family");
  const solana = requirements({ network: "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1" });
  verify("verify-other-namespace", ["unregistered-network"], "F12", "security-profile", payload(solana, good), solana,
    NETWORK_REJECT, "registered for eip155:84532 only; a requirement on a Solana network");
  const wild = requirements({ network: "eip155:*" });
  verify("verify-wildcard-requirement", ["wildcard-network"], "S2", "normative", payload(wild, good), wild,
    NETWORK_REJECT, "the requirement's network is the pattern eip155:*, which is not a CAIP-2 chain id");
  verify("verify-accepted-network-mismatch", ["invalid-reason-codes"], "F14", "security-profile",
    payload(sepolia, good), R, REJECT, "accepted names eip155:11155111 while the requirement is eip155:84532");

  const reason = (id: string, tags: string[], anchor: string, p: unknown, req: unknown, code: string[], note: string) =>
    verify(id, ["invalid-reason-codes", ...tags], anchor, "normative", p, req, { ...REJECT, invalidReason: code }, note);
  const over = await signed("overpay", { value: "2000" });
  reason("verify-overpay", ["override-ceiling"], "S5", payload(R, over), R,
    ["invalid_exact_evm_payload_authorization_value_mismatch"], "a valid signature authorising 2000 for a 1000 requirement");
  const under = await signed("underpay", { value: "999" });
  reason("verify-underpay", ["override-ceiling"], "S5", payload(R, under), R,
    ["invalid_exact_evm_payload_authorization_value_mismatch"], "a valid signature authorising 999 for a 1000 requirement");
  const other = await signed("recipient", { to: OTHER });
  reason("verify-recipient-mismatch", [], "S5", payload(R, other), R, ["invalid_exact_evm_payload_recipient_mismatch"],
    "a valid signature paying an address other than payTo");
  const expired = await signed("expired", { validBefore: "1000" });
  reason("verify-expired", [], "S5", payload(R, expired), R, ["invalid_exact_evm_payload_authorization_valid_before"],
    "validBefore is in 1970");
  const early = await signed("not-yet-valid", { validAfter: "4102444000" });
  reason("verify-not-yet-valid", [], "S5", payload(R, early), R, ["invalid_exact_evm_payload_authorization_valid_after"],
    "validAfter is in 2099");
  reason("verify-bad-signature", [], "S5",
    payload(R, { ...good, signature: `0x${"11".repeat(65)}` as Hex }), R, ["invalid_exact_evm_payload_signature"],
    "65 bytes that are not a signature by the payer");
  reason("verify-scheme-mismatch", [], "S5", payload(requirements({ scheme: "upto" }), good), R,
    ["unsupported_scheme", "invalid_scheme"], "accepted names the upto scheme while the requirement is exact");
  reason("verify-version-3", [], "S5", { ...payload(R, good), x402Version: 3 }, R, ["invalid_x402_version"],
    "x402Version 3");
  const noDomain = requirements({ extra: {} });
  reason("verify-missing-eip712-domain", [], "P5", payload(noDomain, good), noDomain, ["invalid_payment_requirements"],
    "the requirement has no extra.name or extra.version");

  route("route-not-base64", "%%%not-base64%%%", "a PAYMENT-SIGNATURE that is not base64");
  route("route-base64-not-json", b64("this is not json"), "base64 of text that is not JSON");
  route("route-json-array", b64("[1,2,3]"), "base64 of a JSON array");
  route("route-json-number", b64("42"), "base64 of a JSON number");
  route("route-json-null", b64("null"), "base64 of JSON null");
  route("route-empty-object", b64("{}"), "base64 of an empty object");
  route("route-no-accepted", b64(JSON.stringify({ x402Version: 2 })), "x402Version 2 and nothing else");

  const doc = { schema: "x402conf.parity-vectors/1",
    about: "Shared parity vectors (XC-56). verify vectors go to the library's facilitator verify, registered for the exact "
      + "scheme on eip155:84532 with a stub signer; paid-route vectors go to the library's payment middleware on loopback "
      + "as the PAYMENT-SIGNATURE header of a GET to a paid route. expect is the outcome the spec calls for.",
    registered: { scheme: "exact", network: NETWORK, asset: ASSET, payTo: PAY_TO, amount: AMOUNT },
    signer: account.address, vectors };
  writeFileSync(out, JSON.stringify(doc, null, 1) + "\n");
  console.log(`wrote ${vectors.length} vectors to ${out}`);
}

main(process.argv[2] ?? "vectors.json").catch((e) => { console.error(e); process.exit(1); });
