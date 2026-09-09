# Wealth Core V5 + Sentinel EX3 V5 — adversarial campaign v1

## Objective

Attack the frozen **Wealth Core V5 + Sentinel EX3 V5** configuration without tuning it. The campaign is validation-only. Results may diagnose fragility but may not be used by the runner to select new parameters.

## Frozen authority

Wealth Core V5:
- Median-5
- 20 holdings
- 5% target entry weight
- 10 bp close admission reserve
- total-cash one-share affordability
- next-valid-open whole-share sizing
- no fractional shares
- one-session dividend lag

Sentinel EX3 V5:
- REC = 8 sessions
- recent-leadership R20 divergence threshold = -8.5%
- SPY V rebound = +11%
- Wealth Core drawdown divergence threshold = -10%
- SPY divergence floor = 0%
- full-recovery recent-leadership R40 floor = -5%
- divergence ceiling = 55%
- FAST damaged breadth = 88%
- healthy damaged ceiling = 63%

Measurement authority is the same canonical full-PIT 2006-07-31 through 2026-07-31 path used by the impedance study, with 2006-01-03 warmup.

## Hard baseline gates

The campaign starts with a fresh full-PIT replay and refuses to continue the dependent suites unless all frozen authorities reproduce:
- canonical dataset hash
- 5,032 measured sessions
- exact Wealth Core core-tape hash
- exact transaction hash
- exact close-decision hash
- one-session dividend lag
- exact Sentinel EX3 V5 20-year CAGR, max drawdown and Sharpe
- next-open controller timing / no same-session allocation path

## Test classes

### A. Ex-post attribution jackknives

These operate on the frozen realized path and are explicitly marked `EX_POST_PATH_ATTRIBUTION_NOT_CAUSAL_RERUN`:
- leave one calendar year out
- leave one calendar quarter out
- remove best 1/3/5/10/20 strategy sessions
- remove worst 1/3/5/10/20 sessions as controls
- neutralize each Sentinel defensive episode back to Wealth Core returns
- fixed historical regime decomposition
- exposure-state and transition diagnostics
- benchmark beta/alpha/Sortino/Calmar diagnostics
- deterministic 20-session moving-block bootstrap

They measure concentration and attribution. They are not represented as alternate causal histories.

### B. Fresh causal full-PIT reruns

Controller neighborhood / cliff tests:
- REC 7 / 9
- R40 floor -4% / -6%
- R20 -8.0% / -9.0%
- SPY V +10% / +12%
- drawdown -9% / -11%
- divergence ceiling 50% / 60%
- FAST damaged 86% / 90%
- healthy damaged 61% / 65%

Mechanism ablations:
- divergence latch disabled
- SPY V release disabled
- FAST native defense disabled
- ordinary native defense disabled
- cross-surface release disabled
- recovery-persistence release disabled
- divergence persistence-clear disabled

Wealth Core structural jackknife:
- 18 holdings reciprocal weight
- 19 holdings at fixed 5% and reciprocal weight
- 21 holdings at fixed 5% and reciprocal weight
- 22 / 24 / 26 holdings reciprocal weight

Execution stress:
- 15 / 25 / 50 bp transaction cost
- 25 / 50 bp adverse open fills on both buys and sells
- one additional session of entry delay

Universe robustness:
- deterministic security-ID dropout at 1%, 5% and 10%
- three frozen seeds at every dropout level

### C. Exhaustive held-security leave-one-out

The baseline measured book emits the union of exact historical security IDs actually held. Every such ID is then excluded from eligibility from the beginning of a fresh full-PIT replay, one security at a time.

This is an exhaustive causal security jackknife. It is sharded for execution efficiency; a shard result is incomplete evidence until all shards finish.

### D. Harness fault injection

The baseline runner also verifies that deliberately illegal mutations are rejected:
- same-session controller allocation/lookahead mutant
- zero-session dividend-lag mutant
- dataset-hash mutation
- core-hash mutation

## Interpretation contract

- No test is allowed to rewrite `SELECTED` from observed performance.
- Local perturbations are cliff detectors, not candidate selection.
- Mechanism ablations are attribution diagnostics, not proposed strategies.
- Ex-post jackknives and fresh causal replays are labeled separately.
- Baseline authority failure is a hard failure.
- Perturbation underperformance is evidence, not a workflow failure.
- Production and `main` are untouched.
