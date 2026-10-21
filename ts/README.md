# x402-conformance-svm

The resource-server probe of [x402-conformance](https://github.com/atsp-protocol/x402-conformance). It starts a
facilitator double on loopback, points your server at it through `X402_FACILITATOR_URL`, and pays your paid route
with test payloads on **Solana devnet** or **Base Sepolia** (`exact`; EVM via EIP-3009) under each fault below. The name
is historical: it grades Base Sepolia too. The double never touches a chain, a key or anything beyond loopback.

```
npx -y x402-conformance-svm probe --resource http://127.0.0.1:4020/paid --start "node server.js" --out results.json
npx -y x402-conformance-svm --help
npx -y x402-conformance-svm --version
```

| id | what the double does on `/settle` | your server must |
|---|---|---|
| R0 | (unpaid request) | answer 402 with a `PAYMENT-REQUIRED` header offering `exact` on Solana devnet or Base Sepolia; if it offers neither, the result is **unsupported** |
| R1 | settles | serve the content, after calling the double (otherwise the probe stops: your server isn't using `X402_FACILITATOR_URL`) |
| R2 | settles once, then `duplicate_settlement` | serve the same payment at most once (F3) |
| R3 | never answers | not serve (F6) |
| R4 | HTML 502 | not serve (F6) |
| R5 | 503 with a body that reads as success | not serve (F9) |
| R6 | 200 with an HTML page | not serve (F9) |
| R7 | 200 with half a success body | not serve (F9) |
| R8 | `settlement_pending` with a transaction | not serve before the payment is final (F5) |
| R9 | `invalid_transaction_state` | not serve (F8) |
| R10 | (the R1 response) | carry a `PAYMENT-RESPONSE` header that decodes to `success: true` |

**Your server.** Any x402 resource server works if it reads its facilitator URL from `X402_FACILITATOR_URL` and offers
one of the two test networks. With the upstream Express middleware, unchanged:

```js
import express from "express";
import { paymentMiddleware, x402ResourceServer } from "@x402/express";
import { HTTPFacilitatorClient } from "@x402/core/server";
import { ExactEvmScheme } from "@x402/evm/exact/server";   // or ExactSvmScheme from "@x402/svm/exact/server"

const network = "eip155:84532";                              // or "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1"
const server = new x402ResourceServer(new HTTPFacilitatorClient({ url: process.env.X402_FACILITATOR_URL }))
  .register(network, new ExactEvmScheme());
const app = express();
app.use(paymentMiddleware({ "GET /paid": { accepts: [{ scheme: "exact", price: "$0.001", network,
  payTo: "0xYourAddress" }], description: "paid route" } }, server));
app.get("/paid", (_req, res) => res.json({ content: "paid content" }));
app.listen(Number(process.env.PORT ?? 4020), "127.0.0.1");
```

This server passes R0-R10 in this repo's CI on both networks
([example/express-server.ts](https://github.com/atsp-protocol/x402-conformance/blob/main/ts/example/express-server.ts)).

**Options.** `--port` sets the double's loopback port (default 4402). `--start` runs your server with
`X402_FACILITATOR_URL` set; the probe refuses to run if something else already answers on your server's port, and stops
with an error if your server exits. `--network` picks `auto` (default), `solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1` or
`eip155:84532`. `--out` writes the results JSON, on errors too. Each request has a 60 s deadline; a server still holding
a request then has served nothing.

**Exit codes.** 0 all pass; 1 a check failed; 2 usage error, or the run couldn't complete (a port in use, your server
exited or never answered); 3 unsupported (your server offers no network the probe grades). `--help` and `--version`
exit 0.

In GitHub Actions use the action at the repository root:

```yaml
- uses: atsp-protocol/x402-conformance@v1
  with:
    resource-url: http://127.0.0.1:4020/paid
    start: node server.js
```

Apache-2.0. Ryan Gillespie / Optitransfer.
