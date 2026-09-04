# R1000 correlation-peer benchmark

Status: **PASS**

Evidence class: `BEST_EFFORT_PIT_R1000_CORRELATION_PEERS`

This is a causal research backtest of the frozen LD-RC strategy on a historical Russell 1000 proxy derived from authenticated historical IWB holdings. It intentionally removes historical issuer-family and sector metadata from strategy decisions. Securities are independent, and sector contagion is replaced by prior-only residual-correlation peers.

It is not formal golden PIT certification because IWB is a proxy for exact Russell 1000 membership and the historical archive has one material gap. The methodology itself remains causal: a snapshot dated `t` is usable only after `t`, and missing periods carry only the latest authenticated prior snapshot.

## Run identity

- Workflow run: `33838376828`
- Job: `100915436454`
- Exact head: `1a139402d363eeda0e61b8a9c56f08ff582c3d8e`
- Artifact: `9924555169`
- Artifact SHA-256: `0ae6baeef380c3814eb60b626c24b0c15fa8ee8da947edaf8922ab18634bc9c2`
- Artifact bytes: `2,708,595`

## Membership evidence

- First authenticated snapshot: `2006-09-29`
- Last snapshot: `2026-07-31`
- Distinct accepted snapshots: `233`
- Minimum IWB-to-contemporaneous-SEP mapping coverage: **97.52%**
- Median mapping coverage: **98.86%**
- Archive gap: January through June 2017
- Gap treatment: carry `2016-12-30` membership forward until the `2017-07-31` snapshot becomes available
- Maximum carried staleness: **182 days**
- No later snapshot is used to fill an earlier period

## Correlation-peer definition

- trailing lookback: **252 trading sessions**
- minimum common history: **120 sessions**
- SPY-residualized returns
- strongest **3** peers
- minimum accepted correlation: **0.145**
- pair correlations evaluated: `2,620,926`
- accepted peer edges: `258,401`
- insufficient residual histories: **0**

## Results

| Window | Research CAGR | Core CAGR | SPY CAGR | Research max DD | Research Sharpe | Research multiple |
|---|---:|---:|---:|---:|---:|---:|
| 5y | **17.17%** | 18.37% | 12.76% | -28.38% | 0.923 | 2.21x |
| 10y | **13.44%** | 13.61% | 14.99% | -28.38% | 0.837 | 3.53x |
| 15y | **12.70%** | 12.92% | 14.40% | -28.38% | 0.842 | 6.01x |
| nominal 20y | **12.45%** | 11.20% | 11.26% | -28.38% | 0.834 | 10.45x |
| active max, 2006-10-03 to 2026-07-31 | **12.58%** | 11.32% | 11.10% | -28.38% | 0.839 | 10.47x |

The nominal 20-year row starts `2006-07-31`, before the first authenticated R1000 membership snapshot, so it includes a short forced-cash period. The active-max row beginning `2006-10-03` is the cleaner long-horizon economic result.

## Interpretation

The R1000 idea does **not** preserve the broad-universe economics. The active R1000 result is approximately **12.58% CAGR**, materially below the broad full-PIT estimate around **20.49%**.

The important attribution is upstream of Sentinel: raw R1000 Wealth Core produces about **11.32% CAGR** over the active period, while the broad PIT raw core previously produced about **17.18%**. That strongly indicates that restricting the opportunity set to the Russell 1000 removes a large portion of the strategy's historical alpha before the risk overlay acts.

The risk machinery is still useful on R1000 over the long horizon: it raises active CAGR from about **11.32%** to **12.58%** and reduces maximum drawdown from **-44.69%** to **-28.38%**. Over the recent 5-year period, however, raw core at **18.37%** beats the controlled result at **17.17%**, so recovery/defensive behavior still sacrifices some upside in recent regimes.

## Conclusion

R1000 solves much of the metadata-complexity problem, and the correlation-peer replacement works causally, but the experiment shows that **R1000 is too restrictive if the objective is to preserve the broad strategy's ~20% long-run CAGR**. The next investigation should focus on finding the smallest broader PIT universe that restores the missing opportunity-set alpha while keeping the simplified metadata-free architecture.
