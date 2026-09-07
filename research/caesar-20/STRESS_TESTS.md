# Caesar 20 local robustness stress tests

These calculations use the completed emitted `daily.csv` paths from GitHub Actions artifacts. They are post-processing only: no strategy replay, parameter search, market-data fetch, classifier change or additional backtester run is performed.

## Method

### Rolling windows

For each trading-day start, use fixed 252-session years. A `Y`-year window spans `252 * Y` return intervals and `252 * Y + 1` NAV observations. CAGR is `(ending_nav / starting_nav)^(1/Y) - 1`. Strategy and SPY use the identical endpoints.

### Leave one calendar year out

Compute daily strategy and SPY returns from the emitted NAV paths. For each complete calendar year 2007-2025, remove all return observations dated in that year, compound the remaining returns and annualize using `252 / remaining_return_count`. This is a path-contribution diagnostic, not a counterfactual strategy replay.

### Six-month paired block bootstrap

Take month-end strategy and SPY NAVs, form the 240 paired monthly returns, sample contiguous six-month paired blocks with replacement until 240 months are filled, and repeat 5,000 times. Random seed: `20260906`. Strategy and SPY blocks remain paired. Max drawdown is computed on each simulated monthly strategy NAV path.

## Caesar 20

Source artifact: workflow `34079759743`, artifact `10003871840`, arm `SIZE_20`.

Full-history result: **19.9355% CAGR, 37.9307x ending wealth, -23.8169% max drawdown, 1.08176 Sharpe**.

### Rolling windows

| Horizon | Windows | Positive CAGR | Beat SPY | Median CAGR | Worst CAGR | Worst-period dates | Worst-period SPY CAGR |
|---:|---:|---:|---:|---:|---:|---|---:|
| 3y | 4,276 | 100% | 78.09% | 16.88% | 3.85% | 2021-02-12 to 2024-02-15 | 10.16% |
| 5y | 3,772 | 100% | 80.59% | 17.34% | 7.83% | 2014-03-05 to 2019-03-07 | 10.10% |
| 7y | 3,268 | 100% | 84.49% | 16.96% | 11.30% | 2011-07-26 to 2018-07-30 | 13.46% |
| 10y | 2,512 | 100% | 97.41% | 16.63% | 11.82% | 2010-04-28 to 2020-05-01 | 11.23% |

Worst relative five-year window: strategy **10.99%**, SPY **16.82%**, spread **-5.83 pp/year**.

### Leave one calendar year out

Every 2007-2025 year deletion leaves Caesar 20 ahead of SPY.

- Lowest remaining strategy CAGR: exclude **2020** -> **17.78%**, SPY **10.92%**, excess **+6.87 pp/year**.
- Narrowest remaining excess: exclude **2008** -> strategy **21.20%**, SPY **14.65%**, excess **+6.55 pp/year**.

### Six-month paired block bootstrap

5,000 synthetic 20-year paths:

- Median CAGR: **19.91%**
- 5th percentile CAGR: **13.01%**
- 1st percentile CAGR: **10.27%**
- Fraction beating paired SPY: **99.12%**
- 5th percentile max drawdown: **-27.08%**
- 1st percentile max drawdown: **-31.76%**

## Certified 25-stock reference

Source artifact: workflow `34071569702`, artifact `10001317230`.

Full-history result: **18.8009% CAGR, 31.3635x ending wealth, -24.9137% max drawdown, 1.03634 Sharpe**.

### Rolling windows

| Horizon | Positive CAGR | Beat SPY | Median CAGR | Worst CAGR |
|---:|---:|---:|---:|---:|
| 3y | 100% | 64.66% | 16.85% | 4.45% |
| 5y | 100% | 71.77% | 17.71% | 4.58% |
| 7y | 100% | 79.99% | 16.30% | 7.73% |
| 10y | 100% | 88.69% | 15.36% | 11.14% |

Leave-one-year-out:

- Lowest remaining strategy CAGR: exclude **2020** -> **17.03%**, SPY **10.92%**, excess **+6.11 pp/year**.
- Narrowest remaining excess: exclude **2008** -> strategy **19.62%**, SPY **14.65%**, excess **+4.97 pp/year**.

Paired six-month bootstrap:

- Median CAGR: **18.79%**
- 5th percentile CAGR: **11.91%**
- 1st percentile CAGR: **9.28%**
- Fraction beating paired SPY: **97.70%**
- 5th percentile max drawdown: **-35.59%**
- 1st percentile max drawdown: **-43.46%**

## 18-stock concentration check

Source artifact: workflow `34079759743`, artifact `10003780329`, arm `SIZE_18`.

Full-history result: **17.2107% CAGR, 23.9539x ending wealth, -29.0754% max drawdown, 0.94468 Sharpe**.

### Rolling windows

| Horizon | Positive CAGR | Beat SPY | Median CAGR | Worst CAGR |
|---:|---:|---:|---:|---:|
| 3y | 100% | 61.83% | 15.25% | 3.14% |
| 5y | 100% | 64.05% | 15.68% | 3.10% |
| 7y | 100% | 71.02% | 15.02% | 8.18% |
| 10y | 100% | 79.98% | 14.44% | 9.45% |

Leave-one-year-out:

- Lowest remaining strategy CAGR: exclude **2020** -> **14.94%**, SPY **10.92%**, excess **+4.02 pp/year**.
- Narrowest remaining excess: exclude **2008** -> strategy **18.02%**, SPY **14.65%**, excess **+3.36 pp/year**.

Paired six-month bootstrap:

- Median CAGR: **17.10%**
- 5th percentile CAGR: **10.15%**
- 1st percentile CAGR: **7.32%**
- Fraction beating paired SPY: **92.52%**
- 5th percentile max drawdown: **-35.69%**
- 1st percentile max drawdown: **-42.76%**

## Portfolio-size robustness context

Using the same fixed-window method:

| Holdings | 5y windows beating SPY | 10y windows beating SPY | Worst 10y CAGR |
|---:|---:|---:|---:|
| 16 | 49.26% | 37.18% | 8.59% |
| 18 | 64.05% | 79.98% | 9.45% |
| **20** | **80.59%** | **97.41%** | **11.82%** |
| 22 | 77.62% | 93.31% | 11.15% |
| 24 | **85.68%** | 96.82% | 11.55% |
| 25 certified | 71.77% | 88.69% | 11.14% |

This supports two simultaneous conclusions:

1. Caesar 20 has the strongest historical headline and long-window risk-adjusted result in the tested set.
2. The portfolio-size response is not smooth: 18 and 22 are materially weaker, while 24 is especially strong on rolling-window consistency and drawdown. Caesar 20 therefore remains a frozen research challenger pending prospective evidence.
