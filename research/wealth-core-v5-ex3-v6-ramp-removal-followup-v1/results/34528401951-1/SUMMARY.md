# Ramp removal follow-up results

Status: **INCOMPLETE**; 1/7 Core cases complete; 1/7 slots claimed.

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

## Robustness versus original

| Strategy | Median area reduction | Affected comparator cases | Worst abs CAGR fault delta pp | Formal screen |
|---|---:|---:|---:|---|
| original | — | 0 | — | PENDING |
| simplified | — | 0 | — | PENDING |
| original_no_ramp | — | 0 | — | PENDING |
| simplified_no_ramp | — | 0 | — | PENDING |
| compact_original_no_ramp | — | 0 | — | PENDING |
| compact_simplified_no_ramp | — | 0 | — | PENDING |

The formal robustness gate requires at least 50% median individual fault-area reduction and no more than 1pp baseline CAGR loss. Economic preservation is a separate four-window gate. Exact compact/reference and restart comparisons are recorded per case.

These six new faults extend the earlier hardening study on the same historical dataset. Prior cases are not pooled. No production promotion or merge follows from this report.
