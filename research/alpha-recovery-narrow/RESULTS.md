# Narrow alpha-recovery result

**Status:** research result; no production activation.

This experiment keeps the authoritative slow/severe state machine, severe hold, Sentinel 1.1 recovery ramp, and Simplified Concordance LD-RC semantics unchanged. Only the FAST-entry boundary changes:

1. causal confirmation may authorize the existing native FAST severe entry;
2. the first unconfirmed warning receives an external 55% ceiling;
3. that ceiling is applied after LD-RC and never opens or mutates an LD-RC recovery episode;
4. a second consecutive warning confirms the existing native FAST entry.

## Control parity

The unmodified arm reproduced the authoritative 5,032-session tape exactly to floating-point replay tolerance:

- native decision max absolute difference: `0.0`
- LD-RC desired decision max absolute difference: `0.0`
- effective allocation max absolute difference: `0.0`
- daily NAV max absolute difference: `2.21e-13`
- authoritative ending multiple: `59.15428690967636x`
- reconstructed ending multiple: `59.15428690967622x`

## Headline comparison

| Window | Strategy | CAGR | Sharpe | Max DD | Ending multiple |
|---:|---|---:|---:|---:|---:|
| 5y | Narrow candidate | 29.8919% | 1.4032 | -20.8689% | 3.6996x |
| 5y | Current authoritative | 27.7402% | 1.3239 | -20.8689% | 3.4030x |
| 5y | SPY | 12.7559% | 0.7878 | -24.4973% | 1.8231x |
| | | | | | |
| 10y | Narrow candidate | 28.2945% | 1.3591 | -21.6958% | 12.0933x |
| 10y | Current authoritative | 27.2274% | 1.3189 | -21.6958% | 11.1239x |
| 10y | SPY | 14.9831% | 0.8704 | -33.7001% | 4.0420x |
| | | | | | |
| 15y | Narrow candidate | 23.4180% | 1.2679 | -21.6958% | 23.5109x |
| 15y | Current authoritative | 22.7327% | 1.2383 | -21.6958% | 21.6262x |
| 15y | SPY | 14.3973% | 0.8710 | -33.7001% | 7.5268x |
| | | | | | |
| 20y | Narrow candidate | 23.1327% | 1.2357 | -21.6958% | 64.1958x |
| 20y | Current authoritative | 22.6302% | 1.2138 | -21.6958% | 59.1543x |
| 20y | SPY | 11.2563% | 0.6473 | -55.2019% | 8.4433x |
| | | | | | |

## Candidate minus current

| Window | CAGR delta | Sharpe delta | Max-DD delta |
|---:|---:|---:|---:|
| 5y | +2.1517 pp/yr | +0.0793 | -0.0000 pp |
| 10y | +1.0671 pp/yr | +0.0402 | +0.0000 pp |
| 15y | +0.6853 pp/yr | +0.0296 | +0.0000 pp |
| 20y | +0.5025 pp/yr | +0.0219 | +0.0000 pp |

## 20-year verdict

The narrowed candidate improves the 20-year result from **22.6302% to 23.1327% CAGR**, increases Sharpe from **1.2138 to 1.2357**, and leaves maximum drawdown unchanged at **-21.6958%**. Ending wealth rises from **59.1543x to 64.1958x**, an **8.52%** relative increase.

The allocation path differs on only 55 sessions across three effective episodes:

- **2010-05-10:** the one-session provisional warning costs about 0.61% relative wealth in that episode;
- **2022-04-27 through 2022-06-13:** earlier confirmed FAST protection adds about 0.48% relative wealth;
- **2025-04-08 through 2025-05-07:** the false-positive filter plus one-session provisional response adds about 8.73% relative wealth.

The 2x2 result shows that provisional treatment without causal confirmation is unacceptable over long horizons. Dynamic confirmation is the load-bearing change; the provisional sleeve is useful only when paired with it.

## Qualification

The controller, execution, and equity curve were replayed statefully on the authoritative return/accounting tape. The causal peer decisions are a retained schedule ported to the authoritative tape rather than a fresh recomputation from authoritative per-security held histories. This remains the principal promotion gate.
