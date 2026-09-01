# Backtester Ideas

This document captures research ideas for improving how the backtester measures whether historical performance is representative of plausible future performance.

## Objective

The goal is to answer a stronger question than whether the backtest is technically correct:

> If future market dynamics are broadly drawn from the same kind of process seen over the last 20 years — bull markets, bear markets, crashes, recoveries, volatility shifts, liquidity changes, rate regimes and changing market structure — does the strategy continue to produce results from a similar distribution?

A successful historical CAGR should therefore be accompanied by evidence about robustness, regime dependence, parameter stability and plausible future outcome ranges.

## Rolling adaptive fitting

Markets evolve. A fixed parameter set estimated over a full 20-year history may become stale as market structure, liquidity, volatility and trading behavior change.

Test a predefined causal walk-forward adaptation rule using rolling historical windows.

Candidate variants:

- Fixed parameters across the full history.
- 5-year rolling fit.
- 10-year rolling fit.
- Potential hybrid: slower-moving parameters from 10 years and faster-moving parameters from 5 years.

At each historical refit date:

1. Use only information available before that date.
2. Fit only the predefined parameters allowed to adapt.
3. Freeze those parameters until the next scheduled refit.
4. Trade the following period using those frozen values.
5. Repeat through the entire backtest.

Suggested refit schedules to compare:

- Monthly.
- Quarterly.
- Annually.

The adaptive layer should remain deliberately small. Parameter ranges and fitting rules must be specified before evaluating the subsequent period.

## Required comparison

For each adaptive variant compare against the fixed strategy using at least:

- CAGR.
- Maximum drawdown.
- Volatility.
- Sharpe/Sortino where appropriate.
- Turnover.
- Number of trades.
- Win/loss distribution.
- Parameter path over time.
- Rolling 1-, 3-, 5- and 10-year performance.
- Performance by market regime.
- Performance relative to SPY.

The key question is whether adaptation improves out-of-sample robustness across regimes, not merely full-period CAGR.

## Parameter stability tests

For every important strategy parameter:

- Sweep values around the chosen setting.
- Measure whether performance changes smoothly or collapses near the selected value.
- Identify broad plateaus of acceptable behavior.
- Flag parameters whose success depends on a narrow optimum.

A robust strategy should retain similar economics under modest parameter perturbations.

## Regime robustness

Measure the strategy separately across distinct market environments, including:

- Bull markets.
- Bear markets.
- High-volatility periods.
- Low-volatility periods.
- Financial crises.
- COVID crash and recovery.
- Rising-rate regimes.
- Falling-rate regimes.
- Sideways markets.
- Strong momentum environments.
- Momentum reversals.

The strategy does not need identical returns in every regime. The objective is to understand where returns come from and whether failure modes are economically plausible.

## Period stability

Calculate rolling historical results for multiple horizons:

- 3 years.
- 5 years.
- 10 years.
- 15 years.

Measure the distribution of CAGR, drawdown and relative performance across every possible rolling window.

This prevents a single favorable start/end date from dominating the interpretation of a 20-year result.

## Event and concentration dependence

Measure how much total performance depends on a small number of observations.

Tests should include:

- Remove the best 1, 5 and 10 trades.
- Remove the best-performing stock names.
- Remove the best calendar year.
- Remove the strongest regime.
- Measure contribution by stock, sector, year and trade.

A strategy whose economics disappear after a few exceptional observations should be treated as fragile.

## Strategy-selection overfitting

A technically perfect backtest can still overstate future performance if the final strategy was selected after many experiments on the same historical sample.

Track and evaluate:

- Number of materially different strategy variants tested.
- Number of parameter searches performed.
- Whether design changes followed observed historical performance.
- Whether the final strategy remains strong under neighboring parameter values and alternative subperiods.

Where practical, use untouched or pseudo-out-of-sample periods for major design decisions.

## Future-performance distribution

Do not report only one 20-year CAGR. Estimate the range of plausible future outcomes under historical-like dynamics.

Use block/bootstrap or other dependence-preserving resampling methods that retain important properties such as:

- Volatility clustering.
- Drawdown clustering.
- Serial dependence.
- Cross-sectional dependence.
- Crash/recovery sequences.

Target outputs:

- Historical CAGR.
- Median simulated 20-year CAGR.
- 25th percentile CAGR.
- 10th percentile CAGR.
- 5th percentile CAGR.
- Probability of underperforming SPY.
- Probability of CAGR below selected thresholds.
- Distribution of maximum drawdowns.
- Worst historically plausible sequences.

## Execution robustness

Stress the assumptions connecting simulated decisions to executable trades.

Test sensitivity to:

- Delayed fills.
- Opening gaps.
- Bid/ask spread assumptions.
- Slippage.
- Liquidity limits.
- Volume participation limits.
- Trading halts.
- Delistings.
- Corporate actions.

The objective is to quantify how much CAGR survives progressively less favorable execution assumptions.

## Golden PIT database requirement

These tests should run against the completed canonical point-in-time historical database so that universe membership, identity, ticker history, security type, sector and other eligibility inputs are reconstructed causally.

All walk-forward fitting must obey the same point-in-time boundary. No parameter fit may see observations, classifications or metadata from the period it is intended to predict.

## Recommended first experiment after PIT reconstruction

Run the current LDRC strategy unchanged in three forms:

1. Fixed parameters.
2. 5-year rolling walk-forward fit.
3. 10-year rolling walk-forward fit.

Freeze the fitting algorithm and allowed parameter set before examining the subsequent-period results.

Compare full-period performance, rolling performance, regime performance, drawdowns, turnover and the time series of fitted parameter values.

If the adaptive versions improve regime robustness while parameter changes remain gradual and economically interpretable, rolling adaptation may be justified as part of the production strategy.

## Backtestability

All ideas in this document are backtestable with the retained research backtester once the canonical PIT reconstruction is complete. The rolling-fit tests require the backtester to support explicit train/refit/trade windows and to persist the fitted parameter state causally through each walk-forward segment.
