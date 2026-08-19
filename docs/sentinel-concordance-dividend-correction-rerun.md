# Sentinel Concordance — dividend-domain correction rerun

**Date:** 2026-08-19  
**Status:** corrected research evidence; not certification  
**Parent research record:** `docs/sentinel-concordance-research.md`

## Executive conclusion

The previous Sentinel Concordance headline of **23.24% 20-year CAGR / -22.60% maximum drawdown** must not be treated as a current economic claim.

The Sharadar ACTIONS dividend stream was being interpreted on the wrong share basis in canonical Wealth Core: ACTIONS dividend `value` is stated on Sharadar's current split-adjusted share basis, while historical holdings are carried in the raw/as-traded share count. The corrected conversion is:

```
raw_dividend_per_share = ACTIONS.value * SEP.closeunadj / SEP.close
```

The corrected 20-year hardened Sentinel control is now:

- **CAGR: 21.3433%**
- **maximum drawdown: -24.7500%**
- **ending multiple: 47.9019x**
- **daily Sharpe: ~1.105**
- **window: 2006-07-31 through 2026-07-31**

This independently reproduces, to rounding, the approximately **21.34% / -24.75%** action-normalized control already recorded in the earlier Concordance research document. That agreement is strong evidence that the dividend-domain correction is economically coherent rather than an arbitrary backtest adjustment.

The original single **durable independent witness** scratch implementation that produced 23.24% was not retained in the repository or retained research files. Therefore that exact candidate cannot honestly be rerun or re-certified. Reconstructing a merely similar shadow and labelling it the original would create false lineage.

A retained-definition Concordance rerun was therefore performed with the independent **leadership-overlap recovery witness**, whose definition is preserved by the earlier research: compare the established 6-to-1 momentum leadership population with an equally sized recent 21-session leadership population and require their overlap to normalize before risk-on transitions.

## Corrected data and accounting

The rerun used the same corrected Sharadar corpus as the dividend-fixed Wealth Core control:

- SEP signal close: split-adjusted / dividend-unadjusted;
- raw close: `closeunadj`;
- corrected dollar-liquidity invariant: `SEP.close * SEP.volume`, equivalently raw close times raw-compatible volume;
- ACTIONS dividends converted to the historical raw-share basis;
- split-before-dividend same-session ordering;
- next-open Sentinel allocation changes with 10 bp allocation-change cost;
- BIL as the defensive sleeve;
- hardened fast-crisis detector using the corrected 30-percentage-point damage-acceleration threshold.

The allocation replay reproduced the corrected hardened control NAV to machine precision before any Concordance gate was applied (maximum relative error below `6e-15`).

## Independent leadership witness

For every session:

1. form the causally eligible Wealth Core population using the corrected liquidity domain;
2. rank by established 6-to-1 momentum and retain the established top-decile population;
3. rank the same eligible population by recent 21-session return and retain an equally sized recent-leadership population;
4. define leadership overlap as the intersection size divided by that population size.

The sensor still identifies the intended false-recovery episodes. On **2008-12-23**, leadership overlap was only **6.93%**. On **2022-01-03**, it was **8.33%**. So the qualitative Concordance insight survives: the adaptive Wealth Core book can appear healthier before the broader leadership opportunity set has normalized.

## Primary corrected Concordance rerun

The predeclared central rule used:

- leadership overlap threshold: **30%**;
- SPY 20-session V-rebound exception: **10%**;
- every upward Sentinel allocation change requires concordance;
- risk-off reductions remain immediate and authoritative.

Result:

| Window | Corrected hardened control CAGR | Leadership Concordance CAGR | Control max DD | Concordance max DD |
|---|---:|---:|---:|---:|
| 5y | 26.8108% | 26.3587% | -23.8182% | -21.5894% |
| 10y | 26.8685% | 26.6423% | -24.7500% | -22.7093% |
| 15y | 21.5697% | 22.3461% | -24.7500% | -22.7093% |
| 20y | **21.3433%** | **21.3941%** | **-24.7500%** | **-22.7093%** |

20-year Concordance details:

- ending multiple: **48.3047x**;
- daily Sharpe: **~1.141**;
- allocation transitions: **18** versus 20 for the corrected hardened control;
- maximum-drawdown improvement: **2.04 percentage points**;
- CAGR change: approximately **+0.05 percentage points**.

This is a credible drawdown improvement, but it is **not a universal dominance result**: trailing 5-year and 10-year CAGR are lower than the corrected control.

## Neighborhood after the dividend correction

The documented overlap neighborhood (25-40%) and SPY rebound exceptions (8%, 10%, 12%) were rerun without selecting a new optimum first.

At the central 10% SPY exception:

| Leadership overlap | 20y CAGR | Max DD |
|---:|---:|---:|
| 25% | 21.82% | -26.00% |
| 30% | 21.39% | -22.71% |
| 35% | 21.70% | -22.71% |
| 40% | 21.70% | -22.71% |

The former broad ~22.9-23.0% plateau is therefore **not reproduced**. The corrected surface separates wealth and drawdown trade-offs rather than providing the previous across-the-board improvement.

The 8% SPY exception, which was the old historical CAGR maximum, is no longer benign: at 30% overlap under the primary every-upward-transition semantics it produces approximately **21.38% CAGR / -25.82% max drawdown**. This is direct evidence that the old 8-12% stability claim depended materially on the superseded economic path.

## Recovery-gate semantics sensitivity

A second interpretation was tested because it is architecturally plausible: gate only the initial exit from zero-risk, then allow Sentinel's native 55→65→100 recovery ramp to remain authoritative.

At 30% overlap / 10% SPY exception this produced approximately:

- **22.38% 20-year CAGR**;
- **-25.98% max drawdown**.

That is a wealth-first trade-off, not a dominance result: CAGR improves materially, but maximum drawdown becomes worse than the corrected hardened control. It is reported as a semantic sensitivity, not promoted.

## What survives and what does not

### Survives

- The Sharadar dividend interpretation defect is real and economically material.
- The corrected hardened control is about **21.34% CAGR / -24.75% max drawdown**.
- Independent recovery evidence remains useful: leadership overlap is severely depressed at the 2008 and 2022 false-recovery examples.
- Requiring independent concordance can reduce drawdown without increasing transition frequency.

### Does not survive as a current claim

- **23.24% CAGR / -22.60% max drawdown** as the current Sentinel Concordance champion.
- the statement that the candidate improves all standard trailing CAGR windows;
- the former 8-12% V-rebound stability claim;
- any assertion that the exact durable-witness candidate has been rerun, because its source implementation was not retained.

## Decision

Do **not** freeze or certify the old 23.24% Sentinel Concordance result.

For current causal truth, the economically defensible reference is the corrected hardened Sentinel control at approximately **21.34% CAGR / -24.75% max drawdown**. The retained-definition leadership Concordance remains a promising drawdown-oriented research overlay at approximately **21.39% / -22.71%** under the predeclared central rule, but it is not yet a replacement because it sacrifices recent-window CAGR and the exact former durable-witness lineage cannot be reproduced.

Before any Concordance variant becomes a production version, its witness implementation must be retained as source, its semantics frozen before scoring, and the full corrected-data causal/certification suite rerun from that exact implementation.
