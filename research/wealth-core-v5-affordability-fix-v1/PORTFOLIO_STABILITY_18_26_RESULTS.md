# Wealth Core V5 portfolio-size stability — 18–26 holdings

Status: **completed / PASS**

## Authorities

- V5 authority base: `288f31a03b74c3ae186550ae22b78926930765de`
- V5 contract commit: `4b3eb0a364cef57906b104a02c4e37b28dcd9176`
- Stability branch: `research/wealth-core-v5-portfolio-stability-18-26-v1`
- Completed stability run: `34313794954`
- Successful run head: `6cdd5137b3d1d0ec732d82f10f13ae59129808f9`
- Actions URL: https://github.com/flabber1835/stocker/actions/runs/34313794954
- Measurement window: `2006-07-31` through `2026-07-31`
- Measurement sessions: `5,032`

All nine matrix arms completed successfully.

## Frozen experiment design

The only sweep dimension was portfolio size, with the mechanically linked equal-weight entry target `1/N`.

| Holdings | Entry target |
|---:|---:|
| 18 | 5.555556% |
| 19 | 5.263158% |
| 20 | 5.000000% |
| 21 | 4.761905% |
| 22 | 4.545455% |
| 23 | 4.347826% |
| 24 | 4.166667% |
| 25 | 4.000000% |
| 26 | 3.846154% |

Everything else remained frozen: Median-5 ranking hardening, 10 bp close-time admission cushion, V5 total-cash one-share affordability test, next-valid-open whole-share sizing, fractional shares disabled, one-session dividend lag, invalid-open guard, zero-quantity-at-open guard, and Sentinel EX3 / Candidate-A in parallel.

## 20-year stability surface

| N | Wealth Core CAGR | Max DD | Sharpe | Ending multiple | Wealth Core + EX3 CAGR | Max DD | Sharpe | Ending multiple |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 18 | 15.59% | -50.12% | 0.788 | 18.13x | 17.40% | -25.08% | 0.940 | 24.75x |
| 19 | 15.60% | -51.74% | 0.794 | 18.17x | 18.03% | -26.19% | 0.993 | 27.51x |
| **20** | **17.07%** | **-50.34%** | **0.840** | **23.40x** | **20.73%** | **-28.45%** | **1.095** | **43.25x** |
| 21 | 15.38% | -50.24% | 0.781 | 17.49x | 19.34% | -25.43% | 1.037 | 34.35x |
| 22 | 17.67% | -50.09% | 0.881 | 25.90x | 21.69% | -23.99% | 1.154 | 50.69x |
| 23 | 15.47% | -50.01% | 0.794 | 17.76x | 19.59% | -25.50% | 1.071 | 35.81x |
| 24 | 14.04% | -49.89% | 0.743 | 13.84x | 16.76% | -23.88% | 0.945 | 22.19x |
| 25 | 15.24% | -50.52% | 0.781 | 17.05x | 19.13% | -28.85% | 1.031 | 33.17x |
| 26 | 15.22% | -51.17% | 0.788 | 17.01x | 18.04% | -24.26% | 1.028 | 27.59x |

## 20-slot V5 control by horizon

| Horizon | Core CAGR | Core Max DD | Core Sharpe | Core multiple | +EX3 CAGR | +EX3 Max DD | +EX3 Sharpe | +EX3 multiple |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 5y | 29.00% | -26.47% | 1.202 | 3.57x | 30.77% | -18.65% | 1.353 | 3.82x |
| 10y | 23.49% | -30.46% | 1.029 | 8.24x | 26.29% | -28.45% | 1.247 | 10.31x |
| 15y | 19.14% | -30.46% | 0.940 | 13.82x | 21.69% | -28.45% | 1.165 | 18.99x |
| 20y | 17.07% | -50.34% | 0.840 | 23.40x | 20.73% | -28.45% | 1.095 | 43.25x |

At 20 holdings, EX3 contributed approximately `+3.65` percentage points of 20-year CAGR, improved maximum drawdown by approximately `21.89` percentage points, and increased daily Sharpe by approximately `0.255`.

## V5 affordability and execution validation

The required V5 witnesses passed before performance was accepted.

### AGN1 false-rejection witness

Historical decision date: `2014-05-23`.

The 20-slot V5 path had approximately:

- total cash: `$232.45`
- reserve: `$214.46`
- cash above reserve: `$17.99`
- AGN1 close: `$166.92`
- one-share close cost including modeled cost: approximately `$167.09`

V5 correctly allowed the candidate to proceed to `PLAN_OPEN_SIZE` because total cash could afford one share. This confirms that the 10 bp reserve is an admission cushion and is not incorrectly reused as the one-share funding basis.

### AMZN true-unaffordability witness

The 20-slot V5 path retained the true affordability protection. On `2015-12-04`, AMZN at approximately `$672.64` was unaffordable from total cash and was rejected as a total-cash one-share-unaffordable candidate.

### Gap-risk witness

The close does not bind quantity. The next-open zero-quantity guard remains active for a close-affordable candidate that gaps beyond available execution cash. No historical arm encountered a zero-quantity-at-open or invalid-open block during this completed sweep.

### Whole-share execution

Fractional-share violations were zero in all nine arms.

## Execution counts

| N | Buys | Sells | Close cash-scarcity skips | Total-cash one-share-unaffordable skips | Zero-at-open blocks | Invalid-open blocks | Cash-limited executions | Fractional violations |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 18 | 369 | 310 | 33,807 | 1 | 0 | 0 | 85 | 0 |
| 19 | 388 | 325 | 47,756 | 0 | 0 | 0 | 83 | 0 |
| 20 | 416 | 350 | 40,269 | 1 | 0 | 0 | 78 | 0 |
| 21 | 444 | 377 | 56,243 | 0 | 0 | 0 | 100 | 0 |
| 22 | 437 | 368 | 43,962 | 0 | 0 | 0 | 92 | 0 |
| 23 | 472 | 399 | 80,979 | 0 | 0 | 0 | 122 | 0 |
| 24 | 490 | 416 | 58,402 | 0 | 0 | 0 | 98 | 0 |
| 25 | 529 | 452 | 75,102 | 0 | 0 | 0 | 114 | 0 |
| 26 | 536 | 456 | 68,335 | 0 | 0 | 0 | 102 | 0 |

Some arms have one more close admission than completed entry because a reservation can remain pending at the terminal boundary. This is end-of-window accounting and does not indicate fractional execution or a zero-quantity block.

## V4 → V5 shape change

The affordability correction materially changed the portfolio-size sensitivity surface.

| N | V4 Core CAGR | V5 Core CAGR | Δ Core | V4 +EX3 CAGR | V5 +EX3 CAGR | Δ +EX3 |
|---:|---:|---:|---:|---:|---:|---:|
| 18 | 15.49% | 15.59% | +0.10 pp | 17.47% | 17.40% | -0.07 pp |
| 19 | 16.40% | 15.60% | -0.80 pp | 19.55% | 18.03% | -1.52 pp |
| 20 | 13.90% | 17.07% | +3.17 pp | 17.79% | 20.73% | +2.94 pp |
| 21 | 15.69% | 15.38% | -0.31 pp | 19.73% | 19.34% | -0.38 pp |
| 22 | 15.17% | 17.67% | +2.50 pp | 19.52% | 21.69% | +2.17 pp |
| 23 | 15.64% | 15.47% | -0.17 pp | 19.71% | 19.59% | -0.12 pp |
| 24 | 16.18% | 14.04% | -2.14 pp | 20.82% | 16.76% | -4.06 pp |
| 25 | 15.30% | 15.24% | -0.06 pp | 19.10% | 19.13% | +0.04 pp |
| 26 | 15.34% | 15.22% | -0.12 pp | 19.04% | 18.04% | -1.00 pp |

The V5 correction therefore changes path-dependent outcomes materially. The local maximum at 22 holdings must not be interpreted as an optimized production target.

## Stability conclusion

1. V5 is broadly robust to portfolio size over the tested 18–26 range, though CAGR and Sharpe are not perfectly smooth.
2. The central robustness basin is approximately **19–23 holdings**.
3. **20 holdings is inside the stable basin** and is not a knife-edge result.
4. Core drawdown is very smooth around 20; CAGR and Sharpe show local oscillation.
5. The V5 affordability correction materially changes the shape observed under V4.
6. 22 holdings is the best-performing historical point in this sweep, but the `21 → 22 → 23` pattern is a local peak, not evidence of a broad optimum.

## Frozen portfolio-size decision

**Retain 20 holdings.**

The 20-slot configuration remains the frozen default because:

- it was the pre-specified V5 baseline control;
- it lies within the 19–23 robustness basin;
- its 20-year performance is strong under both pure Wealth Core and Wealth Core + EX3;
- moving to 22 after observing the sweep would amount to post-hoc selection of a local backtest maximum;
- the sweep provides no robustness-based reason to replace 20 with 22.

No strategy tuning or production economic change is authorized by this result. Any future portfolio-size change requires a separately pre-specified research decision and validation path.
