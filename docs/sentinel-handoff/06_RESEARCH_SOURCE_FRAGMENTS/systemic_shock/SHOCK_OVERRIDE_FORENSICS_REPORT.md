# Wealth Core shock override: forensic and root-cause iteration

## Executive conclusion

The original shock override increased CAGR because it was exposed to Wealth Core during normal compounding, but temporarily reduced exposure during a small number of sessions whose conditional return was strongly negative.

It was not T-bill yield creating the improvement. Almost all of the benefit came from avoiding unusually large Wealth Core losses and then returning to the unchanged shadow book after internal breadth recovered.

The original override also contained three materially harmful emergency episodes. Adding an external market-panic confirmation removed those false positives while preserving all major protective episodes.

## Improved candidate

### Internal Wealth Core shock condition

All must be true:

- shadow-book drawdown at least 10%;
- at least 85% of holdings damaged;
- no more than 20% of holdings green;
- shadow return at most -5% over five sessions or -8% over ten sessions;
- damaged breadth increased at least 40 percentage points over five sessions.

### External systemic confirmation

Both must be true:

- SPY five-session realized volatility is at least 5% above its 20-session realized volatility; and
- either SPY's 20-session return is at most -1%, or Wealth Core's ten-session shadow return is at most -10%.

### Action and recovery

- reduce live Wealth Core exposure to 40%;
- place 60% in the SHY/BIL defensive sleeve;
- keep the immutable Wealth Core shadow running at full exposure;
- stay defensive for at least 10 sessions;
- require three healthy sessions, positive shadow 20-session return, damaged breadth no more than 60%, and green breadth at least 20%;
- retain the normal 15.5% portfolio backstop independently.

Thresholds are stated at the middle of a stable plateau. Volatility acceleration between 2% and 6%, SPY 20-session thresholds from -1% to -1.5%, and Wealth Core fallback thresholds from -9% to -10% produced the same path in the tested neighborhood.

## Full-history comparison

| Strategy | CAGR | Maximum drawdown | Ending wealth |
|---|---:|---:|---:|
| Wealth Core | 19.97% | -41.16% | 166.0x |
| Current 15.5% backstop | 19.78% | -34.42% | 158.5x |
| Original shock override | 20.56% | -31.61% | 190.1x |
| **Systemic-confirmed shock override** | **21.14%** | **-31.61%** | **217.8x** |

The iteration improved the original override by 0.58 percentage points of CAGR and 14.5% of terminal wealth without worsening maximum drawdown.

## Root-cause mechanics

### 1. Loss avoidance, not defensive yield

Across the selected candidate's 117 incremental defensive sessions:

- reduced equity exposure contributed approximately +28.76 percentage points on a simple summed basis;
- the defensive sleeve contributed approximately +0.38 percentage points;
- total gross incremental contribution was approximately +29.14 percentage points before switching costs.

The T-bill sleeve was useful operationally, but it was not the source of alpha.

### 2. Negative-return magnitude exceeded missed-rebound magnitude

During incremental defensive days:

- 60 sessions had negative Wealth Core returns;
- 57 sessions had positive Wealth Core returns;
- avoided losses on negative days contributed approximately +73.11 percentage points;
- missed gains on positive days cost approximately -43.97 percentage points.

The controller did not predict more down days than up days. It identified periods when down days were materially larger than up days.

### 3. Geometric compounding magnified the benefit

Avoiding a large loss preserves capital for the next compounding cycle. A 10% loss requires an 11.1% gain merely to recover. Therefore, reducing a few severe losses can raise long-term CAGR even though the strategy is temporarily less invested.

### 4. The original false positives were late or non-systemic

The original override had eleven emergency episodes. Three materially harmful episodes were:

| Entry | Incremental result versus current backstop | Root cause |
|---|---:|---|
| March 10, 2008 | -6.90% | volatility had already stopped accelerating; protection entered into a strong bear-market rally |
| May 20, 2010 | -2.63% | late, oversold entry with decelerating market volatility |
| August 11, 2020 | -3.34% | primarily an internal Wealth Core rotation while the broad market trend remained healthy |

Their combined log-relative cost was approximately 13.2%. Removing them explains nearly all of the 14.5% terminal-wealth improvement over the original override.

### 5. Profitable episodes were genuine panic impulses

The improved controller retained eight episodes:

| Entry | Exit | Incremental result versus current backstop |
|---|---|---:|
| August 4, 1998 | November 2, 1998 | +3.56% |
| March 15, 2000 | May 15, 2000 | +4.28% |
| July 27, 2007 | September 17, 2007 | +4.99% |
| July 2, 2008 | December 18, 2008 | +2.86% |
| August 5, 2011 | September 6, 2011 | +4.10% |
| August 24, 2015 | October 28, 2015 | -0.26% |
| October 10, 2018 | January 22, 2019 | +4.35% |
| February 27, 2020 | April 21, 2020 | +9.11% |

Seven of eight episodes were positive. The 2015 event was nearly neutral. Further tuning specifically to remove it would add more overfitting than expected value.

## Trailing-period results through July 31, 2026

| Period | Systemic-confirmed CAGR | Maximum drawdown | Original shock CAGR | Original max DD | SPY CAGR | SPY max DD |
|---|---:|---:|---:|---:|---:|---:|
| 5 years | 24.71% | -24.48% | 24.71% | -24.48% | 12.83% | -24.50% |
| 10 years | 22.31% | -30.97% | 21.88% | -30.97% | 15.01% | -33.70% |
| 15 years | 19.00% | -30.97% | 18.72% | -30.97% | 14.44% | -33.70% |
| 20 years | 19.12% | -31.14% | 18.31% | -31.14% | 11.26% | -55.20% |

## Official U.S. recession windows

| Recession | Strategy | Annualized CAGR | Total return | Maximum drawdown |
|---|---|---:|---:|---:|
| 2001 | Systemic-confirmed override | -4.85% | -3.66% | -9.73% |
| 2001 | Current backstop | -4.85% | -3.66% | -9.73% |
| 2001 | SPY | -10.01% | -7.61% | -25.62% |
| Great Recession | Systemic-confirmed override | -6.88% | -10.62% | -31.14% |
| Great Recession | Current backstop | -8.54% | -13.11% | -33.06% |
| Great Recession | Original shock override | -11.09% | -16.89% | -31.14% |
| Great Recession | SPY | -24.00% | -35.09% | -53.91% |
| COVID | Systemic-confirmed override | -46.38% | -13.80% | -17.72% |
| COVID | Current backstop | -62.82% | -21.00% | -24.59% |
| COVID | SPY | -35.23% | -9.83% | -33.70% |

The systemic confirmation fixed the original override's largest recession weakness: missing the March-April 2008 bear-market rally.

## Parameter and start-date robustness

Thirty-six neighboring parameter combinations produced the exact same CAGR and drawdown path. The same selected path appeared across:

- volatility-acceleration thresholds of 2%, 4%, and 6%;
- SPY 20-session thresholds of -1% and -1.5%;
- fallback Wealth Core ten-session thresholds of -9% and -10%;
- minimum defensive holding periods of 5, 10, and 15 sessions.

Rolling-start tests also retained the improvement over the current controller from 1998, 2000, 2005, 2010, 2012, 2015, 2016, and 2020 starts. It did not improve the 2021 start because no emergency override occurred after that start date.

## Recommendation

This is now the leading research challenger:

> Wealth Core + fixed 30% position stop + immutable shadow book + systemic-confirmed fast-shock override + normal 15.5% portfolio backstop + 40% Wealth Core / 60% T-bills + shadow-controlled recovery.

Do not tune the historical rule further. The next gains in confidence should come from validation rather than another parameter search:

1. exact next-open execution through the trusted ledger;
2. leave-one-crisis-out and rolling-origin validation;
3. frozen parameters in an untouched forward shadow;
4. live/windtunnel/backtester parity for breadth and volatility calculations;
5. realistic spread, tax and transition-cost testing.

## Status

This remains a close-to-close research overlay. The result is promising and mechanically explainable, but not certified and not deployable yet.
