# Wealth Core V5 + Sentinel EX3 V5 structural drawdown execution study

Date: 2026-09-09 UTC

## Objective

Test structural release/execution weaknesses that can reduce maximum drawdown without changing Wealth Core V5 stock selection or Sentinel EX3 V5 predictive entry economics.

This is not a historical parameter optimization. The complete ten-arm matrix is fixed before observing any result from this study.

## Frozen authority

Wealth Core V5 remains frozen at:

- Median-5 ranking
- 20 holdings
- 5% target entry weight
- 10 bp close admission reserve
- total-cash one-share affordability
- next-valid-open whole-share sizing
- one-session dividend lag

Sentinel EX3 V5 remains frozen at:

- LDRC_REC = 8
- LDRC_R20 = -8.5%
- LDRC_V = +11.0%
- LDRC_DD = -10.0%
- divergence SPY floor = 0.0%
- selected native/full-recovery recent-leadership r40 floor = -5.0%
- divergence ceiling = 55.0%
- native FAST damaged breadth = 88.0%
- native healthy damaged ceiling = 63.0%

The already-certified Sentinel EX3 V5 replay from Actions run 34319850800 is the baseline and does not consume one of the ten new slots.

## Structural hypotheses

1. Native-recovery and divergence-release are different risk states and should not share one recovery clock.
2. Downward transitions should remain immediate, while upward transitions can be staged through exposure levels that already exist in the controller: 0%, 55%, 65%, 100%.
3. Re-risking should require positive recovery evidence; renewed weakness should halt upward progress.
4. Any benefit should survive broader confirmation persistence rather than depend on one exact historical session.

No new predictive market signal is introduced.

## Ten fixed arms

### Single-mechanism attribution

1. `split_clocks` — native recovery keeps r40 > -5%; divergence release requires its own r40 > 0% streak.
2. `global_tier` — any upward controller transition advances by at most one existing exposure tier per decision session.
3. `positive_gate` — upward transitions require recent-leadership r20 > 0 and r40 > 0; downward transitions remain immediate.
4. `divergence_tier` — tiered re-risking only after divergence release.
5. `native_tier` — tiered re-risking only after native-defense release.

### Predeclared combinations

6. `split_divergence_tier` — split clocks + divergence-only tiering.
7. `split_divergence_tier_gate` — split clocks + divergence tiering + positive recovery gate.
8. `split_global_tier_gate` — split clocks + global tiering + positive recovery gate.

### Robustness

9. `split_global_tier_gate_c2` — arm 8 with two qualifying sessions before each upward tier.
10. `split_global_tier_gate_c3` — arm 8 with three qualifying sessions before each upward tier.

## Anti-overfit rules

- Do not add, remove, or change arms after seeing partial results.
- Do not tune thresholds to named historical episodes.
- Do not use CAGR, drawdown, Sharpe, or episode outcomes to change an in-flight arm.
- Existing 0/55/65/100 exposure levels are reused; no fitted intermediate exposure level is introduced.
- Results are interpreted by mechanism attribution first and aggregate performance second.

## Evidence

Every arm must:

- use canonical PIT dataset hash `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`;
- use warm-up start 2006-01-03 and measurement 2006-07-31 through 2026-07-31;
- reproduce the exact frozen Wealth Core V5 core-tape, transactions, and close-decision hashes;
- emit 5/10/15/20-year metrics;
- emit maximum-drawdown peak/trough attribution including effective exposure transitions between peak and trough.

## Scope

Research only. No production, main, Wealth Core V5, or Sentinel production behavior is modified.