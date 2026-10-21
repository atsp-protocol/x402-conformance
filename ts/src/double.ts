// A facilitator double for resource-server checks: GET /supported, POST /verify and POST /settle (x402 V2 7.1-7.3) on
// loopback, with one switchable fault mode. It never touches a chain, a key or a network beyond loopback.
import http from "node:http";
import type { AddressInfo, Socket } from "node:net";

export const DEVNET = "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1";
export const BASE_SEPOLIA = "eip155:84532";
/** Networks the probe can grade, in the order it prefers them when a server offers several. */
export const NETWORKS = [DEVNET, BASE_SEPOLIA] as const;
export type Network = (typeof NETWORKS)[number];
// Syntactically valid signers the double advertises; they hold nothing and sign nothing.
export const DOUBLE_FEE_PAYER = "11111111111111111111111111111111";
export const DOUBLE_EVM_SIGNER = "0x000000000000000000000000000000000000dEaD";

export type Mode =
  | "reference"      // verify: isValid=true; settle: success once per transaction, then duplicate_settlement
  | "settle_timeout" // settle never answers: the connection is held open until the server gives up or the probe ends
  | "settle_502"     // settle answers an HTML 502
  | "settle_503"     // settle answers 503 with a body that still reads as success (a proxy replaying a cached body)
  | "settle_non_json"// settle answers 200 with an HTML page
  | "settle_truncated" // settle answers 200 with half of a success body
  | "settle_pending" // settle answers success=false, errorReason=settlement_pending, with a transaction
  | "settle_failed"; // settle answers success=false, errorReason=invalid_transaction_state

export const MODES: Mode[] = ["reference", "settle_timeout", "settle_502", "settle_503", "settle_non_json",
  "settle_truncated", "settle_pending", "settle_failed"];

export interface Double {
  url: string;
  mode: Mode;
  calls: { path: string; mode: Mode }[];
  close(): Promise<void>;
}

function txOf(body: any): string {
  const p = body?.paymentPayload?.payload ?? {};
  const t = String(p.transaction ?? p.signature ?? p.authorization?.nonce ?? "");
  let h = 0;
  for (const c of t) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return `double-tx-${h.toString(16)}-${t.length}`;
}

/** Thrown by startDouble when its port is taken, so callers can report it instead of crashing. */
export class PortInUseError extends Error {
  constructor(public port: number) {
    super(`port ${port} on 127.0.0.1 is already in use; pick another with --port`);
  }
}

export async function startDouble(port = 0): Promise<Double> {
  const settled = new Set<string>();
  const held = new Set<http.ServerResponse>();
  const sockets = new Set<Socket>();
  const d: Double = { url: "", mode: "reference", calls: [], close: async () => {} };
  const server = http.createServer(async (rq, rs) => {
    const json = (code: number, obj: unknown) => {
      rs.writeHead(code, { "content-type": "application/json" });
      rs.end(JSON.stringify(obj));
    };
    let data = "";
    for await (const c of rq) data += c;
    const path = rq.url ?? "";
    d.calls.push({ path, mode: d.mode });
    if (rq.method === "GET" && path === "/supported") {
      return json(200, {
        kinds: [{ x402Version: 2, scheme: "exact", network: DEVNET, extra: { feePayer: DOUBLE_FEE_PAYER } },
          { x402Version: 2, scheme: "exact", network: BASE_SEPOLIA }],
        extensions: [], signers: { "solana:*": [DOUBLE_FEE_PAYER], "eip155:*": [DOUBLE_EVM_SIGNER] },
      });
    }
    let body: any;
    try { body = JSON.parse(data); } catch { return json(400, { isValid: false, invalidReason: "invalid_payload" }); }
    const network = body?.paymentRequirements?.network ?? DEVNET;
    const payer = network.startsWith("eip155:") ? DOUBLE_EVM_SIGNER : "double-payer";
    if (path === "/verify") return json(200, { isValid: true, payer });
    if (path !== "/settle") return json(404, { error: "not found" });
    const tx = txOf(body);
    const success = { success: true, transaction: tx, network, payer };
    switch (d.mode) {
      case "settle_timeout":
        // Never answer, and never answer success later: a slow success is not a timeout, and a server that waits for
        // it is right to serve. The response is held until the server gives up or close() drops the connection.
        held.add(rs);
        rs.on("close", () => held.delete(rs));
        return;
      case "settle_502":
        rs.writeHead(502, { "content-type": "text/html" });
        return rs.end("<html><body>502 Bad Gateway</body></html>");
      case "settle_503":
        return json(503, success);
      case "settle_non_json":
        rs.writeHead(200, { "content-type": "text/html" });
        return rs.end("<html><body>Service temporarily unavailable</body></html>");
      case "settle_truncated": {
        const raw = JSON.stringify(success);
        rs.writeHead(200, { "content-type": "application/json" });
        return rs.end(raw.slice(0, Math.floor(raw.length / 2)));
      }
      case "settle_pending":
        return json(200, { success: false, errorReason: "settlement_pending", transaction: tx, network });
      case "settle_failed":
        return json(200, { success: false, errorReason: "invalid_transaction_state", transaction: tx, network });
      default:
        if (settled.has(tx)) return json(200, { success: false, errorReason: "duplicate_settlement", transaction: "", network });
        settled.add(tx);
        return json(200, success);
    }
  });
  server.on("connection", (s: Socket) => { sockets.add(s); s.on("close", () => sockets.delete(s)); });
  await new Promise<void>((ok, fail) => {
    server.once("error", (e: NodeJS.ErrnoException) => fail(e.code === "EADDRINUSE" ? new PortInUseError(port) : e));
    server.listen(port, "127.0.0.1", ok);
  });
  d.url = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  d.close = () => new Promise((ok) => {
    for (const s of sockets) s.destroy();
    server.close(() => ok());
  });
  return d;
}
