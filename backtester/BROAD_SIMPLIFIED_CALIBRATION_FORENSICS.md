# Broad simplified calibration forensics

Date: 2026-09-04

## Scope

This report analyzes the simplified broad-universe PIT-estimate architecture before calibration.

Simplified broad baseline:

- experiment: `EXPERIMENT_2_BROAD_INDEPENDENT_CORRELATION`
- Actions run: `33840689248`
- exact head: `5f80de11175c5dd52dc4e3f7afdd92d7246c9324`
- broad eligibility remains the prior broad PIT-estimate/common-stock seam
- issuer-family blocking disabled; securities are independent
- sector taxonomy removed from strategy decisions
- Sentinel contagion uses prior-only SPY-residual correlation peers

This remains a PIT research estimate, not formal golden PIT certification, because the broad common-stock/category authority is not fully reconstructed point-in-time.

## Baseline economics

| Window | Controlled CAGR | Core CAGR | Controlled max DD | Controlled Sharpe |
|---|---:|---:|---:|---:|
| 5y | 25.75% | 23.79% | -19.70% | 1.269 |
| 10y | 23.26% | 21.75% | -29.63% | 1.158 |
| 15y | 19.85% | 18.72% | -29.63% | 1.098 |
| 20y | 19.66% | 17.18% | -29.63% | 1.075 |
| max 1998-2026 | 19.49% | 17.20% | -33.46% | 1.055 |

The prior broad sector-based PIT-estimate benchmark was 20.49% CAGR, -28.87% max DD, Sharpe 1.110 over 20 years.

## Wealth Core

Wealth Core is exonerated for the simplified-broad performance difference:

- the simplified broad Wealth Core equity curve is bit-for-bit identical to the prior broad PIT benchmark;
- green breadth is also identical;
- raw 20-year Wealth Core remains about 17.18% CAGR, -45.14% max drawdown, Sharpe 0.866;
- 747 buys / 727 sells remain unchanged.

Frozen Wealth Core mechanics:

- 25 slots
- 4% entry size
- at most one new admission per day after initialization
- 126-session momentum with the most recent 21 sessions skipped (`lag21 / lag126 - 1`)
- score = `log1p(momentum) / annualized volatility`
- top 10% momentum candidate pool, then durable score ordering
- new admission requires non-negative recent 21-session return
- 30% trailing retention stop (`STOP_RET=0.70`)
- age-119 review; underwater names that no longer qualify are exited
- 21-session cooldown after exit
- next-open execution with 10 bps modeled cost

Active broad geometry from 2006-07-31 onward:

- median eligible population: about 1,408
- median top-decile population: about 141
- median held count: 24
- >=20 holdings on about 91% of sessions

No Wealth Core parameter is changed in the calibration.

## Correlation-peer damaged breadth

Peer construction remains frozen:

- trailing 252 sessions
- minimum 120 common observations
- stock returns residualized against SPY
- strongest 3 peers
- minimum residual correlation 0.145
- each holding evaluates its own state plus its accepted peers
- contagion amber if at least 50% of that local neighborhood is red and the holding is not green

Replacing sector contagion with correlation peers changes only the damaged breadth state in the controlled comparison:

- Wealth Core changed sessions: 0
- green changed sessions: 0
- damaged changed sessions: 2,477
- correlation damaged > sector damaged: 2,018 sessions
- correlation damaged < sector damaged: 459 sessions
- mean damaged shift: about +1.39 percentage points
- upper-tail shift is commonly about +2.5 to +5 percentage points

FAST signal differs on 7 sessions, native target on 157 sessions, and final allocation on 108 sessions versus the retired sector-based broad path.

## Native FAST

Frozen FAST requires all of:

- Wealth Core DD <= -10%
- damaged >= 85%
- green <= 20%
- Wealth Core R5 <= -5% OR R10 <= -8%
- damaged breadth acceleration over 5 sessions >= 30 percentage points
- SPY 5/20 volatility acceleration >= 4%
- SPY R20 <= -1% OR Wealth Core R10 <= -10%

FAST remains valuable. Major examples include 2008 and 2020, where raw Wealth Core continued materially lower after the FAST decision.

The simplified correlation breadth creates one clear marginal false-positive episode:

- `2025-04-07`: damaged = 86.36%, FAST fires
- the following 20/40/60-session raw Wealth Core returns are approximately +9.35% / +12.51% / +16.00%
- the correlation path stays at zero allocation from 2025-04-08 through 2025-05-07
- this costs roughly 6% relative wealth versus the prior broad overlay in that interval

Current FAST signal observations below 87.5% damaged are limited to:

- 2001-01-04: 85.0% (the same episode reaches 95% the next session)
- 2001-01-08: 85.0%
- 2008-07-02: 86.96% (the same episode reaches 100% on 2008-07-08)
- 2025-04-07: 86.36% (no later >=87.5% FAST-qualified observation in that break)

Therefore a modest FAST damaged threshold increase can filter the 2025 event while preserving the severe historical crisis witnesses, with a possible few-session delay in 2008.

## Native SLOW

SLOW is entered only while the ordinary/base-FAST stress base is active and requires:

- base duration >=30 sessions
- loss since base anchor <= -2%
- Wealth Core R40 <= -3%
- damaged >=75%
- green <=25%

Simplified-broad SLOW episode starts:

- 2010-06-29, WC DD about -20.1%
- 2011-10-03, WC DD about -22.0%
- 2018-12-19, WC DD about -28.1%
- 2022-05-18, WC DD about -22.8%

2010, 2011 and 2018 are followed by rebound return; 2022 is followed by further weakness and is genuinely useful. SLOW therefore remains mixed and late, but the evidence does not support changing it in the same first calibration pass.

All actual SLOW entries already occur with damaged breadth above about 80.9%, so the immediate 75% numerical boundary is not the identified problem.

## Healthy/recovery state

Native recovery defines healthy as:

- Wealth Core R20 > 0
- damaged <=60%
- green >=20%

The correlation breadth scale makes the 60% ceiling slightly too strict in one economically important recovery:

- 2010-07-30, 2010-08-02 and 2010-08-03 have positive R20 and adequate green breadth but damaged = 60.87%
- those sessions narrowly fail the existing recovery condition
- the simplified correlation path remains materially more defensive during the subsequent rebound

A 62.5% ceiling admits these near-threshold observations without meaningfully broadening healthy classification in the major 2008/2020 crisis periods.

## Ramp

After severe native risk-off, the fragile recovery ramp uses 55% then 65% exposure, with 10 healthy confirmations per stage.

In this simplified broad history, native ramp episodes are concentrated in 2015 and 2022. Raw Wealth Core is positive during the ramp windows, so the ramp gives up some rebound return, but 2022 demonstrates why gradual re-risking can still be useful. It is left frozen for this pass.

## LD-RC

LD-RC sits downstream of native Sentinel. It can:

- cap full native risk at 55% when Wealth Core is down >=10%, recent leadership R20 <= -8%, and SPY R20 is non-negative;
- hold a prior defensive allocation after native recovers until recent-leadership R20/R40 are both healthy for 7 sessions or SPY R20 exceeds 11%.

LD-RC effects are mixed:

- it materially protects portions of 2000/2001 and 2021-2022;
- it delays rebound exposure in 2010 and 2019;
- the sample of distinct divergence entries is small.

No LD-RC parameter is changed in this pass.

## Chosen calibration

The first simplified-broad calibration is deliberately narrow and changes only the damaged-breadth scale used by native FAST/recovery:

- `FAST['dam']`: **0.85 -> 0.875**
- healthy damaged ceiling: **0.60 -> 0.625**

Frozen:

- Wealth Core: all parameters
- peer lookback/count/correlation floor
- peer contagion rule
- FAST DD/green/short-return/acceleration/volatility/confirmation thresholds
- SLOW: all parameters
- ramp: all parameters
- LD-RC: all parameters

The intent is to remove marginal correlation-peer panic classification while modestly normalizing recovery hysteresis. It is not a wholesale parameter optimization.

## Calibration run

Workflow: `.github/workflows/backtester-calibrate-broad-simplified-breadth.yml`

Actions run: `33876316789`

Exact calibration head: `238891bf67cc75afa3efd4b82b71cfdb52c2fd75`

Status at report creation: **running**.
