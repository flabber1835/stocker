# S&P 500 LD-RC continuous result — 1997–2026

## Status

PASS. One uninterrupted best-effort PIT S&P 500 replay ran from `1997-12-31` through `2026-07-31` using the frozen retained LD-RC strategy.

The replay preserves portfolio and controller state continuously across the 2005/2006 boundary. It is not a stitched combination of separate backtests.

Formal PIT certification is **not** claimed because the early S&P membership source remains explicitly best-effort.

## Seam proof

The continuous replay exactly reproduced the previously sealed pre-2006 OOS endpoint:

- 2005 endpoint: `2005-12-30`
- Pre-2006 sessions: 2,013
- LD-RC NAV: `2.8822811536528485`
- SPY NAV: `1.4394278879361175`
- Next session: `2006-01-03`
- State reset: **false**
- Exact match to sealed OOS: **true**

This proves that all reported 5/10/15/20/Max windows belong to the same continuous state path.

## Requested windows

| Window | LD-RC CAGR | SPY CAGR | Spread | LD-RC Max DD | SPY Max DD | LD-RC Sharpe | SPY Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|
| 5 years | 13.69% | 12.76% | +0.94 pp | -20.82% | -24.50% | 0.824 | 0.788 |
| 10 years | 12.48% | 14.98% | -2.51 pp | -20.82% | -33.70% | 0.846 | 0.870 |
| 15 years | 12.73% | 14.40% | -1.67 pp | -20.82% | -33.70% | 0.899 | 0.871 |
| 20 years | 12.12% | 11.26% | +0.87 pp | -21.98% | -55.20% | 0.866 | 0.647 |
| Max — 28.07 years | 12.26% | 8.73% | +3.54 pp | -33.62% | -55.20% | 0.831 | 0.529 |

Ending multiples:

- 5y: LD-RC 1.900x; SPY 1.823x
- 10y: LD-RC 3.242x; SPY 4.042x
- 15y: LD-RC 6.040x; SPY 7.527x
- 20y: LD-RC 9.864x; SPY 8.443x
- Max: LD-RC 25.711x; SPY 10.467x

## Interpretation

The long-history result remains favorable to LD-RC, but the advantage is concentrated differently across horizons.

Over the maximum available active history, LD-RC compounds at 12.26% versus 8.73% for SPY and experiences materially lower maximum drawdown. Over the 20-year development-period window, LD-RC also leads SPY, 12.12% versus 11.26%, with a much smaller drawdown and higher Sharpe.

The 10-year and 15-year windows underperform SPY on CAGR. The 5-year window is modestly ahead. This means the S&P-only universe does not preserve the approximately 20% CAGR expectation from earlier broader-universe work. Its main demonstrated advantage is a combination of long-run excess return and substantially lower drawdown/risk, with inconsistent excess return over intermediate recent horizons.

This result is still useful for the production-universe decision: S&P eligibility is viable enough to evaluate operationally, but adopting it should be based on the desired return/risk tradeoff rather than an expectation that it will reproduce the broader-universe CAGR.

## Universe quality

The continuous materialized universe contains 7,189 market sessions.

Daily eligible constituent count:

- Minimum: 460
- Median: 476
- Maximum: 504
- Final session: 503

Source constituent-sessions: 3,587,397.

Admitted constituent-sessions: 3,458,733.

Explicit exclusions: 128,664, or 3.5866% of source membership sessions.

Exclusion reasons:

- 108,431 — no approved causal identity mapping
- 13,453 — ambiguous SEC-CIK identity
- 6,170 — duplicate resolved ticker on session
- 610 — Stage-3 ambiguous identity

No ambiguous identity was silently promoted.

## Reproducibility

Successful GitHub Actions run: `33828489539`

Exact run head: `f10f7ea9406ed2296210b93446b272deba2f96c3`

Artifact:

- ID: `9921123829`
- Name: `sp500-continuous-1997-2026-f10f7ea9406ed2296210b93446b272deba2f96c3`
- Size: 42,610,359 bytes
- ZIP SHA-256: `69066a3ac496f797749514ccad3556600692008106a9accfc7ea364f8e018a4d`

All workflow stages passed, including source/hash verification, causal identity rebuild, Stage-3 artifact verification, full-universe materialization, uninterrupted replay, exact pre-2006 seam verification, 5/10/15/20/Max metric validation, result checksums, and artifact upload.

Machine-readable evidence:

- `backtester/evidence/sp500_ldrc_continuous_1997_2026.json`
- `backtester/evidence/sp500_ldrc_continuous_1997_2026_metrics.csv`
- `backtester/evidence/sp500_ldrc_oos_1998_2005.json`

## Data-reconstruction decision

No additional S&P corpus reconstruction is required to use this result for strategy viability or to continue evaluating S&P eligibility as a production-universe option.

Further identity cleanup can improve the best-effort corpus and is appropriate before claiming formal PIT certification. It is no longer a prerequisite for seeing or evaluating the backtest economics.
