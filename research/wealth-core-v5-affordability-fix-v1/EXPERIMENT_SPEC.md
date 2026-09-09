# Wealth Core V5 + Sentinel EX3 experiment specification

Status: specification only. No V5 performance run has been executed yet.

## Objective

Measure Wealth Core V5 over the canonical 20-year PIT window with frozen Sentinel EX3 / Candidate-A in parallel.

V5 exists to correct the affordability defect discovered in the fixed-V3 / V4 close-admission rule.

## Base economic configuration

Wealth Core V5 retains:

- Median-5 ranking hardening
- 20 slots
- 5% target entry weight
- 10 bp close-time cash/admission cushion
- next-valid-open whole-share sizing
- fractional shares disabled
- one-session dividend lag
- exact quantity determined only at the next valid open
- existing invalid-open and zero-quantity guards
- frozen Sentinel EX3 / Candidate-A controller path from the same Wealth Core path

## V5 affordability contract

The close performs two separate checks.

### 1. Admission-cushion check

```text
reserve = max(0, close_nav * 0.001)
cash_above_reserve = max(0, total_cash - reserve)

require cash_above_reserve > 0
```

The 10 bp reserve remains a close-time admission cushion.

### 2. One-share feasibility check

```text
one_share_close_cost = close_price * (1 + COST)

require total_cash >= one_share_close_cost
```

This check must use **total cash**, not `cash_above_reserve`.

Reason: the 10 bp admission cushion is released into the execution funding pool at the next open.

## Next-open execution contract

The close must not bind quantity.

At the next valid open:

```text
execution_budget = max(0, min(intended_target_dollars, actual_cash))
quantity = floor(execution_budget / (actual_open_price * (1 + COST)))
```

Requirements:

- whole shares only;
- no fractional execution;
- actual open price determines quantity;
- actual cash at execution determines quantity;
- 10 bp close cushion is not withheld from next-open funding;
- zero-quantity guard remains active for extreme overnight gaps or other execution-time infeasibility.

## Required behavioral witnesses

The implementation must prove these cases before performance results are accepted.

### AGN1 false-rejection witness

On the historical `2014-05-23` decision state from the V4 evidence:

- total cash approximately `$232.45`;
- reserve approximately `$214.46`;
- cash above reserve approximately `$17.99`;
- AGN1 close approximately `$166.92`.

V4 incorrectly treated AGN1 as one-share unaffordable because it compared the share cost with only `$17.99`.

V5 must not reject AGN1 for that reason because total cash is sufficient for one share at the known close.

### AMZN true-unaffordability witness

The original repeated AMZN case must remain protected.

When total cash is below the cost of one AMZN share at the close, AMZN must be recorded as a total-cash one-share-unaffordable skip and must not reserve a slot.

### Gap-risk witness

A candidate that is affordable at the close but becomes unaffordable after an overnight gap may still produce a next-open zero-quantity block. That guard must remain; V5 must not pre-bind a quantity to eliminate it.

## Evidence requirements

The V5 run must emit at minimum:

- `RESULT.json`
- `daily.csv`
- `summary.json`
- `transactions.csv`
- `close-decisions.csv`
- `open-sizing-events.csv`
- `open-sizing-telemetry.json`
- generated economic source
- source/data hashes
- final corpus validation

Telemetry must distinguish at least:

- close cash-scarcity skips;
- close total-cash one-share-unaffordable skips;
- next-open invalid-market blocks;
- next-open zero-quantity blocks;
- completed entries;
- cash-limited executions;
- whole-share rounding underfill;
- fractional-share violations, which must remain zero.

## Causal invariants

Before interpreting performance, verify:

1. canonical PIT dataset and frozen source authorities are unchanged;
2. measurement window is unchanged;
3. Median-5 ranking hashes are unchanged from the V4 comparison path;
4. slots remain exactly 20;
5. target entry weight remains exactly 5%;
6. cash buffer remains exactly 10 bp;
7. dividend lag remains exactly one session;
8. fractional shares remain disabled;
9. Sentinel EX3 / Candidate-A logic is unchanged;
10. only the one-share affordability cash basis changes from V4.

## Measurement horizon

- warmup start: `2006-01-03`
- measurement start: `2006-07-31`
- measurement end: `2026-07-31`
- expected measurement sessions: `5,032`

Report Wealth Core and Wealth Core + EX3 for:

- 20 years
- 15 years
- 10 years
- 5 years

For each horizon report at least:

- CAGR
- maximum drawdown
- Sharpe
- ending multiple

Also report EX3 incremental contribution.

## Comparison set

The V5 result should be compared against both:

### Pre-fix V3

Run `34299991647`, artifact `10085231668`.

This is useful as the historical path before either affordability repair, but it contains the original AMZN zero-quantity defect.

### V4 / fixed-V3

V4 run `34308443342`, artifact `10088101728`.

This is the direct A/B control for V5 because V5 changes only the affordability cash basis from V4.

## No performance tuning

No CAGR, drawdown, Sharpe, trade-count, or EX3 target may be used to alter V5 before the replay.

The purpose of the experiment is causal correctness first and performance measurement second.