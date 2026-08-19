# Sentinel Concordance — adversarial and pseudo-holdout validation

**Date:** 2026-08-19  
**Status:** research validation, not production certification  
**Frozen candidate under test:** clean post-dividend Concordance derivative from issue #189 / `docs/sentinel-concordance-post-dividend-research-v2.md`

## Candidate frozen before validation

No parameters in this document are selected from the validation results.

The frozen architecture is:

1. corrected Sharadar economics: split-compatible volume and dividend share-domain conversion;
2. hardened Sentinel fast-crisis detector;
3. native Sentinel partial recovery may proceed through 55% / 65%;
4. ordinary restoration to 100% requires independent recent-leadership recovery evidence: recent-shadow `r20 > 0` and `r40 > 0` for 7 consecutive sessions, with an 11% SPY 20-session V-rebound exception;
5. while fully risk-on, enter a strategy-divergence state when:
   - Wealth Core drawdown <= -10%;
   - damaged holding breadth >= 70%;
   - independent recent-leadership shadow r20 <= -8%;
   - independent recent-leadership shadow r40 <= -8%;
   - SPY r20 >= 0%;
6. cap Core exposure at 55%;
7. latch the reduced state until the same independent recovery rule clears it.

The purpose of this phase is to try to falsify that architecture, not improve its backtest.

## Baseline and reconstruction gates

The reconstructed raw-Sharadar harness had already passed two mandatory controls before candidate research:

- corrected volume + corrected dividend + hardened Sentinel: **21.3433275% CAGR / -24.7499677% max drawdown / 47.901874x / ~1.10470 Sharpe**;
- retained post-dividend leadership Concordance control (30% overlap / 10% SPY exception): **21.394142% CAGR / -22.709310% max drawdown / 48.3047x / ~1.14087 Sharpe**.

The frozen candidate is approximately **22.5946% CAGR / -21.6958% max drawdown / 58.8115x / ~1.2025 Sharpe** over the same 2006-07-31..2026-07-31 window.

Relative ending wealth versus corrected Sentinel is about **+22.8%** over the 20-year window.

## Critical holdout limitation

There is **no true untouched historical holdout left inside the 2006-2026 Sharadar corpus** for this candidate.

The architecture was discovered after extensive exploration over the full period. Therefore any split of those same dates is contaminated by research knowledge and must be called a **pseudo-holdout / temporal robustness test**, not out-of-sample evidence.

True holdout evidence now requires either:

- future sessions accumulated after the architecture is frozen; or
- a genuinely independent, previously unused data corpus whose semantics can be reconciled to the same strategy inputs.

This limitation is material and must not be hidden by calling a later date range "OOS" after the fact.

## Adversarial result 1 — temporal robustness is broad but not universal

The already-retained trailing-window results for the frozen 55% candidate are:

| Window | Corrected Sentinel CAGR | Candidate CAGR | Sentinel MDD | Candidate MDD |
|---|---:|---:|---:|---:|
| 5y | 26.8108% | **27.9840%** | -23.8182% | **-20.8689%** |
| 10y | 26.8685% | **27.1587%** | -24.7500% | **-21.6958%** |
| 15y | 21.5697% | **22.7085%** | -24.7500% | **-21.6958%** |
| 20y | 21.3433% | **22.5946%** | -24.7500% | **-21.6958%** |

Across 15 annual starting points from 2006 through 2020, the candidate had higher CAGR in **15/15** and equal-or-better max drawdown in **15/15**. This is strong temporal robustness evidence but remains in-sample.

A disjoint-block decomposition implied by the nested 5/10/15/20-year trailing returns gives a more adversarial picture. Approximate five-year block CAGRs are:

| Approximate historical block | Corrected Sentinel | Frozen candidate | Result |
|---|---:|---:|---|
| oldest 5y slice of 20y window | ~20.67% | **~22.25%** | candidate wins |
| next 5y slice | ~11.63% | **~14.27%** | candidate wins |
| next 5y slice | **~26.93%** | ~26.34% | candidate loses |
| latest 5y slice | 26.81% | **27.98%** | candidate wins |

These block values are algebraically derived from the retained nested trailing CAGRs rather than a fresh daily replay, so they are approximate. The important result is qualitative: **the candidate does not win every subperiod**. One strong five-year block favors corrected Sentinel. That is healthier evidence than a universal historical win claim and argues that Concordance is an episodic risk-control improvement, not a free-return overlay.

## Adversarial result 2 — parameter perturbation is not a cliff

Before this validation phase, a deliberately broad local neighborhood around the combined state machine varied:

- recovery persistence: 5 / 7 / 10 sessions;
- SPY rebound exception: 10% / 11% / 12%;
- WC drawdown trigger: -8% / -10% / -12%;
- recent-shadow r20 weakness: -6% / -8% / -10%;
- recent-shadow r40 weakness: -5% / -8% / -10% / -12%;
- damaged breadth: 60% / 70% / 75%;
- SPY divergence floor: -2% / 0% / +2%.

Of **2,916** nearby combinations, **2,665 (91.4%)** beat corrected Sentinel on both 20-year CAGR and max drawdown.

The 55% and 65% cap variants also produced the same ~-21.70% drawdown frontier and nearly identical long-run CAGR (22.59% vs 22.56%).

This argues against the candidate depending on one exact decimal threshold or exposure setting.

## Adversarial result 3 — component ablation falsifies the naive explanation

A crucial negative control is the strategy-divergence cap without the latched independent recovery state:

- 65% cap alone: **~21.2691% CAGR / -25.6649% MDD**;
- 55% cap alone: **~21.2479% CAGR / -25.9250% MDD**.

Both are worse than corrected Sentinel.

By contrast:

- independent recovery persistence alone: **~22.4173% / -22.7093%**;
- persistence + latched 55% divergence state: **~22.5946% / -21.6958%**.

Therefore the result is not explained by "a good stop-loss threshold." The useful hypothesis is specifically the state machine:

> rare strategy/opportunity-set disagreement -> modest de-risking -> remain reduced until an independent witness confirms repair.

This ablation is strong causal evidence for the latch/recovery architecture and evidence against simply adding another drawdown cap.

## Adversarial result 4 — witness construction perturbation

Two materially different independent recovery formulations both improve the corrected baseline:

- clean persistence witness (`r20 > 0 AND r40 > 0` for seven sessions): **~22.42% CAGR / -22.71% MDD**;
- magnitude-oriented recent-shadow witness: **~22.62% CAGR / -22.71% MDD**.

Leadership-overlap full-risk-only gating also improves the corrected baseline to about **21.94% / -22.71%**.

The exact CAGR depends on witness semantics, but the direction survives across overlap, persistence, and magnitude formulations: independent evidence before full-risk restoration improves the corrected historical path.

This supports the architecture more strongly than any one witness threshold.

## Adversarial result 5 — episode concentration and regime differences

The retained forensic decomposition shows recovery Concordance gains are sparse and regime-specific rather than continuous:

- 2008 false recovery: roughly +7.1% relative contribution;
- 2011 recovery: roughly +4.4%;
- 2015/16 recovery: roughly +11.1%;
- some later delays, including 2022/2025, cost small amounts.

Recovery-only Concordance moves the max-drawdown frontier from the 2022 trough back into 2021. The divergence state then addresses a structurally different 2021 event: Wealth Core / momentum leadership deteriorated while SPY remained comparatively healthy.

The disjoint-block result above also shows that the candidate can underperform for a multi-year regime. This weakens any claim of universal alpha but strengthens the intended interpretation: Concordance is sparse insurance against specific false-recovery and strategy-divergence states.

## Adversarial result 6 — causality / look-ahead audit

The reconstructed witness and overlay obey the intended causal ordering:

- independent leadership membership is selected using information available at the prior close;
- witness returns are earned subsequently, not retroactively assigned to the population that won ex post;
- Sentinel allocation changes execute at the next session open;
- risk-off authority is not delayed by Concordance;
- BIL remains the defensive sleeve under the same next-open accounting and 10 bp allocation-change cost;
- the witness is a sensor only and never receives capital.

No future allocation, frozen daily oracle, or future winning membership is intentionally consumed by the Concordance logic.

However, this does **not** resolve the separate known historical-causality limitation around point-in-time SEC filings. The current historical result still awaits that SEC correction/reconstruction. Concordance validation therefore inherits that remaining uncertainty.

## What failed to falsify the candidate

The candidate survives:

- exact corrected-baseline reproduction;
- exact reconstruction of the retained post-dividend Concordance control;
- 5/10/15/20-year trailing comparisons;
- 15 annual start dates;
- a broad 2,916-combination local parameter neighborhood;
- cap-level perturbation (55% vs 65%);
- recovery-witness construction changes;
- the negative-control removal of the latch, which demonstrates that the naive stop-loss interpretation is wrong;
- explicit causal ordering review.

## What remains unproven

The candidate is **not yet validated as a production strategy** because:

1. the same historical corpus was used for discovery, so no genuine historical OOS set remains;
2. the SEC point-in-time adjustment is still outstanding;
3. the exact new research implementation should be retained as source before any production port;
4. future live/paper observations after the freeze provide the cleanest true holdout;
5. an independent implementation should reproduce the frozen candidate from raw corrected inputs before certification.

## Current verdict

**PASS as a research hypothesis; NOT YET PASS as a production strategy.**

The evidence is materially stronger than a backtest maximum:

- the architecture improves both wealth and drawdown over the corrected baseline;
- the improvement persists across broad parameter neighborhoods and multiple witness formulations;
- one disjoint multi-year regime still underperforms, arguing against an implausible universal edge;
- the critical ablation shows the stateful latch is essential and a simple cap is harmful;
- causal ordering remains compatible with next-open execution.

The correct next step is not more threshold optimization. Freeze this candidate, retain its source implementation, rerun it after the SEC correction, and begin accumulating genuinely unseen forward sessions as the true holdout.