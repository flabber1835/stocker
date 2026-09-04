# Experiment 4 — Wealth Core symmetric deterioration exit

Status: **REJECTED after completed fresh replay**.

Research branch only. `main` remains read-only.

Economic experiment budget before this run: **3 / 10 consumed**. The candidate completed its fresh measured replay and therefore consumed experiment **#4**. Budget after completion: **4 / 10**.

## Structural evidence that motivated the test

The zero-budget observational run `33917445284` found that in 2018, held securities that had already fallen outside the existing top-10% momentum pool while also having a negative existing recent-21 return accounted for **76.19% of gross negative holding P&L**. The 12 episodes first detected in 2018 remained held for a median **65.5 sessions** and a maximum **115 sessions** after the condition was observable.

This established a real admission/retention asymmetry: Wealth Core requires non-negative recent-21 performance for new admissions, while a previously admitted holding can remain outside the admission-quality set for months until the intentional one-time age-119 review, 30% trailing stop, or terminal event acts.

## Candidate rule

Keep all Strategy 9 Wealth Core mechanics and E3 Sentinel mechanics frozen except for one additional Wealth Core exit condition evaluated at the close:

```text
if existing trailing stop fires:
    exit as today
elif holding is outside the existing top-10% momentum pool
     AND existing recent-21 return < 0:
    schedule deterioration exit for next open
else:
    preserve the existing age-119 review logic
```

The existing 21-session cooldown, one-admission-per-session steady-state limit, 4% sizing, stop priority, and E3 Sentinel overlay were preserved.

## Parameter discipline

No new fitted numeric threshold was introduced:

- Top 10% is the existing admission pool.
- Recent 21 sessions is the existing admission-quality horizon.
- Zero is the existing sign boundary.
- Existing 30% trailing stop remained first priority.
- Existing age-119 review remained in place.
- Existing 21-session cooldown remained unchanged.

## Fresh replay evidence

The workflow performed two independent fresh chronological full-history replays against the same pinned inputs and frozen runtime:

1. `CONTROL_E3` — exact retained Experiment 3.
2. `E4_SYMMETRIC_EXIT_E3` — E3 plus only the declared Wealth Core exit rule.

Evidence:

- GitHub Actions run: `33920953006`
- Exact head: `43e6bbe2d7a73cc37f1eee4cda3312a2bc9c9588`
- Artifact ID: `9956419168`
- Artifact ZIP digest: `sha256:1c78a71a41ebe932e3bad1ab18db9b261a6c40b1a4521341ed5262d26fbdcea5`
- Fresh E3 control parity: PASS
- New fitted numeric thresholds: 0
- Deterioration signals: `1849`
- Executed deterioration exits: `1849`

## Results — E3-controlled strategy

| Window | E3 control CAGR | E4 CAGR | E3 control Max DD | E4 Max DD | E3 control Sharpe | E4 Sharpe | E4 multiple |
|---|---:|---:|---:|---:|---:|---:|---:|
| 5y | 27.2967% | 16.7197% | -20.4865% | -30.7409% | 1.318578 | 0.775501 | 2.166307x |
| 10y | 24.4037% | 17.0936% | -28.6186% | -30.7409% | 1.198502 | 0.826339 | 4.845402x |
| 15y | 20.6461% | 12.9354% | -28.6186% | -30.7409% | 1.129585 | 0.702805 | 6.200878x |
| 20y | 20.3277% | 12.3836% | -28.6186% | -33.0801% | 1.101492 | 0.682533 | 10.329036x |
| max | 19.9548% | 12.7469% | -33.4590% | -42.2478% | 1.073666 | 0.705060 | 30.825743x |

## Results — Wealth Core surface

| Window | E3-control Core CAGR | E4 Core CAGR | Control Core DD | E4 Core DD | Control Core Sharpe | E4 Core Sharpe |
|---|---:|---:|---:|---:|---:|---:|
| 20y | 17.1839% | 11.1910% | -45.1420% | -45.0612% | 0.866277 | 0.581767 |
| max | 17.1971% | 12.0524% | -45.1420% | -55.8012% | 0.853550 | 0.610323 |

Turnover increased from **747 buys / 727 sells** to **2400 buys / 2391 sells**.

Across the 29 calendar years whose candidate path differed, E4 beat E3 in **7** and lost in **22**.

## 2018-2019 attribution

The candidate did exactly what the structural hypothesis predicted in 2018:

| Period | E3 control | E4 | E4 minus control | Control Core | E4 Core |
|---|---:|---:|---:|---:|---:|
| calendar 2018 | -20.0204% | +15.9299% | +35.9504% | -19.1185% | +1.8785% |
| 2018-06-12..2018-09-20 | -10.5022% | +7.6960% | +18.1982% | -10.5022% | +7.6960% |
| 2018-09-20..2018-12-19 | -19.6631% | -4.9862% | +14.6768% | -19.6631% | -17.1907% |
| 2018-12-20..2019-02-04 | +0.2720% | +2.2924% | +2.0204% | +7.0399% | +8.4062% |
| 2019-02-05..2019-02-22 | +2.7446% | +3.0875% | +0.3429% | +2.7446% | +3.0875% |

## Analysis

Experiment 4 cleanly separates **diagnosis** from **repair**.

The diagnosis survives: a large fraction of 2018 loss occurred after holdings had already deteriorated relative to Wealth Core's existing admission-quality information. E4's 2018 improvement confirms that acting on this information can avoid much of that specific damage.

The repair fails: evaluating the same admission-quality condition every day and immediately exiting converts a deliberately stateful, long-duration holding architecture into a high-churn short-horizon momentum strategy. Ordinary pullbacks and relative-rank slips become exits. The 21-session cooldown and one-admission-per-session replacement machinery then amplify the churn by creating repeated vacancies and delayed rebuilding. Long-duration winners lose the ability to compound.

This failure must **not** be followed by tuning E4's rank cutoff, negative-return threshold, persistence duration, or crisis-specific exceptions until the backtest improves. That would turn a structural investigation into return fitting.

A later repository inspection also established that the age-119 review is intentionally one-time. Repeating it would be a strategy redesign, not correction of an implementation bug.

## Decision

**REJECT E4 unchanged.**

The 2018 retention asymmetry remains an established architecture weakness. The immediate symmetric exit is not the correct minimal repair. Before spending Experiment #5, investigate actual mechanical state-machine defects or bottlenecks — cooldown convention, replacement capacity, exit-fill delay, and review-state handling — using zero-budget observational diagnostics.
