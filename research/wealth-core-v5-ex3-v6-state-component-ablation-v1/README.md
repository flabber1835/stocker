# Wealth Core V5 + Sentinel EX3 V6 state-component ablation

## Objective

Identify which carried Sentinel state mechanisms amplify small Wealth Core path perturbations, and measure the baseline economic value contributed by each mechanism.

Research only. No production/main behavior is modified or promoted.

## Pinned authority

- Wealth Core V5 / Sentinel EX3 V6 selected-source SHA-256: `335e2ae06efd5e2ebfa11f0641029609d524f4e75e733a3dbd0a5efcf64ac42d`
- Published EX3 V6 authority: `96f705c3b699ec283dbac7e93b973dba9769f038`
- Replay harness authority: `eaddca3f04f279e99663f832bf7293e92ee15662`
- V6 configuration: `rec=8`, `r40_floor=-0.04`, `fast_damaged=0.88`, `healthy_damaged=0.63`
- Warmup: 2006-01-03 onward
- Measurement: 2006-07-31 through 2026-07-31, 5,032 sessions

## Method

Each full-PIT job executes Wealth Core only once. The generated source is instrumented only to emit the exact observable inputs needed to replay Sentinel.

After the engine finishes:

1. the authoritative Native + CandidateA controller is replayed independently from the emitted tape;
2. its allocations, NAV, Native target, effective-Native state, and reason must match the engine's current Sentinel path;
3. only after that parity proof are six one-component counterfactual controllers evaluated on the same tape.

This avoids re-running Wealth Core separately for every Sentinel ablation and makes the causal comparison same-tape by construction.

## Six ablations

1. **`native_base_anchor`** — removes the carried Native base anchor. While base is active, the anchor is the current NAV, so old anchor history cannot influence the current slow trigger.
2. **`native_base_duration`** — removes elapsed base-duration memory. While base is active, the duration qualification is treated as already satisfied; the anchor and all other slow predicates remain.
3. **`native_slow_persistence`** — preserves the slow trigger but removes persistence/recovery-age memory; slow is active only while the current slow predicate is true.
4. **`native_recovery_ramp`** — preserves severe-state logic but removes the carried 55%/65% recovery ramp; recovery returns directly to full exposure.
5. **`ex3_episode_memory`** — removes EX3 recovery-episode memory / `FULL_RISK_HELD`; EX3 latch logic remains.
6. **`ex3_latch_memory`** — removes EX3 divergence-latch entry; recovery-episode behavior remains.

Each variant changes one named mechanism. These are causal ablations, not proposed production implementations.

## Fault set

Eight full-PIT jobs:

- one no-fault baseline;
- six deterministic held-security leave-one-out faults:
  - `301606049357818446`
  - `1040633074096912075`
  - `277347208162984956`
  - `727329233939509358`
  - `425931792436652190`
  - `311453645065866101`
- one deterministic 1% universe dropout, seed `11`.

The fault is injected only into Wealth Core's opportunity set. Sentinel state/output is never forced.

## Measurements

For current Sentinel and every ablation:

- baseline CAGR, max drawdown, Sharpe, ending multiple;
- fault allocation-difference sessions;
- integrated absolute allocation-divergence area;
- first/last divergence and terminal reconvergence;
- fault-induced CAGR/MDD/Sharpe dispersion;
- baseline economic delta versus current Sentinel.

A research screen highlights variants with:

- at least 50% median fault-area reduction on cases where current Sentinel is affected; and
- no more than 1 percentage point absolute baseline CAGR loss.

MDD change is reported separately and is not hidden by that screen.

## Interpretation guard

A strong ablation result identifies a state mechanism worth redesigning. It does not establish that deleting that state is a production-quality solution. Any redesign still requires optimization, adversarial testing, and full certification.
