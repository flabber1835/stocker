# Wealth Core / Sentinel architecture-defect investigation — 2026-09-04

## Status

Research design. No production activation. `main` is read-only.

This investigation has an owner-authorized hard budget of **at most 10 completed economic backtest experiments**. Screening calculations against prior daily evidence do not consume the budget and may never be reported as backtest results. A completed candidate arm in a fresh chronological replay consumes one experiment.

## Baseline

The control is Strategy 9, **Broad simplified fixed breadth calibration**.

- Source lineage: `research/backtester-sp500-pit`
- Authoritative historical control run: Actions `33876316789`
- Control head: `238891bf67cc75afa3efd4b82b71cfdb52c2fd75`
- Control artifact: `9939066139`
- FAST damaged breadth minimum: `0.875`
- healthy/recovery damaged breadth ceiling: `0.625`
- Wealth Core, FAST return/acceleration predicates, SLOW, native recovery ramp, LD-RC, peer construction, price domains and execution timing remain the control mechanics.

The later dynamic breadth experiment is economically identical to this control. Breadth-threshold adaptation is therefore outside this investigation unless a later candidate exposes new falsifying evidence.

## Objective

Find and correct simple mechanical defects in the architecture, then calibrate only the resulting architecture. A candidate must explain a failure mode structurally and improve more than the episode that motivated it.

The priority is lower drawdown and better recovery economics while preserving long-horizon return and causal simplicity.

## Diagnosed defects

### D1 — LD-RC entry observes the opportunity set when the stateful owned book is the object at risk

The current divergence latch requires:

```
Wealth Core drawdown <= -10%
recent-leadership r20 <= -8%
SPY r20 >= 0
native and effective-native exposure both full
```

`recent-leadership` is a causal zero-capital basket of the current top recent-return candidates. It can rotate immediately. Wealth Core is stateful: it owns existing slots subject to its stop, review and cooldown mechanics.

In August 2018 the owned Wealth Core shadow had already reached roughly a 10% drawdown and its own 20/40-session returns were materially negative while SPY r20 remained positive. The recent-leadership witness was much less damaged. The latch therefore observed a healthier replacement opportunity set while the actual owned cohort was deteriorating.

This is a sensor/object mismatch. It is not a breadth-scale defect.

### D2 — recovery is certified twice on overlapping evidence

Native SLOW recovery already requires its own duration and healthy-state evidence. After native recovery, LD-RC can continue to hold the account at the prior lower allocation until **both** recent-leadership r20 and r40 are positive for seven consecutive sessions, or SPY r20 exceeds the V-rebound threshold.

In 2019 native recovered on 25 January. The r40 zero crossing kept LD-RC defensive until 22 February. The extra gate therefore delayed exposure after the native controller had already certified recovery.

The retained r20-only challenger is not an acceptable fix because it also removes the divergence latch; the historical bundle shows that the divergence protection is load-bearing. The repair must preserve the latch.

## Experiment 1 — owned-book divergence mode

Keep the complete Strategy 9 LD-RC state machine and existing recent-leadership divergence mode. Add one alternative entry mode using the immutable Wealth Core shadow itself:

```
owned_book_divergence =
    native >= 1
    AND effective_native >= 1
    AND wc_drawdown <= -0.10
    AND wc_r20 < 0
    AND wc_r40 <= -0.08
    AND spy_r20 >= 0
```

The two entry modes are ORed. Both use the existing 55% divergence ceiling and existing latch/release mechanics.

Parameter discipline:

- `-0.10` reuses the existing LD-RC drawdown threshold.
- `-0.08` reuses the existing LD-RC deterioration magnitude.
- `0` is a sign test that requires the owned book to still be declining over 20 sessions. It prevents a stale negative 40-session return from treating a V-shaped recovery as continuing divergence.
- No new fitted numeric threshold is introduced.

Hypothesis: this catches the 2018 stateful-cohort failure while preserving the current recent-leadership mode for other divergence episodes.

## Experiment 2 — single-horizon recovery confirmation, latch preserved

Keep the complete Strategy 9 divergence-entry logic and divergence ceiling.

Separate the recovery-episode confirmation clock from the divergence-latch clearing clock. The divergence latch retains its current recovery rule. The post-severe recovery episode uses:

```
recovery evidence may accumulate only after native target > 0
recent-leadership r20 > 0
7 consecutive sessions
OR existing SPY V-rebound
```

The clock resets while native target is zero. It may accumulate during the native 55%/65% recovery ramp. When native reaches 100%, LD-RC releases immediately if the seven-session r20 confirmation has already been earned; otherwise it holds the prior desired allocation until it is earned.

This removes the 40-session zero-crossing requirement from the second recovery certification and preserves the same seven-session persistence. No new numeric threshold is introduced.

Hypothesis: this removes the 2019 double-recovery delay while retaining the conservative native severe gate and the existing divergence protection.

## First replay construction

The first fresh replay advances three LD-RC arms on every historical session over the same immutable Wealth Core shadow and native controller state:

1. `CONTROL` — exact Strategy 9.
2. `E1_OWNED_DIVERGENCE` — Experiment 1 only.
3. `E2_RECOVERY_SIMPLIFICATION` — Experiment 2 only.

All arms see identical session data before the replay advances. The candidate controllers do not feed back into Wealth Core, native Sentinel, universe construction, breadth, corporate actions or prices.

This replay consumes **2 / 10** experiments if both candidate arms complete economically. The control arm is a parity check and does not consume a new experiment.

## Acceptance and rejection

A candidate is retained for a combined experiment only if all of these hold:

1. Fresh control reproduces the Strategy 9 daily control allocation and NAV path to numerical tolerance.
2. Candidate uses only contemporaneous or strict-prior information already present in the causal replay.
3. Candidate improves the motivating failure mode mechanically, not by a one-day lucky fill.
4. Full-history maximum drawdown does not materially worsen.
5. Long-horizon CAGR and Sharpe do not show a material degradation.
6. Crisis/event attribution shows the change is not dominated by the 2018-2019 episode alone.
7. The rule remains explainable with a small state surface and no episode-specific dates or thresholds.

A candidate failing any architecture or causality condition is rejected before economic interpretation.

## Budget ledger

| Experiment | Candidate | Status |
|---|---|---|
| 1 | owned-book divergence mode | planned |
| 2 | single-horizon recovery confirmation with latch preserved | planned |
| 3 | combined E1 + E2 | reserved if both survive |
| 4 | one recovery-velocity refinement | reserved only if Experiment 2 exposes a specific falsifier |
| 5 | one neighboring-threshold/stability check | reserved for the surviving architecture |
| 6-10 | robustness / final architecture | uncommitted |

Unused experiments remain unused. The investigation may stop before ten.
