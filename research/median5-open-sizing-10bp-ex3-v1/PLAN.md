# Wealth Core V3 + EX3 full-PIT experiment

Objective: run one fresh canonical 20-year PIT replay that records both the raw Wealth Core V3 book and the frozen EX3/Candidate-A overlay on that exact same book.

## Wealth Core V3 definition

**Wealth Core V3** is the canonical Wealth Core execution contract consisting of:

- Median-5 Wealth Core selection/configuration: 20 slots, 5% target entry weight, trailing-five causal rank-order hardening of the current top three;
- 10 bp close-time admission cushion;
- close-time whole-share affordability gate: cash above the 10 bp reserve must fund at least one whole share at the known close price including modeled cost;
- no prior-close share quantity binding;
- exact whole-share quantity calculated only at the next valid open from actual opening price and actual available cash;
- one-session dividend settlement;
- existing cooldown/review/stop/liquidity/cost/security-type/PIT semantics unchanged.

The close-affordability gate is the AMZN fix. A candidate that is already impossible to buy as one whole share at the close is skipped and the ranked admission search continues.

## Canonical execution harness

There is one active research implementation of Wealth Core V3 execution:

`canonical_execution_harness.py`

Technical contract identifier retained for provenance:

`wealth-core.open-time-whole-shares-10bp/2`

Median-5 remains a separate Wealth Core selection/configuration overlay and is applied before the canonical V3 execution transform. Future strategy variants must reuse this execution module rather than copy its seams.

The older `research/wealth-core-v1-open-sizing-10bp-v1` harness is historical evidence only. Its original evidence remains pinned to commit `3dc74a8e54fdfe6e8368a8db3be0ecd127ee4689`; its workflow has been retired from economic execution.

See `HARNESS_CONSOLIDATION.md` for the audit and governance rule.

## Why the affordability gate exists

The first full-PIT prototype run (`34299991647`) exposed five next-open zero-quantity blocks. Investigation showed all five were repeated AMZN admissions from 2015-12-04 through 2015-12-10 while the 19/20-slot book had only $283.521942 cash and AMZN traded above $650 per share.

The next-open sizing rule behaved correctly; the close admission rule was too weak. It admitted a candidate whenever any positive cash remained above the 10 bp reserve, even if one whole share was already unaffordable at the known close price.

V3 therefore requires:

`cash_above_10bp_reserve >= close_price * (1 + COST)`

If not, the candidate is skipped with `q0_reason = WHOLE_SHARE_UNAFFORDABLE_AT_CLOSE` and the admission search continues down the Median-5 ranked order.

This is a necessary affordability gate only. It does **not** bind share quantity at the close. Exact quantity remains determined at the next valid open from actual opening price and actual cash. An extreme overnight gap can still produce a zero-share open, so the execution guard remains in place.

See `EXECUTION_BLOCK_INVESTIGATION.md` for exact event evidence and diagnosis.

## Recorded outputs

1. Raw Wealth Core V3 metrics from `shadow_equity`.
2. Frozen EX3 / Candidate-A overlay metrics from `A_nav` on the same underlying V3 path.
3. Incremental EX3 contribution: CAGR, max drawdown, Sharpe, ending multiple, transition counts, and allocation statistics.
4. `close-decisions.csv`, including explicit close-admission skip reasons.
5. next-open sizing telemetry and transaction evidence.
6. source/data/runtime hashes and full-PIT provenance.

## Run control

The canonical workflow remains manual-only. The explicitly authorized full-PIT V3 replay is launched through a one-time research workflow so ordinary repository edits do not start additional expensive runs.

No tuning. No production change. Full canonical PIT window: 2006-07-31 through 2026-07-31.
