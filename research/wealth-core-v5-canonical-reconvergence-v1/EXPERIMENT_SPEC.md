# Wealth Core V5 canonical reconvergence v1

## Objective

Test one architectural change intended to reduce deterministic portfolio-path butterfly effects in frozen Wealth Core V5 + Sentinel EX3 V5.

This experiment is robustness-first. It must not tune parameters from historical performance.

## Frozen authority

Base commit: `f5c765e62d173839fd6b36c32d6422cec269d1c7`.

Frozen economics and strategy dimensions:

- Median-5 admission hardening remains enabled.
- 20 holdings.
- 5% target entry weight.
- V5 total-cash one-share affordability economics.
- 10 bp admission reserve.
- next-valid-open whole-share sizing.
- no fractional shares.
- one-session dividend lag.
- 30% trailing stop.
- 119-session review age.
- 21-session security/slot cooldown.
- existing one-admission-per-session throttle after initialization.
- all Sentinel EX3 V5 parameters and timing frozen.

Canonical full-PIT authority remains 2006-07-31 through 2026-07-31 with 2006-01-03 warmup.

## Single architecture change

After a holding reaches the existing 119-session review age, Wealth Core continually checks whether that holding belongs to the current canonical 20-security target.

The canonical target is constructed from the existing Median-5-hardened durable ranking and the existing positive-recent-momentum, security-type, terminal-event, and issuer-uniqueness rules. It deliberately excludes path-specific slot/security cooldown state from target membership.

The original one-time underwater review remains intact.

If an aged holding is outside the canonical target and at least one missing canonical target member is currently admissible after accounting for cooldown and issuer conflicts, the holding is marked for a normal next-open sale. At most one discretionary reconvergence sale is initiated per close. Risk exits remain unrestricted.

No replacement is force-filled. The existing close admission logic, affordability rules, cooldowns, and one-admission-per-session throttle decide the replacement normally.

## Why this is not parameter tuning

No new strategy constant is introduced. The architecture reuses the existing 119-session review boundary, current ranking, current capacity, current cooldown, and current execution rules.

No historical result is used to select a threshold, holding count, weight, Sentinel parameter, or candidate architecture.

## Validation design

### Baseline

Fresh full-PIT replays of:

1. frozen V5 + EX3 V5;
2. the single canonical-reconvergence architecture.

The frozen arm must reproduce exact baseline parity before dependent cases are allowed.

### Untouched security leave-one-out holdout

Six historical held security IDs are chosen deterministically from IDs that:

- were held by both unperturbed architectures;
- belonged to original adversarial shards 29-95, which never began leave-one-out execution before campaign cancellation;
- are ordered only by `sha256("canonical-reconvergence-holdout-v1:" + security_id)`.

Performance is not used for selection.

Each ID receives fresh causal full-PIT leave-one-out replays under both architectures.

### Universe perturbation

Fresh 1% deterministic security-ID dropout reruns using the already-frozen seeds 11, 29, and 47 under both architectures.

These are development/mechanism evidence, not untouched holdout evidence.

### Execution perturbation

Fresh 15 bp and 25 bp transaction-cost reruns under both architectures. This tests whether cost behavior becomes more economically monotonic when path sensitivity is reduced.

## Primary measurements

For every perturbation:

- exact portfolio match fraction;
- mean symmetric difference in held-security sets;
- median Jaccard overlap;
- maximum portfolio difference;
- first 20-session exact reconvergence;
- for LOO, post-last-baseline-holding reconvergence and path dispersion;
- Sentinel allocation-divergence sessions;
- Core CAGR/DD/Sharpe perturbation;
- full-system CAGR/DD/Sharpe perturbation;
- Sentinel-to-Core absolute CAGR-impact ratio.

Performance is diagnostic, not an optimization objective.

## Precommitted robustness gates

- all six untouched LOO cases complete;
- all three 1% universe-dropout cases complete;
- at least four of six untouched LOO cases have lower post-exclusion path dispersion;
- median untouched-LOO post-exclusion symmetric difference is at least halved;
- median Sentinel/Core perturbation amplification does not increase;
- median 1% dropout Core CAGR impact decreases;
- median 1% dropout full-system CAGR impact decreases;
- under reconvergence, 25 bp transaction cost must not produce a higher CAGR than 15 bp.

The old architecture's cost monotonicity is reported but is not a pass/fail requirement for the new architecture.

## Interpretation

A PASS supports the hypothesis that the main structural weakness was excess path memory in Wealth Core.

A FAIL means the reconvergence mechanism is insufficient or introduces unacceptable new instability. It does not authorize parameter tuning. Any follow-up design must be motivated mechanistically and validated on additional untouched perturbations.

Production and `main` remain untouched.
