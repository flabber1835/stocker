# Ramp removal follow-up results

Status: **COMPLETE**; 7/7 Core cases complete; 7/7 slots claimed.

Measurement: 2006-07-31 to 2026-07-31, 5,032 sessions. Ending wealth is a multiple of starting wealth.

| Strategy experiment | CAGR | Max drawdown | Sharpe | Ending wealth | Preservation vs original / simplified |
|---|---:|---:|---:|---:|---|
| compact_original_no_ramp | 22.16% | -25.87% | 1.145 | 54.7783x | FAIL / FAIL |
| compact_simplified_no_ramp | 22.32% | -26.53% | 1.154 | 56.2653x | FAIL / FAIL |
| original | 21.56% | -27.38% | 1.121 | 49.6193x | PASS / FAIL |
| original_no_ramp | 22.16% | -25.87% | 1.145 | 54.7783x | FAIL / FAIL |
| simplified | 21.83% | -27.36% | 1.135 | 51.9214x | FAIL / PASS |
| simplified_no_ramp | 22.32% | -26.53% | 1.154 | 56.2653x | FAIL / FAIL |

## Each perturbation and strategy

Allocation area is the sum of absolute allocation differences from that strategy’s own baseline. Economic deltas also use its own baseline.

| Fault | Strategy | CAGR | Max DD | Sharpe | Wealth | Area | Different sessions | CAGR delta pp |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| drop_47 | original | 15.42% | -34.13% | 0.879 | 17.6061x | 339.25 | 494 | -6.137 |
| drop_47 | simplified | 16.01% | -34.55% | 0.906 | 19.4965x | 319.05 | 446 | -5.823 |
| drop_47 | original_no_ramp | 16.59% | -34.13% | 0.932 | 21.5417x | 235.00 | 271 | -5.570 |
| drop_47 | simplified_no_ramp | 16.68% | -34.55% | 0.939 | 21.8847x | 238.20 | 276 | -5.641 |
| drop_47 | compact_original_no_ramp | 16.59% | -34.13% | 0.932 | 21.5417x | 235.00 | 271 | -5.570 |
| drop_47 | compact_simplified_no_ramp | 16.68% | -34.55% | 0.939 | 21.8847x | 238.20 | 276 | -5.641 |
| drop_83 | original | 19.91% | -24.69% | 1.092 | 37.7795x | 167.50 | 297 | -1.646 |
| drop_83 | simplified | 20.08% | -26.88% | 1.094 | 38.8554x | 124.75 | 177 | -1.753 |
| drop_83 | original_no_ramp | 20.49% | -28.54% | 1.112 | 41.5690x | 85.45 | 90 | -1.674 |
| drop_83 | simplified_no_ramp | 20.31% | -29.54% | 1.105 | 40.3844x | 83.55 | 89 | -2.012 |
| drop_83 | compact_original_no_ramp | 20.49% | -28.54% | 1.112 | 41.5690x | 85.45 | 90 | -1.674 |
| drop_83 | compact_simplified_no_ramp | 20.31% | -29.54% | 1.105 | 40.3844x | 83.55 | 89 | -2.012 |
| drop_29 | original | 18.35% | -29.55% | 0.998 | 29.0780x | 354.75 | 568 | -3.205 |
| drop_29 | simplified | 18.57% | -31.74% | 1.002 | 30.1510x | 308.70 | 442 | -3.266 |
| drop_29 | original_no_ramp | 18.97% | -32.11% | 1.020 | 32.2664x | 276.70 | 361 | -3.190 |
| drop_29 | simplified_no_ramp | 18.62% | -33.14% | 1.005 | 30.3994x | 270.90 | 357 | -3.708 |
| drop_29 | compact_original_no_ramp | 18.97% | -32.11% | 1.020 | 32.2664x | 276.70 | 361 | -3.190 |
| drop_29 | compact_simplified_no_ramp | 18.62% | -33.14% | 1.005 | 30.3994x | 270.90 | 357 | -3.708 |
| loo_2 | original | 17.01% | -26.87% | 0.933 | 23.1337x | 240.05 | 349 | -4.551 |
| loo_2 | simplified | 17.24% | -28.32% | 0.943 | 24.0683x | 213.25 | 276 | -4.595 |
| loo_2 | original_no_ramp | 17.37% | -29.50% | 0.948 | 24.6031x | 198.00 | 234 | -4.792 |
| loo_2 | simplified_no_ramp | 17.54% | -29.95% | 0.957 | 25.3167x | 196.00 | 234 | -4.788 |
| loo_2 | compact_original_no_ramp | 17.37% | -29.50% | 0.948 | 24.6031x | 198.00 | 234 | -4.792 |
| loo_2 | compact_simplified_no_ramp | 17.54% | -29.95% | 0.957 | 25.3167x | 196.00 | 234 | -4.788 |
| loo_1 | original | 17.79% | -24.50% | 0.958 | 26.4410x | 213.10 | 344 | -3.766 |
| loo_1 | simplified | 17.78% | -23.28% | 0.957 | 26.3952x | 188.15 | 270 | -4.052 |
| loo_1 | original_no_ramp | 18.30% | -23.28% | 0.978 | 28.8303x | 161.45 | 197 | -3.858 |
| loo_1 | simplified_no_ramp | 18.37% | -23.39% | 0.983 | 29.1736x | 158.10 | 195 | -3.952 |
| loo_1 | compact_original_no_ramp | 18.30% | -23.28% | 0.978 | 28.8303x | 161.45 | 197 | -3.858 |
| loo_1 | compact_simplified_no_ramp | 18.37% | -23.39% | 0.983 | 29.1736x | 158.10 | 195 | -3.952 |
| loo_0 | original | 18.50% | -27.58% | 1.003 | 29.8311x | 209.10 | 325 | -3.054 |
| loo_0 | simplified | 18.90% | -30.16% | 1.017 | 31.8794x | 184.45 | 246 | -2.935 |
| loo_0 | original_no_ramp | 19.01% | -30.99% | 1.022 | 32.5064x | 158.40 | 190 | -3.146 |
| loo_0 | simplified_no_ramp | 19.15% | -30.84% | 1.029 | 33.2597x | 161.30 | 195 | -3.174 |
| loo_0 | compact_original_no_ramp | 19.01% | -30.99% | 1.022 | 32.5064x | 158.40 | 190 | -3.146 |
| loo_0 | compact_simplified_no_ramp | 19.15% | -30.84% | 1.029 | 33.2597x | 161.30 | 195 | -3.174 |

## Robustness versus original

| Strategy | Median area reduction | Affected comparator cases | Worst abs CAGR fault delta pp | Formal screen |
|---|---:|---:|---:|---|
| original | 0.0% | 6 | 6.137 | FAIL |
| simplified | 11.7% | 6 | 5.823 | FAIL |
| original_no_ramp | 24.2% | 6 | 5.570 | FAIL |
| simplified_no_ramp | 24.7% | 6 | 5.641 | FAIL |
| compact_original_no_ramp | 24.2% | 6 | 5.570 | FAIL |
| compact_simplified_no_ramp | 24.7% | 6 | 5.641 | FAIL |

The formal robustness gate requires at least 50% median individual fault-area reduction and no more than 1pp baseline CAGR loss. Economic preservation is a separate four-window gate. Exact compact/reference and restart comparisons are recorded per case.

These six new faults extend the earlier hardening study on the same historical dataset. Prior cases are not pooled. No production promotion or merge follows from this report.
