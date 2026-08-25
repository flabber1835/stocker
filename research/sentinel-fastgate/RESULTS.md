# Sentinel Fastgate — retained historical result

**Status:** research result; no production activation.

Sentinel Fastgate preserves the authoritative slow/severe state machine, severe hold, Sentinel 1.1 recovery ramp, and Simplified Concordance LD-RC. It changes only FAST confirmation and ownership of the first provisional warning.

## Exact unchanged-control parity

The unmodified arm reproduced all 5,032 authoritative sessions:

- native decision maximum absolute difference: `0.0`
- LD-RC desired decision maximum absolute difference: `0.0`
- effective allocation maximum absolute difference: `0.0`
- daily NAV maximum absolute difference: `2.2026824808563106e-13`
- authoritative ending multiple: `59.15428690967636x`
- reconstructed ending multiple: `59.154286909676216x`

## Headline comparison

| Window | Strategy | CAGR | Sharpe | Max DD | Ending multiple |
|---:|---|---:|---:|---:|---:|
| 5y | **Sentinel Fastgate** | **29.8919%** | **1.4032** | **-20.8689%** | **3.6996x** |
| 5y | Current authoritative | 27.7402% | 1.3239 | -20.8689% | 3.4030x |
| 5y | SPY | 12.7559% | 0.7878 | -24.4973% | 1.8231x |
| 10y | **Sentinel Fastgate** | **28.2945%** | **1.3591** | **-21.6958%** | **12.0933x** |
| 10y | Current authoritative | 27.2274% | 1.3189 | -21.6958% | 11.1239x |
| 10y | SPY | 14.9831% | 0.8704 | -33.7001% | 4.0420x |
| 15y | **Sentinel Fastgate** | **23.4180%** | **1.2679** | **-21.6958%** | **23.5109x** |
| 15y | Current authoritative | 22.7327% | 1.2383 | -21.6958% | 21.6262x |
| 15y | SPY | 14.3973% | 0.8710 | -33.7001% | 7.5268x |
| 20y | **Sentinel Fastgate** | **23.1327%** | **1.2357** | **-21.6958%** | **64.1958x** |
| 20y | Current authoritative | 22.6302% | 1.2138 | -21.6958% | 59.1543x |
| 20y | SPY | 11.2563% | 0.6473 | -55.2019% | 8.4433x |

## Verdict

Over 20 years, Sentinel Fastgate adds **0.5025 percentage points of CAGR per year**, raises Sharpe by **0.0219**, leaves maximum drawdown unchanged, and increases ending wealth by **8.52%** relative to the current strategy.

The effective allocation differs on only 55 sessions: one costly provisional session in 2010, earlier confirmed protection in 2022, and avoidance of the false severe/recovery episode in 2025. The factorial result shows dynamic confirmation is load-bearing; provisional treatment alone is not acceptable.

## Qualification

The controller and accounting replay are stateful and parity-gated. The canonical source contains the exact Fastgate decision policy from a causal feature snapshot. This retained performance run still uses the prior causal confirmation schedule rather than freshly rebuilding the per-security residual-correlation and co-distress features. That fresh reconstruction remains the production-promotion gate.
