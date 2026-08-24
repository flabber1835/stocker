# Corrected point-in-time metadata A/B — Simplified Concordance LD-RC

**Status:** research evidence; no production/main strategy change.

## Objective

Measure the economic effect of removing avoidable present-day Sharadar metadata from the authoritative corrected-volume Simplified Concordance LD-RC lineage. The A control must first reproduce the retained 22.6302156206% 20-year CAGR fingerprint exactly. Issue #241 is retracted because its nominal current-sector control failed that gate.

## Experimental definitions

**A — Current Sharadar metadata control.** Authoritative 30pp Simplified Concordance LD-RC, corrected price/liquidity/dividend/action semantics, current Sharadar sector grouping, current category gate, close decision -> next executable open, BIL defensive sleeve, and 10bp one-way overlay-change cost.

**B — Best-effort causal/PIT metadata variant.** The economic strategy is otherwise frozen, with these metadata changes only:

- `category`: removed from eligibility rather than projecting the current category backward. Raw-corpus replay changes 0 Wealth Core buys, 0 NAV sessions, 0 native-allocation sessions and 0 final-allocation sessions. It changes only the zero-capital recent-leadership witness values; B uses that category-free witness.
- `exchange`: remains inert because it is not part of the recovered/certified Wealth Core rule.
- issuer family / `relatedtickers`: use SEC Form 3/4/5 CIK evidence strictly before the decision session with permaticker fallback. PR #208 proved zero economic delta. A category-free interaction falsifier that removed all cross-security issuer blocking after 2006 found only one security-choice divergence: GOOGL on the 2025-12-22 decision. SEC evidence from 2025-12-18 causally confirms GOOG/GOOGL share CIK `0001652044`, so actual PIT correctly blocks GOOGL and restores the baseline ROIV choice.
- `sector`: latest SEC Financial Statement Data Set SIC evidence strictly before each decision session, mapped through a frozen FF12 SIC classification. No future SIC backfill. Where no causal SIC is available, the security gets a singleton unknown peer, so unavailable evidence cannot manufacture cross-security sector stress.

This is **not** a byte-identical reconstruction of historical Sharadar sector taxonomy. It is the most causal replacement definition supported by the evidence currently assembled.

## Results

| Window | Current Sharadar CAGR | Current Sharpe | Current Max DD | Best-effort PIT CAGR | PIT Sharpe | PIT Max DD | SPY CAGR | SPY Sharpe | SPY Max DD |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 5y | 27.74% | 1.324 | -20.87% | 28.89% | 1.357 | -21.69% | 12.76% | 0.788 | -24.50% |
| 10y | 27.23% | 1.319 | -21.70% | 25.88% | 1.248 | -27.68% | 14.98% | 0.870 | -33.70% |
| 15y | 22.73% | 1.238 | -21.70% | 21.41% | 1.170 | -27.68% | 14.40% | 0.871 | -33.70% |
| 20y | 22.63% | 1.214 | -21.70% | 21.64% | 1.164 | -27.68% | 11.26% | 0.647 | -55.20% |

Standard windows are the retained LD-RC windows ending 2026-07-31: 5y starts 2021-07-30, 10y 2016-07-29, 15y 2011-07-29, and 20y 2006-07-31. Sharpe is daily arithmetic mean / daily standard deviation * sqrt(252), zero risk-free, matching the retained strategy convention. SPY uses Sharadar SFP `closeadj` (total-return domain) on the same sessions.

## Control and causality gates

- A reproduces the authoritative 20-year fingerprint exactly: **22.6302156206% CAGR / 1.213813871 Sharpe / -21.6958215% max DD / 59.1542869x**.
- Category-free replay: **0 changed Wealth Core buys, 0 changed NAV sessions, 0 changed native-allocation sessions, 0 changed final-allocation sessions**. Witness r20/r40 differ on 2,239/2,504 sessions, but substituting the category-free witness into B changes **0** B allocation or NAV sessions.
- SEC-PIT issuer authority has zero economic delta after the causal 2006 boundary; the only permissive-issuer counterexample is Alphabet, and actual SEC CIK evidence blocks it causally.
- Held-row Form 3/4/5 CIK coverage: **80.1%** (92,123/114,961).
- Held-row causal SIC coverage: **67.0%** (77,045/114,961). Missing SIC is singleton/no peer contagion, never current-sector fallback.
- Sector replacement changes damaged breadth on **1,480** sessions, native allocation on **172**, final allocation on **148**, and the raw fast trigger on only **5** sessions.

### Fast-trigger differences

| Session | A damaged | B damaged | A fast | B fast |
|---|---:|---:|:---:|:---:|
| 2008-07-08 | 100.00% | 95.24% | True | False |
| 2010-05-07 | 88.00% | 80.00% | True | False |
| 2018-10-11 | 85.71% | 80.95% | True | False |
| 2021-12-03 | 80.00% | 85.00% | False | True |
| 2025-04-07 | 91.67% | 83.33% | True | False |

The first final-allocation divergence is **2011-10-31**. Changed allocation episodes are 2011-10-31..2012-01-26, 2018-10-12..2018-12-19, 2021-12-06..2022-01-03, and 2025-04-08..2025-05-07.

## SEC SIC provenance

- Upstream: U.S. SEC Financial Statement Data Sets `submissions` table, 2009Q2 through 2026Q1.
- Transport: public `erlenbusch/sec-edgar` DuckDB mirror. Direct SEC downloads returned HTTP 403 to GitHub-hosted runners; the mirror is transport only.
- Cross-check: 2011Q2 yields exactly **1,695 unique dated CIK/SIC observations**, matching the prior direct-SEC reconstruction fingerprint.
- SIC tape rows: **423,766**.
- SIC tape SHA-256: `cee14e068e0793bcaaf668ffe3bbbd09c5d2107699ecd08b71371641a3efd8b7`.
- FF12 follows Kenneth French 12-industry SIC ranges and is frozen in the replay.

## Interpretation

The corrected experiment does **not** reproduce the retracted #241 conclusion. The 22.63% control is sound. Moving as far toward causal metadata as the currently assembled evidence allows lowers 20-year CAGR by about **0.99 percentage points/year** (22.63% -> 21.64%), lowers Sharpe by about **0.05**, and worsens max drawdown by about **5.98 percentage points**. The most recent 5-year window actually improves. The economic effect is concentrated in a handful of threshold-sensitive controller episodes, not a broad disappearance of Wealth Core stock-selection alpha.

The PIT result is a **causal best-effort research variant**, not an exact historical Sharadar-sector reconstruction and not an automatic production strategy change. No change to `main` is authorized by this report.

## Artifact hashes

- control_daily: `75877495da8fa2ba82ea96a15e3c59536162e944d60da0e8ea0e04f3966859a4`
- category_free_daily: `3a99a70625c7b769981b5f6e462d2eeffc775f1b07b7eaeba699c5d0fb1bc147`
- pit_daily: `ce9c801e5e44f3dd40273cf9ef4412f1f6009ff5f0d6daa23f339f1e3c07fe7e`
- metrics: `a9fb403eff8a3feb42931a5c13674064ad85d673caee32b4ed46481d7fe630f8`
- session_diff: `9716c430c2fe9675863c901df2bbc8e980de93fa20903cfaac0f88500b6f36a9`
- held_pit_sector_evidence: `7a89075759c6dc093f4e34a7f21961e2bcf17e0ce5cc0549614a96742fc7630d`
- sec_sic: `cee14e068e0793bcaaf668ffe3bbbd09c5d2107699ecd08b71371641a3efd8b7`
- sec_form345_observations: `61287dcab9185136deedfb8f5f64c391751980a761b748e6bde848366ce65cd0`
- held_sector_diag: `d85f7e8bdf82ff4c0e6a4b14abab7088d67327d25cb987c98205272b62d2870e`
