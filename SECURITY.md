# Security policy

This project is maintained, and security reports are triaged, by Ryan Gillespie ([@mgillr](https://github.com/mgillr)), Optitransfer.

## Reporting a vulnerability
Please use GitHub private vulnerability reporting: **Security → Report a vulnerability**
(https://github.com/atsp-protocol/x402-conformance/security/advisories/new). Do not open a public issue for a
vulnerability, and please do not report one by email.

I acknowledge reports within 7 days. Supported version: the latest `main` and the latest tag.

## Findings about third-party facilitators
When this suite finds a failing safety check in someone else's facilitator, I report it to that operator
privately first. I publish only after a fix, or 90 days after the report, whichever comes first. Without that operator's
permission, the live and resource modes send a third party only GET requests: `GET /supported` (S0 to S4) and one
unpaid GET of a paid URL (P1 to P7), and that is tested. The resource-server probe sends paid requests, and with
`--by-method` a `POST`, to the URL you give it, and nothing checks who runs that server, so point it only at a server you
run, with its facilitator URL set to the double. The devnet runner refuses a facilitator that is not on loopback unless
`--operator-permission` names the operator's written permission.

## What the suite will not do
It holds no keys of yours and never pays on mainnet. Live and resource modes are GET-only, and that is tested. The devnet runner signs devnet payments in a throwaway test token with throwaway keypairs from a directory outside the repository (`X402C_KEYS`), and the R11 binding probe signs with throwaway keys it generates for the run, which hold nothing.
