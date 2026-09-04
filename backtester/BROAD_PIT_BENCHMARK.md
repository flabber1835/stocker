# Frozen broad-universe full-PIT LD-RC benchmark

Date: 2026-09-03

## Status

**PASS.** Dedicated GitHub Actions run `33832270731` completed green on exact head `5fe8c2c1bc1a07b932b62d3dbd2780755cf58133`.

No strategy parameter, LD-RC threshold, ranking rule, sizing rule, or universe calibration was changed for this benchmark. The embedded frozen strategy commit is `c14f77b3c6c6fcc14cf00e8916d7968c853a5d6c`.

The benchmark uses the broad historical Sharadar SEP opportunity set with the corrected full-stack PIT research metadata treatment:

- strict-prior SEC CIK issuer authority;
- strict-prior SEC SIC -> FF12 sector authority;
- PIT ACTIONS;
- causal historical Treasury cash before BIL;
- current TICKERS common-stock/category seam retained under prior zero-delta/equivalence evidence;
- exchange is not economically active.

This is a **broad full-stack PIT research estimate**, not the final formally certified golden corpus.

## Results

| Window | LD-RC CAGR | SPY CAGR | CAGR spread | LD-RC max DD | SPY max DD | LD-RC Sharpe | LD-RC ending multiple |
|---|---:|---:|---:|---:|---:|---:|---:|
| 5 years | **27.64%** | 12.76% | **+14.88 pp** | **-20.49%** | -24.50% | **1.336** | **3.39x** |
| 10 years | **24.82%** | 14.99% | **+9.83 pp** | **-28.87%** | -33.70% | **1.217** | **9.18x** |
| 15 years | **20.86%** | 14.40% | **+6.45 pp** | **-28.87%** | -33.70% | **1.141** | **17.14x** |
| 20 years | **20.49%** | 11.26% | **+9.23 pp** | **-28.87%** | -55.20% | **1.110** | **41.57x** |
| Max, 1998-01-02 to 2026-07-31 | **20.07%** | 9.25% | **+10.82 pp** | **-33.46%** | -55.20% | **1.079** | **185.95x** |

Measurement windows:

- 5 years: 2021-07-30 to 2026-07-31, 1,256 sessions
- 10 years: 2016-07-29 to 2026-07-31, 2,515 sessions
- 15 years: 2011-07-29 to 2026-07-31, 3,773 sessions
- 20 years: 2006-07-31 to 2026-07-31, 5,032 sessions
- Max: 1998-01-02 to 2026-07-31, 7,188 sessions
- machine warm-up begins 1997-01-02

## Reproducibility

The dedicated benchmark reproduced the earlier independent forensic broad full-PIT run (`33830860739`) within the locked acceptance tolerance for all five CAGR windows.

Artifact:

- Actions run: `33832270731`
- artifact ID: `9922250531`
- artifact name: `broad-pit-benchmark-5fe8c2c1bc1a07b932b62d3dbd2780755cf58133`
- artifact SHA-256: `e842bbf79615a022ea750019ab997445e5ab61e803a947647f8c4255d1919aae`

The artifact contains:

- `daily.csv.gz`
- `metrics.csv`
- `summary.json`
- `benchmark-manifest.json`
- `SHA256SUMS.txt`

Permanent machine-readable repository evidence is stored in `backtester/evidence/broad_pit_benchmark_2026-09-03.json`.

## Interpretation

The frozen broad-universe result is materially stronger than the unchanged S&P 500 transfer test. The 20-year broad result is 20.49% CAGR versus 12.12% for the S&P implementation, while the Max broad result is 20.07% versus 12.26% for S&P.

This strengthens the forensic conclusion that the large performance loss in the S&P experiment is predominantly a universe/domain effect. It does not establish that every difference is caused only by index membership; the S&P run also changes the leadership breadth input and contains a small number of best-effort historical identity exclusions.

No calibration should be inferred from this benchmark. It is the same frozen strategy on the broader opportunity set.
