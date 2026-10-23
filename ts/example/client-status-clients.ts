// Clients for the C1 check. Each pays through @x402/core 2.28.0's x402Client with a loopback test signer for the exact
// scheme (a well-formed payload with a fresh nonce or transaction each time it is asked to pay; nothing holds value).
//
//   stockClient          the stock @x402/fetch 2.28.0 wrapper: it pays a 402 and retries
//   decliningClient      the same wrapper with a payment policy that declines any offer above its budget: it does not
//                        pay, and its promise rejects with the payment error
//   statusCheckedClient  a client with its own status check, set to accept every status, and a payment step:
//     ""                   the payment step runs on any 402 before the status check, so the client still pays
//     accept_any_status    the payment step runs only for statuses the status check rejects. The 402 passes the
//                          check, so the payment step never runs and the 402 goes back to the caller unpaid
import { wrapFetchWithPayment } from "@x402/fetch";
import { x402Client, x402HTTPClient } from "@x402/core/client";
import { freshPayload } from "../src/retry.js";

export type StatusFault = "" | "accept_any_status";

function payer(network: string) {
  const client = new x402Client().register(network as `${string}:${string}`, {
    scheme: "exact",
    createPaymentPayload: async (x402Version: number, requirements: any) =>
      ({ x402Version, payload: freshPayload(requirements) }),
  } as any);
  // The test signer has no asset table, so the price's asset reads as non-default to the spend controls.
  client.setSpendControls({ allowedAssets: true });
  return client;
}

export function stockClient(network: string) {
  return (url: string): Promise<Response> => wrapFetchWithPayment(fetch, payer(network))(url);
}

/** Declines any offer whose amount is above `budget` atomic units. The route in the tests asks for 10000. */
export function decliningClient(network: string, budget = 1000n) {
  return (url: string): Promise<Response> => {
    const client = payer(network).registerPolicy((_v, reqs) => reqs.filter((r) => BigInt(r.amount) <= budget));
    return wrapFetchWithPayment(fetch, client)(url);
  };
}

export function statusCheckedClient(network: string, fault: StatusFault = "",
    statusOk: (status: number) => boolean = () => true) {
  const client = payer(network);
  const http = new x402HTTPClient(client);
  // The payment step: read the offer from the 402, sign it and send the request again with PAYMENT-SIGNATURE.
  const pay = async (url: string, answer: Response): Promise<Response> => {
    const text = await answer.text();
    let body: unknown;
    try { body = text ? JSON.parse(text) : undefined; } catch { body = undefined; }
    const required = http.getPaymentRequiredResponse((n) => answer.headers.get(n), body);
    const payload = await client.createPaymentPayload(required);
    return fetch(url, { headers: http.encodePaymentSignatureHeader(payload) });
  };
  return async (url: string): Promise<Response> => {
    let r = await fetch(url);
    if (fault === "" && r.status === 402) r = await pay(url, r);
    if (statusOk(r.status)) return r;
    // The status check rejected the answer: the payment step runs here, as a handler for failed requests.
    if (r.status === 402) {
      r = await pay(url, r);
      if (statusOk(r.status)) return r;
    }
    throw new Error(`request failed with status ${r.status}`);
  };
}
