# Strategy 9 + E3 broad stability-basin final verdict

Date: 2026-09-05

## Verdict

The broad full-history stability exercise supports a stable research parameter center. Selection was made by plateau centrality and mechanical invariance, not by maximizing historical CAGR.

Final research center:

| Parameter | Original E3 | Final center | Decision |
|---|---:|---:|---|
| LDRC_REC | 7 sessions | **8 sessions** | move to interior of local 7-9 stable region |
| LDRC_R20 | -8.0% | **-8.5%** | better centered with baseline path/economic parity |
| LDRC_V | 11.0% | **11.0%** | keep; 10.5% and 12% alter controller topology |
| LDRC_DD | -10.0% | **-10.0%** | exact midpoint of flat -9/-10/-11 plateau |
| divergence SPY floor | 0.0% | **0.0%** | semantic zero is centered in the stable band |
| full-recovery r40 floor | 0.0% | **0.0%** | semantic zero is centered in the stable band |
| FAST damaged breadth | 87.5% | **88.0%** | move off exact discrete-breadth boundary |
| healthy damaged ceiling | 62.5% | **63.0%** | move off exact discrete-breadth boundary |

Only four parameters change from the original E3: REC, R20, FAST damaged breadth, and healthy damaged ceiling.

## Exact center economics

| Window | CAGR | Max DD | Sharpe | Ending multiple |
|---|---:|---:|---:|---:|
| 5y | 27.2967% | -20.4865% | 1.318578 | 3.342610x |
| 10y | 24.3197% | -28.6507% | 1.195193 | 8.818587x |
| 15y | 20.6091% | -28.6507% | 1.127958 | 16.622661x |
| 20y | **20.3000%** | **-28.6507%** | **1.100287** | **40.300396x** |
| max, 1998-01-02 to 2026-07-31 | **19.9466%** | **-33.2817%** | **1.073346** | **180.770037x** |

Center structure over 7,188 sessions:

- allocation transitions: 37
- cross-surface releases: 3
- divergence entries: 8
- FAST signal sessions: 21
- SLOW signal sessions: 56

## Cost versus original E3

Original E3 20y: 20.3277% CAGR / -28.6186% max DD / 1.101492 Sharpe.

Final center 20y: 20.3000% CAGR / -28.6507% max DD / 1.100287 Sharpe.

The robustness move therefore gives up about 2.8 basis points of annualized 20-year return and about 3.2 basis points of drawdown, with essentially unchanged Sharpe. On max history, the final center has nearly identical CAGR and slightly better max drawdown than the original E3.

## Stage 2 exact sensitivity evidence

Stage 2 run: https://github.com/flabber1835/stocker/actions/runs/33974007040

Stage 2 head: `15b7f1f5e1cde5b7f8af1898d04ff3c0dc303a8b`

All 11/11 exact full-history points completed successfully.

| Point | 20y CAGR | 20y Max DD | 20y Sharpe | Transitions | Cross releases | Divergence entries | Interpretation |
|---|---:|---:|---:|---:|---:|---:|---|
| center | 20.3000% | -28.6507% | 1.100287 | 37 | 3 | 8 | selected center |
| DD -9% | 20.3000% | -28.6507% | 1.100287 | 37 | 3 | 8 | exact plateau parity |
| DD -11% | 20.3000% | -28.6507% | 1.100287 | 37 | 3 | 8 | exact plateau parity |
| SPY floor -0.5% | 20.2877% | -28.6507% | 1.099969 | 37 | 3 | 8 | effectively flat |
| SPY floor +0.5% | 20.3000% | -28.6507% | 1.100287 | 37 | 3 | 8 | exact parity |
| SPY floor +1.0% | 20.2293% | -28.6507% | 1.096959 | 37 | 3 | 8 | beginning to soften |
| r40 floor -0.5% | 20.3000% | -28.6507% | 1.100287 | 37 | 3 | 8 | exact parity |
| r40 floor +0.5% | 20.3000% | -28.6507% | 1.100287 | 37 | 3 | 8 | exact parity |
| r40 floor +1.0% | 20.3000% | -28.6507% | 1.100287 | 37 | 3 | 8 | 20y parity; small earlier-history effect |
| V 10.5% | 20.3553% | -28.3873% | 1.102234 | **39** | **2** | **9** | topology changes; reject performance chase |
| V 12.0% | 20.1426% | -28.6507% | 1.093267 | **35** | **4** | **7** | topology changes and economics weaken |

### LDRC_DD

The -9%, -10%, and -11% points are identical in economics and structural counts. -10% is therefore a true tested center, not a fitted winner.

### Divergence SPY floor

The region from -0.5% through +0.5% is effectively flat. +1.0% begins to reduce CAGR and Sharpe without changing the high-level event counts. Keep 0% because it is central and has clear semantics.

### Full-recovery r40 floor

-0.5%, 0%, and +0.5% are exactly identical. +1.0% retains 20y parity but makes a small earlier-history change: max-history CAGR falls to about 19.9293% and max DD reaches about -33.5567%. Keep 0% as the central semantic value.

### V-rebound threshold

This is the clearest active boundary in Stage 2. V=10.5% produces superficially better historical economics, but changes the controller to 39 transitions / 2 cross-surface releases / 9 divergence entries. V=12% changes it in the other direction to 35 / 4 / 7 and weakens 20y economics. The 11% value is retained because it is between two mechanically distinct regimes. The 10.5% result is explicitly not adopted as a backtest optimization.

## Stage 1 evidence incorporated

Stage 1 run: https://github.com/flabber1835/stocker/actions/runs/33971822256

Stage 1 head: `61c48d5ed6015528141650c639d2e025bb696e61`

Source E3 head: `3f27834db427e71d9bb8d0b6160c8835b739c906`

Stage 1 established that:

- R20=-8.5% is much more locally centered than -8.0% while preserving the accepted baseline path/economics in the refined screen.
- REC=8 is an interior choice near the stable 7-9 region. REC=9 was not selected despite slightly better historical economics.
- FAST 88.0-88.5% and healthy damaged ceilings around 63.0-63.5% preserve the same tested path/economics. 88% / 63% also avoid the original thresholds landing exactly on observed discrete breadth values.
- V=11.5% had already shown deterioration and an extra cross-surface release, which Stage 2 confirmed as part of a mechanically active V dimension.

## Immutable evidence anchors

Representative Stage 2 artifacts:

- center: artifact `9972336789`, SHA-256 `a6da0c8a431befb77f41513eb3a2202d0c1be39ffd091b5f3e075c1169fed227`
- DD -9%: artifact `9972326396`, SHA-256 `c96845afdd82596f42fc2d9a636b18b90d76a6bb09816b6c070ad3102b1849d6`
- DD -11%: artifact `9972549612`, SHA-256 `df00d4d93a63a49d432d313d4d56de80729b73de8082f06d89494af7c2b7ace5`
- r40 -0.5%: artifact `9972314375`, SHA-256 `66a1b362728b324f6961d1172e19a7b8c5af5b201463def86878f440c0b927ab`
- r40 +0.5%: artifact `9972191058`, SHA-256 `5d8dcef0a75b72ab0275ee85bee52979f747cf6208fdbdeaf008e040331021e4`
- r40 +1.0%: artifact `9971998317`, SHA-256 `695059939a5671b5e5515b5747bf152918978bc8126a0d8dce50303795c1bea7`
- SPY -0.5%: artifact `9972189144`, SHA-256 `ce51da6d75370a43e28aa62a9050b5675c23b0804bf382c4018fdee13a0a4184`
- SPY +0.5%: artifact `9972191252`, SHA-256 `4beeef97e5cf7745d874e413bc234ae0ca041bb34e7bc70911be79d049c0fc6e`
- SPY +1.0%: artifact `9972192465`, SHA-256 `65c83e8c219ba1f2be095327508e0bc7c78c385b8db78bcd86a98b04abde3ed3`
- V 10.5%: artifact `9972544154`, SHA-256 `9f8fbcef2a4f5e053414616bb0e9624250988a42bd6f2172b651fd9da8c63478`
- V 12.0%: artifact `9972763421`, SHA-256 `eb0e1c6553af284babac289c41a7ad0639adddaa578f2d0ca544b74206185f9c`

Machine-readable final center is stored in `research/strategy9-e3-broad-stability/FINAL_STABILITY_CENTER_2026-09-05.json`.

## Evidence boundary

This is strong broad full-history PIT research evidence, not a formal PIT certification. The replay explicitly reports:

`exchange_gate: not applied because supplied current TICKERS snapshot cannot establish historical exchange authority`

Therefore this result must not be labeled formally PIT certified until historical exchange authority is available and the full certification contract passes.

## Implementation boundary

This verdict locks the research recommendation on the isolated stability branch only. It does not modify production Strategy 9, Sentinel, the E5/coupling branch, or any parallel PIT-corpus work.
