# Sentinel EX3 V6 — exact configuration authority

## Definition

**Sentinel EX3 V6** is the exact controller configuration previously identified in research as:

`r40_m04_rec8`

It is **Sentinel EX3 V5 configured with `LDRC_REC = 8` and the full-recovery `R40` floor set to `-4%`**, paired with an unchanged **Wealth Core V5**.

This document is the naming authority for V6.

## Exact V5 → V6 delta

The generated V5 `r40_m05_rec8` source and V6 `r40_m04_rec8` source differ in exactly one economic predicate:

```diff
 full_healthy=(finite(recent_r20) and finite(recent_r40)
-              and recent_r20>0 and recent_r40>-0.05)
+              and recent_r20>0 and recent_r40>-0.04)
```

`LDRC_REC` remains `8`.

No Wealth Core V5 logic changes are part of V6. No other Sentinel threshold, state transition, exposure level, timing rule, or execution rule changes are part of V6.

## Exact research authority

- Research variant: `r40_m04_rec8`
- Experiment head: `54af0c9e50e4bf0c0d4242dafcf7fff0b75eb0f3`
- Workflow run: `34319850800`
- Artifact: `v5-ex3-impedance-r40_m04_rec8-34319850800-1`
- Artifact digest: `sha256:4f4e55715da117da0ff445633d785bd26464fa44a409cc773c32fd37f3dee5a3`
- Generated V6 source SHA-256: `335e2ae06efd5e2ebfa11f0641029609d524f4e75e733a3dbd0a5efcf64ac42d`
- Generated `r40_m05_rec8` comparator SHA-256: `ae6fc0668cb6565389c8fc9f453e8d39c57dc824c40aacc42d6d051f386425ed`
- PIT dataset SHA-256: `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`
- Measurement window: `2006-07-31` through `2026-07-31`
- Measurement sessions: `5,032`
- Replay status: `PASS_FRESH_CAUSAL_PIT_REPLAY`

Workflow URL:

`https://github.com/flabber1835/stocker/actions/runs/34319850800`

## Controller structure

Sentinel EX3 V6 has two layers:

1. The inherited Sentinel native exposure controller.
2. The EX3 recovery/divergence overlay, using the V6 `R40 = -4%`, `REC = 8` recovery configuration.

The controller can produce effective equity allocations of `0%`, `55%`, `65%`, and `100%`.

### Native controller inputs

The native controller observes Wealth Core and benchmark state using:

- Wealth Core drawdown from peak (`dd`)
- Wealth Core 5-session return (`r5`)
- Wealth Core 10-session return (`r10`)
- Wealth Core 20-session return (`r20`)
- Wealth Core 40-session return (`r40`)
- damaged breadth fraction (`dam`)
- green breadth fraction (`green`)
- 5-session damaged-breadth acceleration (`ddam5`)
- benchmark 20-session return (`spy20`)
- benchmark short/medium volatility acceleration (`volacc`)
- recent stop count (`stops20`)
- Wealth Core NAV

### Native ordinary-drawdown state

The ordinary drawdown threshold is:

- `native_ordinary_dd = -15.5%`

The state arms above that threshold and enters when Wealth Core drawdown reaches or exceeds `-15.5%` in magnitude. Its recovery health check uses positive 20-session Wealth Core return and at most two recent stops. The ordinary state participates in the slow-defensive setup.

### Native fast-defensive state

The native fast signal requires the following frozen conditions:

- drawdown `<= -10%`
- damaged breadth `>= 88%`
- green breadth `<= 20%`
- short-horizon weakness: `r5 <= -5%` or `r10 <= -8%`
- 5-session damaged-breadth acceleration `>= 30 percentage points`
- volatility acceleration `>= 4%`
- confirmation: benchmark 20-session return `<= -1%` or Wealth Core `r10 <= -10%`

Native fast recovery health is:

- Wealth Core `r20 > 0`
- damaged breadth `<= 63%`
- green breadth `>= 20%`

### Native slow-defensive state

The frozen slow conditions are:

- base defensive condition active for at least `30` sessions
- return since the base anchor `<= -2%`
- Wealth Core `r40 <= -3%`
- damaged breadth `>= 75%`
- green breadth `<= 25%`

The slow state requires its existing minimum duration and healthy-streak release logic.

### Native recovery ramp

A severe native defensive state produces `0%` equity exposure.

When the severe state clears, Sentinel examines the change in Wealth Core 40-session return over the recent recovery window. A fragile or unavailable recovery enters the staged ramp:

- first stage: `55%`
- after the first healthy persistence block: `65%`
- after the second healthy persistence block: `100%`

Each persistence block uses the inherited 10-session healthy requirement. A sufficiently improving recovery can return directly to `100%` native exposure.

## EX3 V6 overlay

### Recovery episode

A recovery episode begins when native exposure moves from full risk to below full risk.

EX3 tracks a consecutive `full_streak`. In V6, one session qualifies as `full_healthy` only when both conditions hold:

```text
recent_r20 > 0
recent_r40 > -0.04
```

The persistence requirement is:

```text
LDRC_REC = 8
```

Therefore, the persistence release route requires eight consecutive qualifying sessions.

The `-4%` comparison is strict: `recent_r40` must be greater than `-0.04`.

### Full-risk release routes

When native exposure has recovered to `100%`, EX3 permits full-risk release through any of these existing routes:

1. **Persistence release** — `full_streak >= 8`.
2. **Benchmark V-rebound release** — benchmark 20-session return `> +11%`.
3. **Cross-surface concordance release** — all of the following hold:
   - recent-positive streak `>= 8`
   - Wealth Core 20-session return `> 0`
   - recent 20-session return is at least the Wealth Core 20-session return
   - benchmark 20-session return is at least the Wealth Core 20-session return

Until a release route succeeds, the overlay retains its previous desired exposure while native is attempting to return to full risk.

### Divergence latch

The EX3 divergence latch enters when all required observations are available and:

- native target is `100%`
- effective native exposure is `100%`
- Wealth Core drawdown `<= -10%`
- recent 20-session return `<= -8.5%`
- benchmark 20-session return `>= 0%`

When latched, desired exposure is capped at:

```text
55%
```

The latch clears through the existing recovery routes:

- `full_streak >= 8`, or
- benchmark 20-session return `> +11%`

The EX3 overlay always respects the native controller ceiling. Final desired exposure cannot exceed the current native target.

## Frozen V6 parameter set

| Parameter | V6 value |
|---|---:|
| `rec` / `LDRC_REC` | `8` |
| full-recovery `r40_floor` | `-0.04` |
| `ldrc_r20` | `-0.085` |
| `ldrc_v` | `0.11` |
| `ldrc_dd` | `-0.10` |
| `ldrc_ceiling` | `0.55` |
| `divergence_spy_floor` | `0.0` |
| `native_ordinary_dd` | `-0.155` |
| native fast drawdown | `-0.10` |
| `fast_damaged` | `0.88` |
| `native_fast_green` | `0.20` |
| `native_fast_r5` | `-0.05` |
| `native_fast_r10` | `-0.08` |
| `native_fast_damaged_delta5` | `0.30` |
| `native_fast_volacc` | `0.04` |
| `native_fast_spy20` | `-0.01` |
| `native_fast_r10confirm` | `-0.10` |
| `healthy_damaged` | `0.63` |
| native slow minimum base duration | `30` sessions |
| native slow anchor return | `-0.02` |
| native slow `r40` | `-0.03` |
| native slow damaged breadth | `0.75` |
| native slow green breadth | `0.25` |

## Wealth Core pairing

The research authority pairs V6 with unchanged Wealth Core V5:

- `20` slots
- `5%` target entry weight
- Median-5 ranking logic
- `10 bp` cash buffer
- next-valid-open execution
- whole-share sizing
- total-cash affordability basis

The replay explicitly verified exact Wealth Core parity across the controller experiment:

- Wealth Core tape SHA-256: `3b40a23a7e499e0314f1d6e86b767fba648136758fdd106cdfd0ff27620b545f`
- Wealth Core transactions SHA-256: `0e4828229c323ab029a5dfe49f258a3e2e379aee6b5e18169e72f9edc88652da`
- Wealth Core close decisions SHA-256: `d1f557bd139e3445538e3f94bce90fe296eba19450d939c4160fe0880e067724`

## Causal timing

The controller evaluates close-state information and places the resulting target into the pending allocation state. The pending target becomes effective on the following session. The research harness includes a causal timing guard preventing the same-session close decision from reaching the same-session allocation.

## Historical replay evidence

For the exact `r40_m04_rec8` V6 authority over `2006-07-31` through `2026-07-31`:

| Horizon | CAGR | Max drawdown | Sharpe | Ending multiple |
|---|---:|---:|---:|---:|
| 5 years | 31.03% | -20.42% | 1.347 | 3.8566× |
| 10 years | 26.47% | -27.38% | 1.247 | 10.4619× |
| 15 years | 22.24% | -27.38% | 1.178 | 20.3179× |
| 20 years | 21.56% | -27.38% | 1.121 | 49.6193× |

Twenty-year allocation behavior:

- average equity allocation: `85.0079%`
- `0%` exposure: `634` sessions
- `55%` exposure: `252` sessions
- `65%` exposure: `20` sessions
- `100%` exposure: `4,126` sessions
- allocation transitions: `28`
- recovery episodes: `8`
- cross-surface concordance releases: `2`

## Relationship to Sentinel EX3 V5

The selected EX3 V5 comparator uses:

```text
REC = 8
R40 floor = -5%
```

V6 uses:

```text
REC = 8
R40 floor = -4%
```

The `-4%` floor is a stricter persistence-health requirement. A session with `recent_r40` between `-5%` and `-4%` can advance the V5 persistence streak and cannot advance the V6 persistence streak.

On the recorded 20-year impedance replay, V5 `r40_m05_rec8` and V6 `r40_m04_rec8` produced the same realized `A_nav` path and the same realized `A_allocation` path. Their configuration and generated source are distinct. The historical path did not contain a threshold-bound decision that changed realized exposure between these two settings. Future or synthetic paths can separate them when the `-5%` to `-4%` interval becomes decision-relevant.

## Research-harness label note

The impedance harness computes `a_d` from the EX3 Candidate-A controller. In this harness, both `control` and `A` pending allocations are assigned `a_d`. Consequently, `control_nav` and `A_nav` represent the same EX3 Candidate-A exposure path in this experiment. This explains graphs sourced from `control_nav` for `r40_m04_rec8`.

## Naming rule

From this point forward, **Sentinel EX3 V6** means exactly the configuration defined here: **the `r40_m04_rec8` controller, equivalent to Sentinel EX3 V5 mechanics with the full-recovery R40 floor set to `-4%` and `REC = 8`**.

Any future change to these controller parameters, state transitions, timing rules, or exposure semantics requires a new configuration identity/version.
