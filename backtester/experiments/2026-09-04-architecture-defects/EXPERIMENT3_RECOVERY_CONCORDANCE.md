# Experiment 3 — cross-surface recovery concordance

Status: **RETAINED**.

Research only. `main` remains read-only.

Experiment budget before run: 2 / 10 consumed. This fresh candidate replay consumed experiment #3.

## Mechanical premise

The 2019 weakness was dominated by delayed re-entry after severe defense. A simple r20-only recovery rule failed in Experiment 2 because a rebound inside a damaged book can look strong locally while the broader opportunity set remains weak.

The repair therefore required recovery to be concordant across three independent surfaces already present in the strategy:

1. the owned stateful Wealth Core book;
2. the current recent-leadership opportunity set; and
3. SPY.

## Candidate rule

While an LD-RC recovery episode is active, add an early full-risk release when:

```text
recent_positive_streak >= existing LDRC_REC  # 7 sessions
AND wc_r20 > 0
AND recent_leadership_r20 >= wc_r20
AND spy_r20 >= wc_r20
```

The existing dual-positive r20/r40 recovery remains the fallback. The existing SPY V-rebound remains the fallback. Divergence-entry/latch mechanics are unchanged. The decision is made after the close and becomes effective at the next open.

## Parameter discipline

No fitted numeric threshold was added:

- `7` reuses the existing LD-RC recovery persistence;
- `0` is a sign boundary;
- `recent >= core` and `SPY >= core` are relative comparisons;
- no new exposure level, crisis date, percentile, or lookback was introduced.

## Fresh replay evidence

- GitHub Actions run: `33912976460`
- Exact head: `3f27834db427e71d9bb8d0b6160c8835b739c906`
- Workflow: `.github/workflows/backtester-strategy9-recovery-concordance-e3.yml`
- Artifact ID: `9953264982`
- Artifact ZIP digest: `sha256:22011d018a336c6da4d92b31e8786811a4f4288daa91d56a80c30c9f144f174f`
- Stable Strategy 9 control projection parity: PASS
- Replay span: 1998-01-02 through 2026-07-31, 7,188 measured sessions

## Results

| Window | Control CAGR | E3 CAGR | Control Max DD | E3 Max DD | Control Sharpe | E3 Sharpe | E3 multiple |
|---|---:|---:|---:|---:|---:|---:|---:|
| 5y | 27.2967% | 27.2967% | -20.4865% | -20.4865% | 1.318578 | 1.318578 | 3.342610x |
| 10y | 24.0168% | 24.4037% | -29.6266% | -28.6186% | 1.183121 | 1.198502 | 8.878358x |
| 15y | 20.3371% | 20.6461% | -29.6266% | -28.6186% | 1.116104 | 1.129585 | 16.699424x |
| 20y | 20.0964% | 20.3277% | -29.6266% | -28.6186% | 1.091505 | 1.101492 | 40.486504x |
| max | 19.7934% | 19.9548% | -33.4590% | -33.4590% | 1.066746 | 1.073666 | 181.122029x |

Control max-history ending multiple: `174.286531x`.

## Changed episodes

The fresh replay produced exactly the three pre-screened early releases:

| Decision date | Difference interval | Control allocation | E3 allocation | Core return | SPY return | E3 minus control |
|---|---|---:|---:|---:|---:|---:|
| 2012-01-18 | 2012-01-19..2012-01-26 | 0% | 100% | +0.5860% | +0.8492% | +0.3370% |
| 2016-02-25 | 2016-02-26..2016-03-11 | 65% | 100% | +1.4503% | +3.6920% | +0.3957% |
| 2019-02-04 | 2019-02-05..2019-02-22 | 0% | 100% | +3.1045% | +2.6400% | +2.8370% |

No early release occurred in the 2000-2001, 2008-2009, or 2022 false/weak recovery cases.

## Analysis

Experiment 3 passes the architectural falsification test that Experiment 2 failed. It recovers risk early only when the damaged owned book is not outperforming the current leadership opportunity set and the broad market. That geometry distinguishes the 2019 repair from the 2000 bear-market rebound.

The gain is not concentrated solely in CAGR. The 10/15/20-year drawdown improves by about one percentage point, Sharpe improves, and the max-history drawdown is unchanged. The 2019 interval supplies most of the economic gain, while the 2012 and 2016 episodes provide independent positive corroboration.

Experiment 3 does not solve the earlier 2018 Wealth Core deterioration. The 2018 loss occurs while Core remains fully exposed and is a separate retention/selection architecture question.

## Decision

**RETAIN.** E3 becomes the current surviving Sentinel architecture for subsequent experiments. Later Wealth Core experiments must preserve E3 unless the experiment explicitly declares Sentinel as the tested dimension.
