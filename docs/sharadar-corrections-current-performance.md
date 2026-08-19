# Sharadar corrections and current Sentinel performance

**Date:** 2026-08-19  
**Status:** current causal-performance summary; not certification  
**Scope:** material Sharadar interpretation defects found and corrected during the 2026-08-18/19 review, their measured performance impact, and the remaining SEC-filings adjustment.

## Executive summary

Two material Sharadar economic-domain interpretation defects were found in this review sequence:

1. **Volume-domain defect** — Sharadar SEP `volume` is split-adjusted, but Sentinel/Wealth Core had combined it with the raw/as-traded `closeunadj` price when calculating dollar liquidity. That mixed two split domains and distorted daily-dollar-volume / ADV eligibility, which changes the eligible cross-section and therefore stock selection, trades, portfolio breadth, and Sentinel regime evidence.
2. **Dividend-domain defect** — Sharadar ACTIONS dividend `value` is stated on Sharadar's current split-adjusted share basis, while Wealth Core carries the historical raw/as-traded number of shares. Applying ACTIONS `value` directly to historical raw shares gives the wrong cash distribution whenever later splits changed the share basis.

Both interpretation defects have now been corrected in the issue-185 Sharadar-correctness work. The dividend repair is stacked in PR #188.

The current best 20-year historical result with **both the volume and dividend corrections applied** is:

- **CAGR: 21.3433%**
- **maximum drawdown: -24.7500%**
- **ending wealth multiple: 47.9019x**
- **daily Sharpe: approximately 1.105**
- **window: 2006-07-31 through 2026-07-31**

For intuition, a 47.9019x ending multiple means `$100,000` becomes approximately `$4.79 million` over the measured window before taxes and any assumptions not included in the historical harness.

This number should currently be treated as the economically defensible Sentinel historical reference **before the separate SEC-filings adjustment is incorporated**.

## 1. Volume-domain defect

### What Sharadar provides

Sharadar SEP has distinct economic domains:

- `close`: split-adjusted, dividend-unadjusted;
- `closeunadj`: raw/as-traded price;
- `volume`: split-adjusted volume.

### Defect

The prior path effectively used:

```
closeunadj * volume
```

That is dimensionally inconsistent because `closeunadj` is in the raw/as-traded price domain while `volume` is in the split-adjusted share domain.

A split could therefore mechanically change measured dollar liquidity even when the actual economics had not changed. Because Wealth Core uses liquidity floors and ADV in eligibility, the defect could change which securities were available to the strategy.

### Correction

The corrected liquidity invariant is either:

```
SEP.close * SEP.volume
```

or, equivalently after converting the source volume to a raw-compatible share count:

```
raw_volume = reported_volume * adjusted_close / raw_close
raw_close * raw_volume == adjusted_close * reported_volume
```

The issue-185 work makes the source-boundary conversion explicit so downstream code carries one canonical raw-compatible volume domain.

### Historical effect

The original frozen-Sentinel historical reference was approximately:

- **22.09% CAGR**
- **-21.96% maximum drawdown**
- **54.20x ending multiple**

After correcting the Sharadar liquidity interpretation, the frozen controller exposed a serious 2008 regime-detection weakness. Hardening the fast-crisis detector repaired most of that controller-specific deterioration.

With corrected liquidity plus the hardened fast-crisis sensor, but before the dividend-domain correction, the research result was approximately:

- **22.02% CAGR**
- **-24.02% maximum drawdown**
- **53.55x ending multiple**

That result is now superseded as a final economic performance claim because its dividend cash still used the wrong share-domain interpretation.

## 2. Dividend-domain defect

### Defect

Sharadar ACTIONS dividend `value` is on the vendor's current split-adjusted share basis. Wealth Core's historical ledger owns the number of shares that actually existed at the historical ex-date.

The old code passed ACTIONS `value` directly into that historical raw-share ledger. This is wrong whenever a later split changed the current share basis.

### Correction

On the dividend's effective SEP row:

```
raw_dividend_per_share = ACTIONS.value * SEP.closeunadj / SEP.close
```

The same helper is now used by both Sentinel feed normalization and the canonical backtester replay, so live and historical paths share the same interpretation.

A positive dividend that cannot be converted because one of the required price domains is missing fails closed rather than guessing.

The engine's same-session economic order remains:

1. apply split/share-count transformation;
2. accrue dividend entitlement;
3. process later session events according to the existing Wealth Core order.

### Concrete validation

AAPL provides a clear historical witness:

- Sharadar ACTIONS on 2014-08-07 reports dividend `value = 0.1175`;
- the corresponding historical SEP row has approximately `closeunadj / close = 4`;
- `0.1175 * 4 = $0.47` per historical share, matching the actual historical cash dividend basis.

An older AAPL distribution with a cumulative later split factor of 28 converts the same current-basis `0.1175` to `$3.29` per historical share.

The previously observed DRYS pathological dividend also becomes economically sane under this conversion rather than creating a fictitious portfolio explosion.

## 3. Combined corrected performance

The important comparison is therefore:

| Historical state | 20y CAGR | Max drawdown | Ending multiple | Status |
|---|---:|---:|---:|---|
| Old frozen Sentinel reference | ~22.09% | -21.96% | 54.20x | superseded |
| Volume fixed + hardened Sentinel, dividend still wrong | ~22.02% | -24.02% | 53.55x | superseded |
| **Volume fixed + dividend fixed + hardened Sentinel** | **21.3433%** | **-24.7500%** | **47.9019x** | **current reference** |

The final row is the one to use when discussing Sentinel historical performance under the corrected Sharadar economic interpretation.

The corrected 21.34% / -24.75% result is additionally supported by an independent action-normalized research path that had previously produced approximately the same 21.34% CAGR / -24.75% maximum drawdown. The agreement between two separately constructed paths is strong evidence that the correction is internally coherent rather than a one-off backtest artifact.

## 4. Consequence for Sentinel Concordance

The previously reported Sentinel Concordance research champion of approximately:

- **23.24% CAGR**
- **-22.60% maximum drawdown**

was generated before the dividend-domain interpretation was corrected. It must therefore **not** be treated as a current economic performance claim.

The exact original single durable-independent-witness scratch implementation was not retained, so that specific 23.24% experiment cannot honestly be rerun from identical source lineage.

A reproducible retained-definition leadership-overlap Concordance rerun on the corrected economics produced, under the predeclared central 30% overlap / 10% SPY-rebound rule:

- **21.3941% 20-year CAGR**
- **-22.7093% maximum drawdown**
- **48.3047x ending multiple**
- **daily Sharpe approximately 1.141**

That remains interesting as a drawdown-oriented overlay, but it is not a clean replacement champion because it slightly reduces trailing 5-year and 10-year CAGR relative to the corrected hardened control.

For current causal truth, the safer reference remains the corrected hardened Sentinel result of **21.3433% CAGR / -24.7500% maximum drawdown** until a Concordance implementation is retained, frozen before scoring, and rerun/certified on the corrected economic path.

## 5. One separate correction still remains: SEC filings

The current 21.3433% result includes both material Sharadar corrections described above:

- corrected volume/liquidity domain;
- corrected dividend/share domain.

It **does not yet include the separate SEC-filings historical correction** identified earlier.

That SEC-filings issue is not another Sharadar price/action-domain bug. It is a separate historical-input / point-in-time-data correction and still needs to be incorporated into the exact historical simulation.

Therefore the current causal-truth sequence is:

```
old historical result
    -> Sharadar volume correction
    -> Sentinel fast-crisis hardening required by corrected population
    -> Sharadar dividend correction
    -> CURRENT REFERENCE: 21.3433% CAGR / -24.7500% max DD
    -> SEC-filings correction still to be incorporated
    -> rerun standard historical windows
    -> new best historical causal-performance estimate
```

Until that SEC-filings rerun is complete, the 21.3433% result should be described as the **best current Sharadar-corrected historical estimate**, not the final fully corrected Sentinel historical truth.

## 6. Required interpretation going forward

The following historical headline numbers are superseded for current economic claims:

- the old ~22.09% frozen-Sentinel reference;
- the ~22.02% volume-corrected/hardened result with old dividend semantics;
- the old 23.24% Sentinel Concordance champion.

The current reference is:

> **Sentinel, corrected Sharadar volume + corrected Sharadar dividends, hardened controller: 21.3433% CAGR / -24.7500% maximum drawdown over 2006-07-31 through 2026-07-31.**

The next required performance update is to incorporate the SEC-filings correction and rerun the same standard 5-, 10-, 15-, and 20-year windows before adopting a new final historical headline.
