# Corrected Sentinel baseline — adversarial validation (no Concordance)

**Date:** 2026-08-19  
**Status:** adversarial research validation; not certification  
**Scope:** Sharadar volume-domain correction + Sharadar dividend-domain correction + hardened fast-crisis sensor. **No Sentinel Concordance logic is present in this test target.**

## Executive verdict

The fully corrected non-Concordance Sentinel baseline survives a broad adversarial review as a **credible research implementation**, with two material limitations that must remain visible:

1. the hardened fast-crisis improvement is sparse-event dependent — compared with the former 40 percentage-point fast threshold, the additional historical evidence is concentrated in 2008 and 2011, with 2008 highly load-bearing;
2. crisis protection is timing-sensitive — one to three additional sessions of execution latency materially worsens drawdown.

The corrected baseline itself reproduces exactly at:

- window: **2006-07-31 through 2026-07-31**;
- sessions: **5,032**;
- CAGR: **21.3433275%**;
- maximum drawdown: **-24.7499677%**;
- ending multiple: **47.901874x**;
- daily Sharpe: **1.1047035**;
- maximum-drawdown trough: **2022-09-26**.

For comparison, the immutable corrected Wealth Core shadow over the same window is approximately **18.1877% CAGR / -43.9160% max drawdown / 28.2800x / 0.910 Sharpe**.

This review does **not** use Concordance or any of the post-dividend Concordance research candidates.

---

## Economic semantics frozen for this validation

The raw-Sharadar replay used the corrected economic interpretation:

- liquidity: `SEP.close * SEP.volume`, equivalently `closeunadj * raw_compatible_volume`;
- raw/as-traded marking and execution: `SEP.closeunadj`;
- cash dividends: `ACTIONS.value * SEP.closeunadj / SEP.close`;
- same-session ordering: split first, dividend second;
- next-open Sentinel allocation changes;
- BIL defensive sleeve;
- 10 bp one-way Sentinel allocation-change cost;
- hardened fast-entry damaged-breadth acceleration threshold: **30 percentage points**.

The baseline reconstruction had to reproduce the retained corrected headline before adversarial tests were accepted. A controller-only replay from the retained daily shadow then reproduced the allocation path **exactly** and the NAV to a maximum absolute error below `2e-13`.

---

## 1. Causality / prefix invariance

The full raw replay through 2026 was compared with an independently terminated replay ending in 2016.

Shared prefix:

- **2,518 sessions** through **2016-07-29**;
- allocation path: **bit-for-bit identical**;
- NAV maximum absolute difference: **0.0**;
- Wealth Core shadow-equity maximum absolute difference: **0.0**;
- no numeric or missing-value mismatch in the retained daily state columns.

This is strong evidence that later SEP rows are not leaking backward through the reconstructed strategy mechanics.

It is not a substitute for the still-pending SEC point-in-time filing correction or for a historical-vintage Sharadar dataset; it proves prefix invariance under the accepted modern reconstructed Sharadar corpus.

---

## 2. Hardened fast-trigger threshold sweep

Only the five-session damaged-breadth acceleration threshold was changed. Everything else remained frozen.

| Minimum 5-session damaged-breadth acceleration | 20y CAGR | Max DD | Interpretation |
|---:|---:|---:|---|
| 20–23 pp | 19.92% | -29.03% | over-sensitive; extra false positives |
| 24 pp | 20.31% | -29.03% | still over-sensitive |
| 25–28 pp | 20.99% | -29.03% | improved, but inferior to central plateau |
| **29–37 pp** | **21.3433%** | **-24.7500%** | **identical allocation/NAV path** |
| 38–41 pp | 19.5407% | -40.2563% | misses the critical 2008 fast entry |
| 42–44 pp | 19.6322% | -40.2563% | same drawdown failure |
| 45 pp | 19.9674% | -40.2563% | same drawdown failure |

The central 30 pp value is therefore **not a one-point optimum**. It sits inside an eight-percentage-point identical-path plateau from 29 through 37 pp.

However, the plateau has a real upper cliff. On **2008-07-02**, corrected Wealth Core had approximately:

- shadow drawdown: **-12.45%**;
- damaged breadth: **91.30%**;
- green breadth: **0%**;
- 5-session return: **-8.40%**;
- 10-session return: **-12.45%**;
- damaged-breadth delta5: **+37.14 pp**;
- SPY r20: **-8.11%**;
- SPY volatility acceleration: **+6.41%**.

A 30 pp threshold fires and is effective at the 2008-07-03 open. A 38–40 pp threshold does not, so the slow path does not reach 0% Core until 2008-10-06.

The second historical event newly captured below 40 pp is 2011: its pre-entry damaged-breadth acceleration was approximately **37.5 pp**. Fast episodes in 2015, 2018, 2020 and 2025 already exceeded 40 pp; 2010 and 2022 entered through the slower stress path.

Consequently, **the 30-vs-40 hardening has no allocation-path effect from 2012 onward**. This is an important limitation: the hardening has two additional historical trigger witnesses (2008 and 2011), not dozens of independent events.

---

## 3. Other fast-sensor threshold perturbations

One threshold at a time was perturbed around the corrected baseline.

### Stable neighborhoods

These ranges produced the exact same 21.3433% / -24.7500% path:

- green-breadth maximum: **15% to 25%**;
- SPY 20-day confirmation threshold: **-3% to +1%**;
- short-loss 5-day threshold: **-4% to -6%**;
- short-loss 10-day threshold: **-7% to -9%**;
- SPY volatility-acceleration threshold: **2% to 6%**;
- damaged-breadth minimum: **82.5% to 85%**.

### Sensitivities

- damaged-breadth minimum 80%: **20.785% CAGR / -30.845% MDD**;
- damaged-breadth minimum 87.5–90%: **20.426% / -27.684%**;
- removing the volatility requirement entirely (`0%`) adds a harmful episode: **20.703% / -24.750%**;
- raising volatility acceleration to 8% happens to remove episodes and yields ~21.47% CAGR with the same MDD, but this is a post-hoc historical result and is **not** a recommendation to change the rule.

The detector is therefore not generally dependent on every exact conjunct, but breadth and timing remain meaningful state boundaries.

---

## 4. Older Sentinel controller perturbations

The adversarial review also perturbed pre-existing Sentinel slow/recovery/ramp parameters so this was not merely a test of yesterday's 30 pp change.

### Essentially invariant under tested perturbation

- slow-entry duration: **25 / 30 / 35 sessions** — identical path;
- slow-entry r40 threshold: **-2% / -3% / -4%** — identical path;
- slow-entry maximum green breadth: **20% / 25% / 30%** — identical path;
- fast-state minimum hold: **8 / 10 / 12 sessions** — identical path;
- recovery green-breadth minimum: **15% / 20% / 25%** — negligible or zero effect;
- recovery damaged-breadth maximum 55–65% — small effects only;
- ramp fragile threshold around `-1% / 0 / +1%` five-session r40 delta — small effect;
- 55→65 and 65→100 ramp confirmations varied from 7 to 13 sessions — less than ~0.05 pp CAGR and ~0.22 pp MDD movement in this sweep.

### Meaningful but non-catastrophic sensitivities

- ordinary-stress drawdown threshold -14% instead of -15.5%: CAGR falls about **0.79 pp** while MDD is unchanged;
- slow-entry damaged breadth 70%: CAGR falls about **0.55 pp**;
- slow-entry damaged breadth 80%: MDD worsens about **0.82 pp**;
- requiring recovery `r20 > +1%` instead of merely `> 0`: CAGR falls about **0.48 pp**, MDD worsens about **1.98 pp**;
- extending slow-recovery confirmation from 6 to 8 observations: CAGR falls about **0.35 pp**.

No tested pre-existing controller perturbation recreated the 2008 ~-40% failure except moving the fast-crisis entry requirements back across the crisis-detection cliff.

---

## 5. Execution-latency attack

The baseline assumes the close decision is implemented at the next session's open. To test dependence on perfect timing, effective allocation transitions were delayed by additional sessions.

| Added delay | What is delayed | CAGR | Max DD |
|---:|---|---:|---:|
| 0 | baseline | **21.3433%** | **-24.7500%** |
| +1 session | all transitions | 20.7515% | -26.4776% |
| +1 session | risk reductions only | 20.7561% | -25.5687% |
| +2 sessions | all transitions | 21.0586% | -27.3259% |
| +2 sessions | risk reductions only | 21.1080% | -27.5393% |
| +3 sessions | all transitions | 20.9287% | -29.4712% |
| +3 sessions | risk reductions only | 21.3144% | -28.7483% |

This is a genuine operational sensitivity. The system remains profitable under these artificial delays, but a crisis decision that cannot reach the broker for several sessions loses a material part of Sentinel's drawdown protection.

This result strengthens, rather than weakens, the need for the separate Alpaca/reconciliation/outage protections: stale or unexecuted risk-off authority is financially material.

---

## 6. Defensive-episode ablation

Each historical defensive episode was independently disabled by forcing 100% Core exposure over that interval while leaving all other episodes unchanged. This is an attribution test, not an alternative strategy.

| Episode | Defensive interval | CAGR if removed | MDD if removed | Effect |
|---|---|---:|---:|---|
| 2008 | 2008-07-03 → 2008-12-23 | **19.54%** | **-43.92%** | extremely load-bearing |
| 2010 | 2010-07-06 → 2010-09-15 | 21.81% | -24.75% | historically cost CAGR |
| 2011 | 2011-08-05 → 2011-09-08 | 21.13% | -24.75% | modestly beneficial |
| 2015 | 2015-08-26 → 2015-10-29 | 21.47% | -24.75% | historically cost CAGR |
| 2018/19 | 2018-10-12 → 2019-01-24 | 20.67% | -30.31% | materially beneficial |
| 2020 | 2020-02-28 → 2020-04-21 | 20.36% | -28.68% | materially beneficial |
| 2022 | 2022-06-14 → 2022-09-01 | 20.91% | -30.00% | materially beneficial |
| 2025 | 2025-04-08 → 2025-05-06 | 21.68% | -24.75% | historically cost CAGR |

This is healthy negative evidence: Sentinel is not magically correct on every risk-off episode. Some episodes acted as paid insurance and reduced historical CAGR. The long-run improvement is driven by the avoided losses in a smaller number of genuinely damaging regimes.

The **2008 episode is the single largest historical contributor** to the drawdown advantage. This must remain explicit when judging the strength of the fast-trigger evidence.

---

## 7. Disjoint temporal blocks

Nested trailing windows can hide regime dependence, so the history was divided into four approximately five-year non-overlapping blocks and compared with the corrected immutable Wealth Core shadow.

| Block | Sentinel CAGR | Wealth Core CAGR | Sentinel MDD | Wealth Core MDD |
|---|---:|---:|---:|---:|
| 2006-07-31 → 2011-07-31 | **20.73%** | 15.48% | **-24.33%** | -43.92% |
| 2011-07-31 → 2016-07-31 | **11.62%** | 11.29% | -21.37% | **-19.70%** |
| 2016-07-31 → 2021-07-31 | **27.19%** | 20.41% | **-22.71%** | -30.31% |
| 2021-07-31 → 2026-07-31 | **26.81%** | 26.40% | **-23.82%** | -29.14% |

Sentinel improved CAGR in all four blocks. It improved maximum drawdown in three of four. The 2011–2016 block is an important falsifier against any claim that the overlay always reduces drawdown: in that block it slightly **worsened** MDD while adding only a small CAGR benefit.

These blocks are robustness evidence, not untouched holdouts: the strategy and its recent hardening have been examined against this historical corpus.

---

## 8. Paired block-bootstrap return-sequence stress test

The realized daily returns of corrected Sentinel and its immutable Wealth Core shadow were resampled in paired contiguous blocks. This does **not** recompute the controller on synthetic histories; it asks whether the observed Sentinel advantage is unusually dependent on the exact ordering of its realized daily return contributions.

3,000 resamples per block size:

| Block length | P(Sentinel ending wealth > WC) | P(Sentinel MDD better) | P(both) |
|---:|---:|---:|---:|
| 5 sessions | 95.5% | 86.0% | 83.3% |
| 20 sessions | 97.0% | 89.2% | 87.2% |
| 60 sessions | 95.5% | 93.0% | 90.1% |
| 120 sessions | 95.4% | 96.4% | 92.9% |

The 5th percentile of bootstrapped log relative ending wealth remains positive for all four block lengths tested.

This supports the realized return contribution but should not be described as synthetic-controller Monte Carlo or out-of-sample validation.

---

## 9. Defensive sleeve and transition-cost attacks

### Remove BIL yield

Replacing BIL with zero-return cash while keeping the same allocations produces approximately:

- **21.2244% CAGR**;
- **-24.9208% MDD**.

Versus BIL at 21.3433% / -24.7500%, only about **0.12 pp CAGR** is attributable to the historical defensive-sleeve yield in this counterfactual. The economic value is overwhelmingly loss avoidance, not Treasury carry.

### Increase Sentinel allocation-transition friction

This changes only the scalar overlay transition cost, not Wealth Core's stock-level trading cost.

| One-way allocation-change cost | CAGR | MDD |
|---:|---:|---:|
| 0 bp | 21.4405% | -24.60% |
| **10 bp baseline** | **21.3433%** | **-24.75%** |
| 25 bp | 21.1976% | -24.98% |
| 50 bp | 20.9546% | -25.35% |
| 100 bp | 20.4683% | -26.10% |

The conclusion survives extremely conservative overlay friction because transitions are sparse.

---

## 10. Combined local-parameter perturbation

As a deliberately harsher interaction test, 120 random combinations were drawn from a broad local box around the fast sensor:

- delta5: 28–37 pp;
- damaged breadth: 82–88%;
- green breadth maximum: 15–25%;
- SPY volatility acceleration: 1–7%;
- SPY confirmation r20: -3% to +1%;
- r5 loss threshold: -6% to -4%;
- r10 loss threshold: -9% to -7%.

Results:

- **45.8%** reproduced the baseline path exactly;
- **87.5%** stayed within 1 pp of baseline CAGR and no more than 5 pp worse MDD;
- **5%** fell below -35% MDD.

This is the strongest warning from the threshold tests: while individual central thresholds often have broad plateaus, simultaneous perturbations can move the detector into materially different crisis classifications. The detector should therefore be treated as a conjunctive state definition, not as seven independently harmless knobs.

---

## Overall conclusion

### What passes

The corrected non-Concordance Sentinel baseline is supported by several independent checks:

- exact raw-Sharadar reproduction of the corrected economic headline;
- exact prefix invariance through a truncated 2016 replay;
- a broad **29–37 pp** identical-path neighborhood around the new 30 pp fast threshold;
- many pre-existing controller thresholds are locally invariant or only mildly sensitive;
- positive CAGR in every disjoint five-year block tested;
- higher CAGR than corrected Wealth Core in all four disjoint blocks and better MDD in three of four;
- paired block-bootstrap return-sequence tests strongly favor Sentinel over Wealth Core;
- the benefit remains with zero-yield cash and under much larger overlay transaction costs.

### What does not pass as a strong claim

Do **not** say that every part of the controller has broad independent historical validation.

The fast-trigger hardening is **sparse-event evidence**:

- it newly changes the outcome of 2008 and 2011 relative to the old 40 pp threshold;
- from 2012 onward, 30 pp and 40 pp produce the same allocation path;
- 2008 is extremely load-bearing to the 20-year drawdown result.

Also, the crisis overlay assumes timely next-open execution. Added execution delay materially worsens drawdown.

### Verdict

**PASS as the current economically defensible non-Concordance Sentinel research baseline.**

That means the **21.3433% CAGR / -24.7500% MDD** result remains a reasonable current historical reference after adversarial testing. It does **not** mean the strategy is causally/certifiably final:

- the SEC point-in-time filing correction still remains;
- there is no genuinely untouched historical holdout after the amount of research already performed on 2006–2026;
- production code consolidation is still in progress across the Sharadar PRs;
- the fast hardening should be regarded as a sparse systemic-crisis robustness change whose main independent witnesses are 2008 and 2011.

No Concordance result or Concordance signal was used in this validation.