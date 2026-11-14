# Whole-share market buys in backed PAPER

Decision recorded before implementation on 2026-11-11. Develop this opt-in
execution policy on the opening stability patch. The default installed policy
continues to be the approved protected limit policy. A later, separately
authorized backed PAPER activation selects the new policy on a fresh plan after
complete broker and journal reconciliation, with zero working or uncertain
orders. Use the existing account binding, book, source generation, backup and
WAL controls. LIVE remains forbidden. Broker facts stay in execution.

## Policy identity and sizing

Select MARKET_DAY_V1 explicitly for the backed owner-authorized Alpaca PAPER
account. Bind the policy into its own versioned execution configuration and
the immutable sizing evidence. Legacy and protected configuration identities
and all historical command terms retain their existing decoding. Bind the market
policy hash into the automation configuration and the plan's original dual
sizing authority. A changed configuration requires an intentional fresh control
binding and a new decision. A same-session plan with a different policy cannot
be adopted for new transport. The narrowly attended unsent replacement in
[fractional PAPER execution](fractional-paper-execution.md#replacing-an-already-saved-next-session-plan)
creates a distinct successor under renewed authority; it does not change the
old plan's policy. Historical read-only reconciliation keeps its
original terms. The protected limit-cap and debug-window inputs are incompatible
with this policy.

All buy increases, including new Core entries, fixed continuing or resized
Core targets, and BIL, use whole-share simple MARKET/DAY orders in regular hours.
Use the actual session's existing 60-second start and 600-second cutoff.
Reductions use the current execution and positive settlement paths. Reuse the
canonical opening allocation and priority, action-bound native identity, and
durable held targets. Size new entries from the existing fresh IEX bid/ask
evidence. In account units, also bound shares by the priority allocation using
the observed ask plus a 100-basis-point sizing buffer and USD 1.00 per buy.
Persist the original quote and sizing evidence for opening intents. Use those
exact quantities on continuation. An unavailable initial quote leaves that
entry pending for a future plan. Fixed targets keep their established share
quantities and face the same current-cash gate. Missing or stale final IEX
evidence defers the affected buy within the existing session deadline.
Prior-session marks are historical.

The buffer is an estimate. The market can execute above the ask and the
estimate. The native cash-only 1x envelope is load-bearing, and the initial
buying-power check supplies no fill-price guarantee. The mode requires
production-equivalent independent PAPER evidence of the cash-only behavior
and opening latency before activation. The design and simulator do not claim
that evidence.

## Submission and recovery

Under the existing account writer lock, submit at most one unresolved market
buy at a time. Use positive, complete quiescent reconciliation and fresh
settled account cash before another buy, including after restart. Retain the
normal account, issuer, source, time, authority and long-only checks. At the
final guarded submission compare the exact pending command, fresh ask plus
buffer and fee reserve, and fresh reconciled cash and native buying power.
Keep the cash bound no greater than the smaller of native cash and buying
power. Missing, mismatched, or lagging evidence defers transport. A previously
attempted POST with ambiguous status belongs to exact-key recovery. A later
pre-transport refusal cannot establish the earlier attempt was unsent.

Reuse the canonical journal, order identity and existing recovery callbacks.
Acknowledge and track partial fills from positive broker evidence. An unresolved
outcome blocks another buy across the account. A clean terminal reconciliation
and actual fill accounting can resume actionable unsent work within the
original window. Keep the existing terminal rejection and cancellation
handling. The submission and verification paths may use no invented fill,
automatic price chase, order replacement, deadline extension or margin.

## Display and qualification

Show actual broker-reported buying power alongside a positively matched
working market buy. Exact account, plan, command, native instrument, terms
and fill evidence can support a bounded pending display, with its original
clock. The protected limit reservation and its proof keep their current
meaning. Uncertain or foreign orders, negative cash, leverage and stale or
contradictory evidence remain visible as their normal failures.

Qualify against private PostgreSQL and Alpaca fixtures with gaps, missing
quotes, insufficient cash, exact cutoff, partial fills, broker rejection,
lost acknowledgement and restart after broker acceptance. Falsify the
single-buy, cash and final transport guards. Exercise historic limit recovery,
policy/hash drift, and the normal scheduled callback path. Compare opening
latency using the original business clock. Deliver through the normal backed
PAPER release and separate financial activation.

Seal the exact reviewed executable inventory for the new source transition.
Retain the opening-stability predecessor and all earlier historical source
closures. Source recognition supplies no financial authority.

## Lifecycle equivalence

Record the reviewed preparation, target projection, instrument mapping, broker
composition, and execution changes in the paper lifecycle delta registry. The
new pending-command validator belongs to paper validation. Keep the historical
extraction manifest and the prior approved function fingerprints. Validate each
new fingerprint after the existing backup and recovery checks and exercise the
registry's fingerprint falsifiers.
