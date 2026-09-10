# Wealth Core V5 + Sentinel EX3 V6 state architecture experiment

## Objective

Measure how much of the observed Wealth Core fault amplification requires Sentinel's carried internal state.

This is research-only. It does not modify or promote production/main behavior.

## Pinned authority

- Wealth Core V5 / Sentinel EX3 V6 selected source SHA-256: `335e2ae06efd5e2ebfa11f0641029609d524f4e75e733a3dbd0a5efcf64ac42d`
- Published V6 authority: `96f705c3b699ec283dbac7e93b973dba9769f038`
- Replay harness authority: `eaddca3f04f279e99663f832bf7293e92ee15662`
- V6 configuration: `rec=8`, `r40_floor=-0.04`, `fast_damaged=0.88`, `healthy_damaged=0.63`
- Full-PIT measurement: 2006-07-31 through 2026-07-31, 5,032 sessions; warmup starts 2006-01-03.

## Architectures

The exact Wealth Core observation tape is shared by all three tracks inside each replay.

1. **Current** — authoritative Native + EX3 V6 with its normal carried state. This remains byte-preserved as track `A`.
2. **State-minimal 60** — the exact Native + CandidateA transition logic is reconstructed from scratch each session using only the most recent 60 observable sessions. No hidden controller state older than 60 sessions can affect the decision. Sixty sessions deliberately spans the major existing time constants: 30-session slow qualification, 20-session slow recovery age, and the recovery ramp/confirmation horizon.
3. **Stateless 1** — the exact Native + CandidateA transition logic is reconstructed from scratch from the current observable session only. No hidden Sentinel state crosses a session boundary.

`Stateless` does **not** mean that rolling features are forbidden. R5/R10/R20/R40, breadth, drawdown and SPY features are observable inputs and may summarize market history. What is removed is hidden controller state such as anchors, episode flags, latches, duration counters and recovery/ramp history.

Both treatment tracks preserve the source's one-session application timing and use the same overlay/cost calculation as the current track.

## Fault set

Eight full-PIT replay slots are used: one no-fault baseline plus the same seven deterministic Stage-3 perturbations used in convergence V2.

Six leave-one-out security faults:

- `301606049357818446`
- `1040633074096912075`
- `277347208162984956`
- `727329233939509358`
- `425931792436652190`
- `311453645065866101`

One deterministic 1% universe dropout:

- seed `11`

The fault remains upstream in Wealth Core. No later Sentinel state or output is forced.

## Primary measurements

For each architecture and fault:

- allocation-difference sessions versus that architecture's no-fault baseline;
- integrated absolute allocation-difference area;
- first/last divergence and terminal reconvergence;
- CAGR, maximum drawdown, Sharpe and ending multiple;
- economic delta from the architecture's no-fault baseline;
- Wealth Core holding-set divergence to verify the initiating perturbation.

The final aggregate reports robustness improvement relative to current Sentinel and the economic cost/benefit of each architecture. There is no automatic promotion threshold.

## Interpretation

This experiment answers a causal architecture question: whether bounded or absent hidden Sentinel state materially reduces the downstream amplification of identical Wealth Core perturbations. It does not establish that a lower-state controller is economically superior. Any candidate redesign would require a separate optimization and certification campaign before promotion.
