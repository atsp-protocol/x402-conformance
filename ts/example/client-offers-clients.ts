// Clients for the C2 check. Each uses the stock @x402/fetch 2.28.0 wrapper over @x402/core's x402Client, with the
// loopback test signer for the exact scheme from the R20b clients (a well-formed payload, nothing holds value). The
// policy is the client's own configuration: its networks and its maximum per payment in atomic units.
//
//   control      x402Client's own policy features: the signer is registered only for the configured networks (in
//                x402Client, scheme registration is the network scope) and spend controls cap each payment at the
//                maximum (an allowedAssets entry with an atomic maxAmountPerPayment for the asset it holds there)
//   first_offer  a selector that returns the first offer, a signer registered for any network and no spend controls
//   ignore_max   registered for its networks only, with no spend controls: it pays the first offer on its networks,
//                whatever the amount
import { wrapFetchWithPayment } from "@x402/fetch";
import { x402Client } from "@x402/core/client";
import { BASE_SEPOLIA, DEVNET } from "../src/double.js";
import { freshPayload } from "../src/retry.js";
import type { OfferPolicy } from "../src/client-offers.js";

export type OfferFault = "" | "first_offer" | "ignore_max";
export const OFFER_FAULTS: OfferFault[] = ["first_offer", "ignore_max"];

/** The asset the test client holds on each network: USDC, the asset the example servers price in. */
export const USDC: Record<string, string> = {
  [DEVNET]: "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU",
  [BASE_SEPOLIA]: "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
};

const signer = {
  scheme: "exact",
  createPaymentPayload: async (x402Version: number, requirements: any) =>
    ({ x402Version, payload: freshPayload(requirements) }),
} as any;

export function offerClient(policy: OfferPolicy, fault: OfferFault = "") {
  return async (url: string): Promise<Response> => {
    let client: x402Client;
    if (fault === "first_offer") {
      client = new x402Client((_version, accepts) => accepts[0]).register("*:*", signer).setSpendControls(false);
    } else {
      client = new x402Client();
      for (const n of policy.networks) client.register(n as `${string}:${string}`, signer);
      client.setSpendControls(fault === "ignore_max" ? false : {
        allowedAssets: policy.networks.filter((n) => USDC[n])
          .map((n) => ({ network: n as `${string}:${string}`, asset: USDC[n], maxAmountPerPayment: policy.maxAmount })),
      });
    }
    return wrapFetchWithPayment(fetch, client)(url);
  };
}
