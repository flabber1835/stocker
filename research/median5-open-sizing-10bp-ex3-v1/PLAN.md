# Median-5 + 10 bp open-time sizing + EX3 full-PIT experiment

Objective: run one fresh canonical 20-year PIT replay that records both the pure Wealth Core book and the frozen EX3/Candidate-A overlay on that same book.

## Frozen Wealth Core configuration
- Median-5: 20 slots
- 5% target entry weight
- trailing-five causal rank-order hardening of the current top three
- 10 bp close-time admission cushion
- next-valid-open whole-share position sizing from actual opening price and actual available cash
- no prior-close share quantity binding
- one-session dividend settlement
- existing cooldown/review/stop/liquidity/cost/security-type/PIT semantics unchanged

## Whole-share admission rule

The first full-PIT run (`34299991647`) exposed five next-open zero-quantity blocks. Investigation showed all five were repeated AMZN admissions from 2015-12-04 through 2015-12-10 while the 19/20-slot book had only $283.521942 cash and AMZN traded above $650 per share.

The open-sizing rule behaved correctly; the close admission rule was too weak. It admitted a candidate whenever any positive cash remained above the 10 bp reserve, even if one whole share was already unaffordable at the known close price.

For the next authorized run, whole-share close admission therefore requires:

`cash_above_10bp_reserve >= close_price * (1 + COST)`

If not, the candidate is skipped with `q0_reason = WHOLE_SHARE_UNAFFORDABLE_AT_CLOSE` and the admission search continues down the Median-5 ranked order.

This is a necessary affordability gate only. It does **not** bind share quantity at the close. Exact quantity remains determined at the next valid open from actual opening price and actual cash. An extreme overnight gap can still produce a zero-share open, so the execution guard remains in place.

See `EXECUTION_BLOCK_INVESTIGATION.md` for exact event evidence and diagnosis.

## Recorded outputs
1. Pure Wealth Core metrics from the raw book NAV (`shadow_equity` / equivalent raw-book series).
2. Frozen EX3 / Candidate-A overlay metrics from `A_nav` on the same underlying Wealth Core path.
3. Incremental EX3 contribution: CAGR, max-drawdown, Sharpe, ending multiple, transition counts, and allocation statistics.
4. `close-decisions.csv`, including explicit close-admission skip reasons.
5. next-open sizing telemetry and transaction evidence.

## Run control

The workflow is manual `workflow_dispatch` only. Changes to the research branch must not automatically launch another 20-year replay.

No tuning. No production change. Full canonical PIT window: 2006-07-31 through 2026-07-31.

Current state: the close-affordability fix is implemented and documented, but no post-fix experiment has been run yet.
