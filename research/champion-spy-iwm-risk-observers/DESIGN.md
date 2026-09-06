# SPY / IWM independent market observations

Status: RESEARCH / NOT CERTIFIED. Pre-registration before economic results.

## Authority and isolation

User requested this experiment in the September 5, 2026 conversation. Base verified through GitHub: 1e7875d2b83fc549e316a97d573633b060461eda on research/champion-pit-metadata-closure. Delivery is through the connected GitHub API on research/champion-spy-iwm-risk-observers. Local shell network access is unavailable. Production main, the frozen Champion, certification work and research/champion-market-risk-controller-robustness are unchanged. No merge or production promotion is authorized.

Frozen reference: corrected run https://github.com/flabber1835/stocker/actions/runs/34007704385, source ba74e79490beb8950611b1d17f5d124833b3d91e, runtime 887f479b15ad861313da666ad698034d3847121c, profile strategy9-e3-research-champion-v1, profile hash 1101e99ae9ca327278d79d5334556ca01bbc167e2cb3410ab4902b89550e5c26, canonical dataset 5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993. Prior 20.09% CAGR remains provisional.

## Research question

Can independent SPY and IWM market observations improve the stability of exposure decisions while retaining the frozen Native controller as explicit portfolio-specific protection? Does VIX add useful information to the matched SPY/IWM design?

An EQM classification correction changed both holdings and leadership observations. Its full economic effect has not been isolated to the risk signal alone. No such attribution is assumed here.

## Frozen and experimental dimensions

Keep the same raw Wealth Core book, ranking, eligibility, corrected classifications, terminal economics, costs, cash yield and order timing. Native portfolio protection remains frozen, including its raw Wealth Core drawdown and held-position breadth observations. That guard is legitimately affected when actual holdings change.

Change the observations consumed by the outer LDRC only. Preserve its 55% ceiling, eight-session persistence, native episode/latch behavior, SPY 11% rebound route, native/effective-native gate, WC drawdown -10% gate and previous-target holding behavior. Explicit experimental entry change: external market stress replaces the conjunction of leadership r20 <= -8.5% and SPY r20 >= 0. Recovery observations use the external indices, including an external-return-versus-WC concordance check. This is a declared observation-policy change, not a new Champion parameter setting.

## Arms and bounded grid

Controls: unchanged corrected Champion; Native portfolio guard alone.

Matched families:
1. SPY observations + frozen Native guard.
2. SPY and IWM observations + the same guard.
3. SPY and IWM observations with VIX confirmation + the same guard.

For each price observer, compute medium-term simple moving average, drawdown from a trailing 126-close high, 20-session realized volatility divided by 60-session realized volatility, and 20/40-session returns. Stress requires price below its moving average, drawdown beyond its threshold and volatility ratio beyond its threshold. In the two-index design either index can report stress. Full recovery requires both indices' 20/40-session returns positive and volatility ratios <= 1. The single-index control applies the corresponding SPY rule.

Predefined grid: moving-average sessions {80,120,160}; drawdown {-0.08,-0.10,-0.12}; volatility ratio {1.0,1.2,1.4}. Exactly 27 points per family, 81 variants plus two controls. The central 120/-0.10/1.2 point is fixed before results and is reported regardless of performance. No adaptive refinement or winning-point selection in this first stage.

VIX confirmation uses fixed thresholds: stress requires lagged VIX >=25; full recovery additionally requires lagged VIX <=20. The extra one-session VIX lag is conservative about historical daily-publication timing. No VIX threshold search is authorized in this first stage.

## Data phase

Extract SPY and IWM from the already retained Sharadar SFP at the frozen base, retaining source bytes/hashes, exact duplicates and conflicts accounting, coverage and adjusted-price-domain disclosure. SFP closeadj is a retrospectively adjusted series. Ratio/trend features are scale invariant, but this does not prove vendor-vintage PIT availability.

Collect official Cboe VIX daily history in a separate data-only operation, truncate through 2026-07-31, retain source and acquisition hashes and missing-date accounting. Preserve data in a content-addressed package and commit its pointer before economic replay. A missing required observation stops that arm; never substitute zero, a future value or another provider silently.

## Execution and accounting

First confirm whether the same-session multi-arm chronological harness can generate the shared raw Wealth Core book once and evolve every controller independently. If used, all allocations must be computed within that fresh run; prior replay files are comparison evidence only. An unchanged control must reproduce the corrected reference on a matching window, including daily equity/allocation/holdings identities.

Any preliminary calculation using an already generated Wealth Core path must be labeled FROZEN_PATH_ATTRIBUTION_DIAGNOSTIC, never a fresh backtest or certified CAGR. Include the identical cash-return and turnover-cost convention, and prove baseline reconstruction parity before publishing such diagnostics.

All close-derived observations act at the following eligible open. Preserve overnight old allocation and intraday new allocation on rebalance days. Use the canonical cash sleeve and 0.001 turnover cost. Long-only; no leverage; external target <= native guard target.

## Independent launches

Include a separate five-year launch for 2021-07-30 through 2026-07-31 (first session on/after the five-calendar-year anniversary). Its pre-start observations warm indicators only. Initialize cash, holdings, pending orders, stops, cooldowns and controllers from explicit fresh state. Report it as an independently initialized launch, distinct from the trailing five years of the 20-year portfolio. Rolling launches are a subsequent robustness stage, not proof supplied by trailing windows.

## Robustness tests and evaluation

Causality: prefix invariance under future-price mutation; one-session target lag; feature-window bounds; missing-date refusal; VIX lag; controller state isolation. Accounting: cash sleeve, turnover costs and next-open tests; unchanged-control parity. Classification independence: change arbitrary classification/leadership inputs while holding external data and the raw portfolio path fixed. External decisions must remain identical. Full-stock-universe changes can still affect Native protection and raw Wealth Core.

Report all 81 variants: 5/10/15/20-year trailing CAGR and drawdown with exact dates, ending wealth, Sharpe definition, same-window SPY, exposure fraction, defensive episodes, first allocation divergence, annual relative log-wealth contributions, crisis/recovery intervals, and adjacent-grid dispersion. Compare families using distributions and local plateaus. More negative maximum drawdown is worse. Absolute return dispersion across different market windows alone is not proof of fragility; compare contemporaneous benchmark-relative results.

Certification and robustness are separate. No variant is promoted automatically. The 83 held/pending inferred-common names are only a priority subset of the current Champion's certification dependencies; unheld candidate displacers, rank-population effects and leadership contributors also require closure or a proven irrelevance bound.
