# Sentinel Concordance — post-dividend reconstruction and new research

**Date:** 2026-08-19  
**Status:** exploratory research evidence, not production strategy and not certification  
**Economic baseline:** Sharadar volume-domain correction + Sharadar dividend-domain correction + hardened fast-crisis sensor

## Executive conclusion

The exact scratch implementation of the former `23.24% CAGR / -22.60% max drawdown` durable-witness Concordance candidate was not retained. That old result is not reconstructed or used as a target here.

The **architecture was recoverable** from retained GitHub research: risk-off remains authoritative; risk-on should not be certified by the adaptive Wealth Core book alone; independent opportunity-set witnesses may delay re-risking; a strong SPY V-rebound can bypass a slow witness.

A fresh raw-Sharadar research harness was rebuilt on the corrected economics and had to pass two controls before any new experiment was accepted:

1. Fully corrected + hardened Sentinel reproduced exactly at **21.3433275% CAGR / -24.7499677% max drawdown / 47.901874x / 1.104704 Sharpe** over `2006-07-31..2026-07-31`.
2. The documented post-dividend leadership-overlap Concordance rule (`30% overlap`, `10% SPY rebound`, every upward transition gated) reproduced exactly at **21.3941422% / -22.7093103% / 48.304678x / 1.140868 Sharpe**.

That establishes that the reconstructed daily state tape and next-open overlay accounting match the retained corrected research semantics before extending them.

The strongest new insight is that Concordance is more useful as a **state machine** than as one threshold:

- allow Sentinel's native staged recovery to reach 55% / 65%;
- require independent evidence before restoring 100%;
- if a fully risk-on Wealth Core is in a deep strategy-specific divergence while independent leadership is also badly damaged but SPY is not in systemic decline, temporarily cap exposure at an existing staged level;
- once capped, do **not** pop immediately back to 100% when one daily trigger clears: remain latched until independent recovery evidence confirms the repair.

A deliberately simple exploratory version of that architecture reaches approximately **22.56-22.59% CAGR with -21.70% max drawdown**, depending on whether the temporary cap is 65% or 55%. Both improve all standard trailing 5/10/15/20-year windows versus the fully corrected Sentinel control in this research replay.

This is promising research, not a parameter set to freeze.

---

## Corrected economic semantics

All research in this note uses:

- liquidity: `SEP.close * SEP.volume` (equivalently raw close times raw-compatible volume);
- raw/as-traded marking and execution: `SEP.closeunadj`;
- dividend conversion: `raw_dividend_per_share = ACTIONS.value * SEP.closeunadj / SEP.close`;
- same-session corporate-action order: split first, dividend second;
- hardened fast-crisis damaged-breadth acceleration threshold: 30 percentage points;
- Sentinel allocation changes at the next open;
- BIL defensive sleeve;
- 10 bp one-way allocation-change cost.

The independent leadership witness earns causal close-to-close **price** returns using membership selected at the prior close. It does not feed ACTIONS dividend cash through another share ledger, so the dividend-domain defect is not duplicated inside the witness.

---

## What was recovered from the old Concordance architecture

The retained research established the causal idea even though the exact former durable-witness code was lost:

- Wealth Core is the only alpha engine.
- Alternative books/opportunity-set measures are sensors, not capital allocators.
- Risk reductions stay immediate.
- Risk restoration should require evidence independent from the adaptive controlled book.
- A strong broad-market V-rebound exception prevents a deliberately slow witness from missing a violent recovery.

The retained leadership witness was also reconstructable exactly: compare the established top-decile 6-to-1 momentum population with an equally sized population ranked by recent 21-session return. The reconstructed overlap matches the retained falsifiers: about **6.93% on 2008-12-23** and **8.33% on 2022-01-03**.

---

## Experiment program

More than **28,000** semantic/parameter variants were evaluated across these families after baseline validation:

1. absolute leadership-overlap recovery gates;
2. gate every upward transition vs gate only return to 100%;
3. adaptive overlap relative to its trailing distribution;
4. broad eligible-population breadth witnesses;
5. recent-leadership shadow 20/40-day return witnesses;
6. persistence rather than magnitude thresholds;
7. combinations of broad breadth, leadership shadow and SPY rebound evidence;
8. strategy-specific divergence caps while otherwise fully risk-on;
9. neighborhood perturbations of the combined state machine.

No old pre-dividend CAGR target was used as an objective.

---

## Recovery-only findings

### 1. Gating every upward transition is too blunt

The retained central leadership rule (`overlap >= 30% OR SPY r20 >= 10%`) reproduced the documented corrected result:

- CAGR: **21.3941%**
- max DD: **-22.7093%**
- multiple: **48.3047x**
- Sharpe: **1.1409**

It reduces drawdown, but delays 55%->65%->100% recovery steps that Sentinel already designed to be cautious.

### 2. Gate only the final return to 100%

Letting native Sentinel move through 55% and 65%, while requiring Concordance only for full risk, is materially better.

A leadership-overlap neighborhood around 35-45% with a 10% SPY exception produced the same historical path at approximately:

- **21.9351% CAGR**
- **-22.7093% max DD**
- **52.7974x**
- **1.1640 Sharpe**

This is an architectural result: partial recovery and full-risk certification should not necessarily use the same authority.

### 3. Independent recent-leadership shadow is stronger than overlap alone

A causal recent-leadership shadow is formed from an equally sized population selected by recent 21-session leadership, using prior-close membership. A magnitude family requiring positive r20 plus roughly +4% to +5% r40, or a strong SPY rebound, produced a broad identical-path neighborhood around:

- **22.6160% CAGR**
- **-22.7093% max DD**
- **59.0177x**
- **1.1819 Sharpe**

A cleaner version replaces the +4-5% r40 magnitude cliff with **persistence**: require `recent-shadow r20 > 0 AND r40 > 0` for seven consecutive sessions, or a strong SPY rebound. With an 11% SPY 20-session rebound exception:

- **22.4173% CAGR**
- **-22.7093% max DD**
- **57.1332x**
- **1.1734 Sharpe**

The persistence rule is lower-performing historically than the magnitude rule, but has a cleaner causal interpretation and fewer arbitrary amplitude thresholds.

---

## Forensics: what recovery Concordance fixes

Under the persistence candidate, relative performance versus corrected Sentinel improves mainly by avoiding false recoveries:

- 2008 recovery episode: roughly **+7.1% relative**;
- 2011 recovery episode: roughly **+4.4% relative**;
- 2015/16 recovery episode: roughly **+11.1% relative**;
- 2022 and 2025 recovery delays cost small amounts after eventual reconvergence.

The maximum-drawdown trough moves from **2022-09-26** in corrected Sentinel back to **2021-05-12**. Therefore recovery Concordance successfully prevents 2022 from extending the prior drawdown, but cannot reduce the remaining 2021 drawdown because the controller was already fully risk-on during that event.

That observation motivated the next derivative.

---

## Concordance derivative: latched strategy-divergence cap

The 2021 episode differs from 2008/2020 systemic panic. Wealth Core and independent momentum/leadership evidence can be badly damaged while SPY itself remains near flat or positive. That is a strategy/factor divergence rather than broad-market crisis.

A deliberately simple exploratory trigger was tested while fully risk-on:

```text
Wealth Core drawdown <= -10%
AND damaged holding breadth >= 70%
AND independent recent-leadership shadow r20 <= -8%
AND independent recent-leadership shadow r40 <= -8%
AND SPY r20 >= 0%
```

When this conjunction is true, cap Core at an existing staged exposure (55% or 65%). The cap is **latched**: return to 100% only when the same independent recovery Concordance used above clears (seven consecutive sessions with recent-shadow r20 > 0 and r40 > 0, or a strong SPY V-rebound).

### Results

| Candidate | 20y CAGR | Max DD | Multiple | Sharpe |
|---|---:|---:|---:|---:|
| Corrected+hardened Sentinel control | 21.3433% | -24.7500% | 47.9019x | 1.1047 |
| leadership 30/10, every upward move gated | 21.3941% | -22.7093% | 48.3047x | 1.1409 |
| leadership full-risk-only gate | 21.9351% | -22.7093% | 52.7974x | 1.1640 |
| recent-shadow persistence, recovery only | 22.4173% | -22.7093% | 57.1332x | 1.1734 |
| recent-shadow magnitude, recovery only | 22.6160% | -22.7093% | 59.0177x | 1.1819 |
| **persistence + divergence cap at 65%** | **22.5597%** | **-21.6958%** | **58.4776x** | **1.1971** |
| **persistence + divergence cap at 55%** | **22.5946%** | **-21.6958%** | **58.8115x** | **1.2025** |

The new drawdown trough is **2021-03-08**, versus 2022-09-26 in the corrected control.

### Standard trailing windows, 55% cap version

| Window | Control CAGR | Candidate CAGR | Control max DD | Candidate max DD |
|---|---:|---:|---:|---:|
| 5y | 26.8108% | **27.9840%** | -23.8182% | **-20.8689%** |
| 10y | 26.8685% | **27.1587%** | -24.7500% | **-21.6958%** |
| 15y | 21.5697% | **22.7085%** | -24.7500% | **-21.6958%** |
| 20y | 21.3433% | **22.5946%** | -24.7500% | **-21.6958%** |

Across 15 annual trailing-start comparisons from 2006 through 2020, this exploratory candidate had higher CAGR in **15/15** and equal-or-better maximum drawdown in **15/15**. This is still the same historical corpus and is **not out-of-sample validation**.

### Critical negative control

The divergence cap without a latched independent recovery state is bad:

- 65% cap alone: about **21.2691% CAGR / -25.6649% max DD**;
- 55% cap alone: about **21.2479% CAGR / -25.9250% max DD**.

Therefore the apparent benefit is **not** “a stop at these thresholds.” The useful hypothesis is the state machine:

> detect a rare disagreement -> reduce exposure modestly -> remain reduced until independent recovery evidence confirms repair.

---

## Neighborhood robustness

A local neighborhood around the combined state machine varied:

- recovery persistence: 5 / 7 / 10 sessions;
- SPY V-rebound exception: 10% / 11% / 12%;
- WC drawdown trigger: -8% / -10% / -12%;
- recent-shadow r20 weakness: -6% / -8% / -10%;
- recent-shadow r40 weakness: -5% / -8% / -10% / -12%;
- damaged breadth: 60% / 70% / 75%;
- SPY divergence floor: -2% / 0% / +2%.

That is **2,916** nearby combinations. **2,665 (91.4%)** improved both CAGR and maximum drawdown versus the fully corrected Sentinel control.

The neighborhood is not one identical path and contains weaker variants; this percentage is robustness evidence, not permission to optimize to the best row. The central simple rule above was intentionally selected for interpretability rather than the maximum backtested CAGR.

Both existing staged cap levels (55% and 65%) produced the same -21.70% drawdown frontier and similar long-run wealth, which further suggests that the information/state transition matters more than one exact exposure value.

---

## Interpretation and next decision

The original Concordance hypothesis survives the dividend correction, but the strongest corrected-data formulation is broader than the old recovery gate:

1. **Systemic crisis entry:** hardened Sentinel remains authoritative.
2. **Partial recovery:** native Sentinel staged 55% / 65% recovery remains authoritative.
3. **Full-risk recovery:** require an independent opportunity-set witness or unmistakable SPY V-rebound.
4. **Strategy-specific divergence:** when the alpha engine and independent leadership are both deeply damaged while SPY is not, a sparse temporary staged cap may be justified.
5. **Latch:** after that cap, only independent recovery evidence restores full risk.

This is now the highest-priority Concordance research derivative, but it must **not** be merged into production based on this search alone. It was discovered on the same historical corpus after extensive exploration. Before a production PR, freeze one simple candidate from this architecture and subject it to adversarial tests, episode holdouts / walk-forward design, perturbation of witness construction, and exact corrected-data replay from retained source.

The old `23.24%` pre-dividend result remains superseded and is not resurrected by this work.
