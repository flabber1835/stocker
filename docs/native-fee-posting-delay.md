# Alpaca PAPER debit fee posting delay

Alpaca can publish a debit fee in its Activity SSE before the Trading Account
endpoint reflects it. On November 12, the owned account's immutable November
13 plan had no commands and recorded $9,742.11 cash. The authenticated stream
added a $0.01 CAT fee, while fresh account observations still reported $9,742.11.
The complete cash equation required $9,742.10. Alpaca documents the propagation
delay in [Activity SSE](https://docs.alpaca.markets/us/docs/activity-sse#sse-delivery-vs-balance-and-position-queries).

Use the existing native fee membership proof and exact plan cash and durable
fill calculation. If all new nonzero entries are authenticated debit fees and
fresh cash still equals the exact pre-activity balance, a complete, clean,
quiescent observation of the same account may report a typed posting wait.
The wait grants no cash authority. Full equality after the debit is required
before preparation, reconciliation or any new transport succeeds. Partial fee
posting, other cash differences, corrupt or incomplete activity, wrong account,
and unresolved or working orders retain their existing guards. Keep the generic
endpoint discrepancy policy and final protected funding checks.

Prepare and recover retry this condition using the normal scheduler. An opening
execution check reports the same wait through reconciliation, with the existing
original execution cutoff. Show the verified wait as amber during that window.
Any possible broker submission still goes through ordinary journal recovery,
and fresh transport remains subject to the original cutoff. An expired wait
cannot extend the execution window or certify a clean outcome. Later independent
readiness checks still require fresh cash and membership proof.

Fenced activation accepts this condition only from an exact, versioned
preparation result with its dedicated exit status. It re-observes under the
same owned activation and exact authority, before the target regular open and
the original validation expiry. It releases no fence while pending. Recheck
current source timing and stopped writers before retrying. Other preparation
refusals retain their existing behavior.
The host loads the shared, dependency-free wire definition from its exact file
without adding the inspection checkout to the Python module search path.

Preserve the immutable plan baseline, canonical book, journal, account and
source history. Qualify using the real native-activity ledger, the opening
scheduler and the fenced activation protocol, including tests for unexplained
cash, wrong or incomplete evidence, restart, convergence and original cutoff.

## Executable source compatibility

The Git archive for `e9ef8b51259898a84f4b2c21f8e601e9ed9a5922` contains 475
Python files with source closure
`9b8784f7b1a97757c100fc3ece7fee0969712b8d5e4badd1bf726ff1cf345f28`.
The 51 prior expanded source maps have canonical JSON SHA-256
`2bed28aba37f1f347d47ddb2023ebfee9d1bb57f6bd09da9f43fe0e174b46795`.
Schema `sentinel.url-selected-trading-transition/53` retains these maps and
adds the exact e9 executable inventory. The 476-file successor has source
closure `a765d57aaee2` and the source handover carries
`authority_effect=NONE`.
