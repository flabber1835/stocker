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

## Display during fenced activation

The software installation receipt retains its installed timestamp while the
activation owner waits for Alpaca cash. For reviewed dual activation of backed
owner PAPER, the existing fenced-authority probe publishes a short-lived,
authenticated observation after the plan-preparation command returns the typed
cash wait. It uses the existing shared state volume and the activation's
original finite cutoff and exact certificate.
The observation binds the decision session, source publication, disabled and
killed control generation, active certificate, and local runtime identity.
Each refresh requires a new fee-wait result. Fencing, a changed subject, a
terminal activation outcome or a stale observation withdraws the display.

The verifier and dashboard consume this observation through the existing
operational projection. During a verified wait, expected missing worker
readiness and withdrawn financial views are pending, and the dashboard shows
amber with the Alpaca fee wait. Unrelated failures and corrupt evidence keep
their existing severity. Historical views keep their original status and
clocks. The wait supplies no machine readiness or trading authority. Ordinary
health resumes when activation ends and current checks provide fresh evidence.

The PAPER verifier must also distinguish an expected withdrawal from a failed
observation. When its existing historical-mirror branch cannot prove this
decision's scheduled readiness during the exact authenticated activation
wait, publish a bounded pending row at the source. This prevents the owned
verification attempt from recording the historical mismatch as a new failure
on each poll. The verifier schedules a new check before that row's original
deadline and publishes its original clock. Consumers recheck the wait before
using the pending row. An expired or changed wait withdraws that explanation.
Current mismatches,
invalid evidence, and unrelated operator review history retain their
existing treatment.

### Bounded renewal under slow PAPER preparation (2026-11-17)

The first installed activation showed consecutive authenticated fee-wait
observations 178–204 seconds apart, then a preparation retry exceeded the
original 210-second display lifetime. The broker-free verifier also queued a
PAPER check for 83 seconds behind the shared observation slot. Its pending
receipt retained the earlier witness deadline and expired while a newer
witness was valid. Both gaps produced real dashboard failures, although the
activation fence remained engaged.

Allow each newly authenticated fee-wait observation up to 360 seconds from its
publication, still capped by the original validation/opening cutoff. The
consumer must recheck the exact runtime, source, certificate, control
generation, disabled and killed fence, and current session on every read. The
observation remains display-only and grants no cash, plan, execution or
activation authority. A terminal activation clears it; a stalled owner or a
retry beyond this bound eventually withdraws the amber display and records a
real failure.

The pre-mutation backup proof may itself return a typed busy result for up to
five minutes before the next broker cash observation. That result does not
renew the fee-wait witness. If it outlasts the 360-second bound, the dashboard
must show the expired evidence as a failure until a new typed fee result or
successful preparation resolves it.

While a PAPER pending row is fresh, start its next full source observation
150 seconds before that row's original deadline, subject to the existing
single-observer slot and retry pacing. Keep the row and signed receipt's
original clocks; a newer witness cannot extend either without a newly
completed source observation. If the observer cannot publish before expiry,
the dashboard must still report the gap rather than extending old proof.

Retain the installed signed predecessor `3afc2f5302ffd63008585a3530e6ed7634c06ccc`
with its complete 490-module executable inventory and source closure
`ab589e0adfa53b7233ed15fa5207da8aa16b2d964f7f325f46dfa93d088a1f5e`.
Append that exact source view to the transition; do not rewrite any older
retained source record or change execution authority.

Retain the signed PAPER predecessor `4563851899ea5eaa157ae1c82e9fe72d2d298e2f`
with all 488 archived Python modules and source closure
`6beb79df5cfdf84d9ba1a266e413fd13254aae06bbe07578bcb92451d93fba8c`.
The source transition appends that exact inventory and seals the new runtime
without changing earlier retained records or granting execution authority.

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
