// Clients for C3. Both use the stock @x402/fetch 2.28.0 wrapper over @x402/core's x402Client, with a loopback test
// signer for the exact scheme (a well-formed payload with a fresh nonce or transaction each time it is asked to pay;
// nothing holds value).
//
//   ""           the control: the stock client. Its HTTP layer reads the PAYMENT-REQUIRED header when there is one and
//                the JSON body only when there is not, so it pays the V2 offer with PAYMENT-SIGNATURE
//   v1_fallback  the same client with a V1 scheme registered too (registerV1) and an HTTP layer that reads a V1 body
//                first: it pays the V1 offer with X-PAYMENT at x402Version 1 although a V2 offer is present
import { wrapFetchWithPayment } from "@x402/fetch";
import { x402Client, x402HTTPClient } from "@x402/core/client";
import { freshPayload } from "../src/retry.js";
import { V1_NAMES } from "../src/client-version.js";

export type VersionFault = "" | "v1_fallback";

// V1 requirements name the network by its V1 name and the price as maxAmountRequired, and a V1 payload carries its
// scheme and network itself (V1 5.2).
const signer = (network: string) => ({
  scheme: "exact",
  createPaymentPayload: async (x402Version: number, requirements: any) => x402Version === 1
    ? { x402Version: 1, scheme: requirements.scheme, network: requirements.network,
        payload: freshPayload({ ...requirements, network, amount: requirements.maxAmountRequired }) }
    : { x402Version, payload: freshPayload(requirements) },
});

/** Reads a V1 body before the PAYMENT-REQUIRED header. */
class V1FirstHTTPClient extends x402HTTPClient {
  getPaymentRequiredResponse(getHeader: (name: string) => string | null | undefined, body?: unknown) {
    if (body && typeof body === "object" && (body as any).x402Version === 1) return body as any;
    return super.getPaymentRequiredResponse(getHeader, body);
  }
}

export function payingClient(network: string, fault: VersionFault = "") {
  return async (url: string): Promise<Response> => {
    const client = new x402Client().register(network as `${string}:${string}`, signer(network) as any);
    // The test signer has no asset table, so the price's asset reads as non-default to the spend controls.
    client.setSpendControls({ allowedAssets: true });
    if (fault === "") return wrapFetchWithPayment(fetch, client)(url);
    client.registerV1(V1_NAMES[network] ?? network, signer(network) as any);
    return wrapFetchWithPayment(fetch, new V1FirstHTTPClient(client))(url);
  };
}
