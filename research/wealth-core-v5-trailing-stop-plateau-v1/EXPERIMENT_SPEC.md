# Wealth Core V5 trailing-stop plateau study

## Objective

Measure whether Wealth Core V5's frozen 30% peak-to-close trailing stop sits on a broad, stable performance plateau.

This is a predeclared 10-arm parameter sweep. The goal is **not** to select the single best historical point. A useful result is a contiguous region where CAGR, drawdown, Sharpe, and trading activity remain economically similar across neighboring stop values and across 5/10/15/20-year windows.

## Frozen authorities

Base research authority: `research/wealth-core-v5-sentinel-ex3-impedance-v1` at `b0c80cfb44bc419b9081420f0a7c98088623b3d6`.

The workflow independently pins the same exact economic source, Median-5 authority, formal source, classifier source, runtime source, and immutable canonical PIT package used for the Wealth Core V5 / Sentinel EX3 V5 impedance experiment.

Frozen Wealth Core economics except for the one parameter under test:

- 20 slots
- 5% target weight per slot
- Median-5 ranking
- 10 bp close-time admission cushion
- total-cash one-whole-share affordability at close
- next-valid-open whole-share sizing
- one-session dividend lag
- all other selection, review, cooldown, execution, transaction-cost, and PIT semantics unchanged

Frozen Sentinel comparison in every arm:

- Sentinel EX3 V5
- `LDRC_REC = 8`
- full-recovery recent-r40 floor = `-5%`
- native FAST damaged threshold = `88%`
- native healthy damaged ceiling = `63%`
- all remaining EX3 parameters unchanged

Each arm performs one fresh full-PIT replay. The same replay records both pure Wealth Core V5 (`shadow_equity`) and Wealth Core V5 + frozen Sentinel EX3 V5 (`A_nav`) results.

## Parameter under test

Current authority:

- `STOP_RET = 0.70`
- exit condition: `close <= peak * STOP_RET`
- equivalent trailing-stop drawdown: **30% below the post-entry peak**

Predeclared sweep:

| Arm | Trailing-stop % | Peak-retention factor |
|---|---:|---:|
| stop_15 | 15.0% | 0.850 |
| stop_20 | 20.0% | 0.800 |
| stop_22_5 | 22.5% | 0.775 |
| stop_25 | 25.0% | 0.750 |
| stop_27_5 | 27.5% | 0.725 |
| stop_30 | 30.0% | 0.700 |
| stop_32_5 | 32.5% | 0.675 |
| stop_35 | 35.0% | 0.650 |
| stop_40 | 40.0% | 0.600 |
| stop_45 | 45.0% | 0.550 |

The range deliberately spans 0.5x to 1.5x the current 30% stop while adding resolution near the current authority.

## Execution contract

All 10 arms are launched in a single matrix with `max-parallel: 10`, `fail-fast: false`.

No arm may alter anything except the single `STOP_RET` source seam. The runner constructs the frozen selected Wealth Core V5 + Sentinel EX3 V5 source first, then proves the candidate source is exactly that source plus the predeclared `STOP_RET` substitution. The 30% arm must be byte-identical to the frozen selected source and reproduce its known 20-year Wealth Core and Sentinel metrics.

Measurement window: 2006-07-31 through 2026-07-31, 5,032 sessions after warmup from 2006-01-03.

## Evidence recorded per arm

For both pure Wealth Core V5 and Wealth Core V5 + Sentinel EX3 V5:

- 5-year CAGR, max drawdown, Sharpe, ending multiple
- 10-year CAGR, max drawdown, Sharpe, ending multiple
- 15-year CAGR, max drawdown, Sharpe, ending multiple
- 20-year CAGR, max drawdown, Sharpe, ending multiple

Additional arm evidence:

- trailing-stop percentage and retention factor
- buys and sells from the Wealth Core replay
- Wealth Core core-tape hash
- transaction hash
- close-decision hash
- Sentinel allocation average, sessions by level, and transition count
- exact source hashes and canonical PIT dataset hash

## Interpretation rule

Do not choose the highest historical CAGR point. Look for a broad contiguous plateau with similar neighboring performance across multiple horizons. A narrow isolated optimum is considered fragile. If the apparent plateau touches 15% or 45%, the correct follow-up is to expand the range rather than declare a winner.
