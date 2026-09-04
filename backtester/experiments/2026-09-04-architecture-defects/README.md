# Wealth Core / Sentinel architecture-defect investigation — 2026-09-04

## Status

Research only. No production activation. `main` is read-only.

Owner-authorized hard budget: **at most 10 completed economic candidate experiments**. Screening against prior daily evidence does not consume the budget and is never promoted as backtest evidence. A candidate arm that completes a fresh chronological economic replay consumes one experiment. Infrastructure failures before a measured candidate replay do not consume the budget.

**Budget consumed: 2 / 10.**

## Baseline

The control is Strategy 9, **Broad simplified fixed breadth calibration**.

- Source lineage: `research/backtester-sp500-pit`
- Historical control run: Actions `33876316789`
- Control head: `238891bf67cc75afa3efd4b82b71cfdb52c2fd75`
- Control artifact: `9939066139`
- FAST damaged breadth minimum: `0.875`
- healthy/recovery damaged breadth ceiling: `0.625`
- Wealth Core, FAST return/acceleration predicates, SLOW, native recovery ramp, LD-RC, peer construction, price domains and execution timing are the baseline mechanics.

The later dynamic breadth experiment changed thresholds repeatedly but produced identical signals and allocations. Breadth-scale tuning is on an economic plateau and is outside this architecture pass.

## Objective

Correct simple mechanical defects, then calibrate only a surviving architecture. A retained rule must explain a failure mode structurally and remain useful across multiple episodes. Simplicity and parameter economy are acceptance requirements.

## Diagnosed architecture issue

The 2018-2019 path contains two distinct phenomena:

1. the stateful owned Wealth Core book deteriorated before the broad market; and
2. after severe defense, LD-RC delayed recovery because its full confirmation requires both recent-leadership r20 and r40 to be positive for seven sessions, or the existing SPY V-rebound.

The first two candidate repairs established important negative evidence.

## Experiment 1 — owned-book divergence mode — REJECTED

Candidate: preserve current LD-RC and OR in a second divergence entry using the owned book:

```
native >= 1
AND effective_native >= 1
AND wc_drawdown <= -0.10
AND wc_r20 < 0
AND wc_r40 <= -0.08
AND spy_r20 >= 0
```

Fresh full-history candidate replay completed in Actions run `33908036047`.

Measured max-period result:

- baseline: CAGR `19.7934%`, max DD `-33.4590%`, Sharpe `1.06675`
- E1: CAGR `19.6191%`, max DD `-33.4590%`, Sharpe `1.06530`

E1 added 10 owned-book divergence entries and raised allocation transitions from 37 to 50 without improving maximum drawdown. Post-run episode screening shows the new sensor frequently engaged during rebounds, including 2004, 2016, August 2018 and 2024. It helped the November-December 2018 decline but its false defensive episodes outweighed that benefit.

**Decision: reject.** The stateful-book diagnosis is real, but this direct OR trigger is too permissive.

## Experiment 2 — r20-only post-severe recovery — REJECTED

Candidate: preserve the existing divergence latch and its release rule. For the separate post-severe recovery episode, permit full-risk certification after seven consecutive recent-leadership `r20 > 0` sessions once native exposure has left zero, retaining the existing SPY V-rebound alternative.

Fresh full-history candidate replay completed in Actions run `33908036047`.

Measured max-period result:

- baseline: CAGR `19.7934%`, max DD `-33.4590%`, Sharpe `1.06675`
- E2: CAGR `19.6964%`, max DD `-37.1649%`, Sharpe `1.05665`

E2 solves the intended 2019 delay, but it mistakes the 2000 bear-market rebound for durable recovery and stays exposed far too early. The maximum drawdown deterioration is material.

**Decision: reject.** The r40 gate is economically load-bearing as protection against false recovery. The repair must distinguish broad durable repair from a rebound inside a damaged book.

## Control-parity note from the E1/E2 run

The full replay produced the historical Strategy 9 max-period economics and all observed year-end control multiples, but the experiment wrapper's overly broad byte-level projection hash failed after output-schema telemetry was added. No candidate is promoted from that run. Future candidate wrappers must avoid inserting telemetry into the baseline output row and must validate the untouched economic path independently after replay.

## Experiment 3 — cross-surface recovery concordance — PLANNED

### Mechanical premise

A false recovery can look excellent inside the damaged owned book. In June 2000 the owned Wealth Core 20-session rebound was much stronger than both the current leadership basket and SPY. In February 2019 the opposite geometry held: the owned book was recovering, while both current leadership and SPY were at least as strong.

The early-release test therefore asks whether recovery is **concordant across all three surfaces**:

- the owned stateful book;
- the current investable leadership opportunity set; and
- the broad market.

### Rule

The existing LD-RC post-severe recovery remains the fallback and is unchanged. Add one early full-risk release path while a recovery episode is active:

```
recent_positive_streak >= existing LDRC_REC  # 7 sessions
AND wc_r20 > 0
AND recent_leadership_r20 >= wc_r20
AND spy_r20 >= wc_r20
```

The recent-positive streak accumulates only while the recovery episode is active and native target is above zero. A non-positive or unavailable recent r20 resets it. All comparisons use same-session causal 20-session returns already available in the replay. The rule is evaluated at the close and any exposure change remains next-open effective.

### Parameter discipline

- `7` is the existing LD-RC recovery persistence; no new duration is introduced.
- `0` is only a sign boundary.
- `recent >= core` and `SPY >= core` are relative comparisons, not calibrated thresholds.
- No new exposure level, lookback horizon, percentile, crisis date or fitted numeric constant is introduced.
- Existing full recovery and SPY V-rebound remain unchanged fallback routes.
- Existing divergence entry/latch mechanics remain unchanged.

### Pre-run falsification screening

Screening on the prior Strategy 9 daily evidence is diagnostic only. It indicates this rule would add early release on only three historical recovery episodes:

| decision date | current control posture after next open | candidate posture | subsequent candidate-difference interval |
|---|---:|---:|---|
| 2012-01-18 | 0% | 100% | 2012-01-19 through 2012-01-26 |
| 2016-02-25 | 65% | 100% | 2016-02-26 through 2016-03-11 |
| 2019-02-04 | 0% | 100% | 2019-02-05 through 2019-02-22 |

It does **not** release early in the 2000-2001, 2008-2009 or 2022 false/weak recovery cases. All three screened added-risk intervals happened to have positive raw Wealth Core returns; that fact is a falsifier target for the fresh replay, not an acceptance claim.

### Experiment 3 acceptance

Experiment 3 survives only if the fresh replay proves all of the following:

1. untouched Strategy 9 control path reproduces within the pinned control tolerance;
2. the candidate changes only the three expected recovery episodes or produces an explainable additional episode from the fresh causal state;
3. max-period and 20-year maximum drawdown do not materially worsen;
4. long-horizon CAGR/Sharpe are not degraded;
5. the 2019 recovery opportunity cost is reduced;
6. no 2000-2001 early release occurs;
7. no new numeric tuning is introduced after seeing the result.

Failure closes this candidate. There is no threshold adjustment inside Experiment 3.

## Acceptance principles for later work

A surviving architecture must use contemporaneous/strict-prior evidence, preserve the immutable Wealth Core shadow, preserve next-open execution, improve more than one episode, maintain or improve drawdown economics, and have a small auditable state surface. A result that requires episode-specific thresholds is rejected even if CAGR improves.

## Budget ledger

| Experiment | Candidate | Status |
|---|---|---|
| 1 | owned-book divergence mode | **REJECTED — completed** |
| 2 | r20-only recovery, divergence latch preserved | **REJECTED — completed** |
| 3 | cross-surface recovery concordance | **PLANNED** |
| 4-10 | uncommitted | held in reserve |

Current budget: **2 / 10 consumed; 8 remain.**
