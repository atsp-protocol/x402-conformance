# False-positive register

Every report that a check failed something the spec allows goes in this table, with the public issue, the outcome and
the test that keeps the outcome. A report is filed with the
[false positive issue form](https://github.com/atsp-protocol/x402-conformance/issues/new?template=false-positive.yml).
The outcome is one of two things: a fix, which changes the check and adds a regression test, or a documented
exception, which keeps the check and records why the reported behaviour is graded as it is. Either way the row stays.

The mutation matrix is the other half of credibility: `docs/site/mutation-matrix.json`, built by
`python3 tools/mutation_matrix.py --write` and checked in CI with `--check`, records for every check which faulty build
it is proven to catch. A check that catches no faulty build fails CI.

| issue | check | outcome | regression test |
|---|---|---|---|
| none filed yet | S4 | documented exception, set in 1.4.0 before any report: a fee payer that is not listed in `signers` is a warning, not an error, because V2 §7.3.1 does not require the listing | `tests.test_live.Live.test_s4_not_signer_is_a_warning_and_missing_fee_payer_an_error` |
| none filed yet | P6 | documented exception, set in 1.4.0: a `PAYMENT-REQUIRED` header over 8 KB is a warning and only over 16 KB an error, because the size limit is a proxy and CDN limit, not spec text | `tests.test_live.Live.test_p6_header_budget` |
| none filed yet | P7 | documented exception, set in 1.4.0: an `upto` Solana offer without `extra.paymentFlow` is a warning, because V2 §6.1 and the upto SVM scheme text disagree | `tests.test_live.Live.test_p7_payment_flow_declared` |

No external false-positive report has been filed so far. When one is, its row names the issue number.
