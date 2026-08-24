# Symbolic sector/peer execution checkpoint — 2026-08-23

Research-only checkpoint for issue #241 and branch `research/pit-sector-signal-2026-08-23`. Nothing here changes production strategy authority or `main`.

## Frozen architecture under test

Primary results use the current corrected-volume Simplified Concordance lineage and the **30 percentage-point** five-session damaged-breadth acceleration threshold. The 40pp recovered Sentinel 1.1 rule remains a historical sensitivity only.

All non-peer economics are held fixed: Wealth Core shadow/trades, corrected Sharadar price/action domains, SEC-PIT issuer identity, independent leadership witness, SPY sensor, LD-RC v3, close-to-next-open timing, BIL/cost model.

For the strongest hybrid candidate, the causal SEC SIC->FF12 damaged-breadth series remains the slow/stable structural breadth input; the dynamic market-derived peer signal is used only to decide the **fast contagion** branch. This is intentional: a sustained slow-stress regime and a fast contagion detector need not use the same peer definition.

## Symbolic reduction

Peer grouping only has economic discretion when it can change the fast damaged-breadth branch. For every session, compute the peer-independent lower and upper bounds on damaged breadth:

- `min_d`: unavoidable/core AMBER fraction even with no peer escalation;
- `max_d`: maximum AMBER fraction permitted if all vulnerable names can be escalated.

Holding every other fast-trigger clause fixed, sessions are classified as:

- **impossible**: no valid peer grouping can satisfy the fast branch;
- **inevitable**: every valid grouping satisfies it;
- **controllable**: peer grouping can decide the branch.

Across the 20-year tape, only **73** sessions satisfy all non-peer fast preconditions: **42 impossible, 6 inevitable, 25 controllable**. Thus the apparent high-dimensional sector problem reduces to only 25 economically discretionary branch points.

## Exact dynamic-programming hindsight oracle

`sector_symbolic_v21_exact_dp.py` exhausts both fast choices on every controllable date and evolves the complete native Sentinel + ramp + LD-RC state machine. States with identical future-relevant controller state are merged, retaining only the higher-NAV path. This is therefore an exact terminal-NAV oracle **within the fixed fast-branch abstraction**. It is not deployable and is not a global strategy optimum.

Exact oracle results, 2006-07-31..2026-07-31:

| metric | exact symbolic oracle |
|---|---:|
| CAGR | **20.1574953%** |
| Sharpe | **1.120525** |
| max drawdown | **-24.1570%** |
| ending multiple | **39.3595x** |
| discovery CAGR (through 2015) | **17.0224%** |
| validation CAGR (2016+) | **23.0447%** |
| 2016-2020 CAGR | **18.6748%** |
| 2021-2026 CAGR | **27.1337%** |

Oracle chooses fast=ON on only five controllable sessions: 2008-07-08, 2011-08-04, 2015-08-24, 2018-10-12, and 2022-04-26. All other controllable dates are OFF. Inevitable dates remain ON independently of peer choice.

## Best causal approximation so far

The strongest coherent causal hybrid is:

1. calculate each held name's prior-252-session return residual after removing rolling SPY beta;
2. for each vulnerable (non-GREEN, non-core-damaged) holding, calculate the maximum residual correlation to currently RED held names;
3. require residual correlation >= **0.15**;
4. require 252-session historical co-distress (Jaccard) corroboration, **or** permit the residual signal alone when the symbolic own-damage floor is `min_d <= 0.75`;
5. apply the dynamic signal only on symbolic-controllable dates; inevitable remains ON and impossible remains OFF;
6. retain SEC SIC->FF12 breadth for the slow/stable native stress path.

The `min_d <= 0.75` geometry is economically interpretable: the book itself is not yet saturated with unavoidable damage, so peer escalation is supplying meaningful missing contagion evidence. Floors 0.70, 0.75 and 0.80 produced the same path.

Primary hybrid result (`sector_symbolic_v22_geometry.py`):

| metric | causal hybrid |
|---|---:|
| 20Y CAGR | **20.1117225%** |
| Sharpe | **1.118670** |
| max drawdown | **-24.1570%** |
| ending multiple | **39.0608x** |
| discovery CAGR | **16.9492%** |
| validation CAGR | **23.0247%** |
| validation Sharpe | **1.188979** |
| 2016-2020 CAGR | **18.6340%** |
| 2021-2026 CAGR | **27.1337%** |

Fast episode starts: 2008-07-02, 2008-10-03, 2011-08-04, 2015-08-24, 2018-02-08 (inevitable), 2018-10-11, 2020-02-27 (inevitable), 2022-04-26, 2022-06-15 (inevitable).

Compared with the exact fast-branch oracle, the causal hybrid is only about **4.6 bp/year** lower in CAGR and has the same max drawdown. This shows that the latent information needed by the fast branch is approximable from causal market history.

### Important full-replacement distinction

When the same dynamic residual construction is also substituted for the slow/stable damaged-breadth series, the corresponding threshold-sweep harness gives about **20.07% CAGR** rather than 20.11%. The difference is only a few basis points/year, but it is conceptually important: the strongest architecture found so far is a **two-timescale hybrid** — structural SEC/FF12 peers for sustained slow stress, dynamic market peers for fast contagion — rather than one peer definition forced into every branch.

## Baselines

Authoritative 30pp comparisons from the frozen experiment:

| peer definition | 20Y CAGR | Sharpe | max DD |
|---|---:|---:|---:|
| sector-neutral | 17.55% | 0.994 | -28.64% |
| current Sharadar sector (non-PIT control) | 18.43% | 1.042 | -25.21% |
| causal SEC SIC->FF12 | **18.48%** | **1.044** | **-25.21%** |
| best causal hybrid fast-contagion signal | **20.11%** | **1.119** | **-24.16%** |
| exact fast-branch hindsight oracle | **20.16%** | **1.121** | **-24.16%** |

The causal hybrid is therefore roughly **+1.63 percentage points/year** above the causal static FF12 control and **+2.56 pp/year** above sector-neutral.

## Robustness and the main caveat

The symbolic geometry floor is robust: 0.70, 0.75 and 0.80 are path-identical.

The residual-correlation threshold is less robust because Sentinel itself contains hard cliffs (`damaged >= 85%` and `d5 >= 30pp`). Fine sweep:

- 0.130: ~18.83% CAGR
- 0.135-0.145: ~19.01%
- **0.150-0.155: ~20.07-20.11%**
- 0.160-0.165: ~19.17% with worse drawdown
- 0.170: ~18.63%

So there is a real but narrow plateau around 0.15-0.155. A Fisher-z significance formulation does not eliminate this cliff sensitivity; z≈2.45 recreates the strong path while standard nearby cutoffs can differ materially.

This means the candidate is **research-grade, not production-ready**. The next step should be to reduce threshold brittleness rather than continue optimizing headline CAGR.

## Pseudo-out-of-sample expanding walk-forward threshold test

A new walk-forward sensitivity (`sector_symbolic_v29_walkforward_threshold.py`) chooses the residual threshold using only the preceding history at 5-year boundaries, then freezes it for the next block. Selection criterion: maximize training CAGR; if several thresholds are within 1 bp/year, choose the lowest threshold deterministically. Sharpe-based selection gives the same choices after 2010.

| training window | selected threshold | next test window | test CAGR |
|---|---:|---|---:|
| 2006-2010 | 0.13 | 2011-2015 | **11.32%** |
| 2006-2015 | 0.15 | 2016-2020 | **18.63%** |
| 2006-2020 | 0.15 | 2021-2026 | **27.13%** |

Matched causal FF12 test CAGRs are about 8.68%, 18.63%, and 25.54%, respectively. The stitched 2011-2026 pseudo-OOS path is: walk-forward hybrid CAGR **19.13%** vs FF12 **17.69%**; Sharpe **1.075** vs **1.013**; max drawdown **-24.16%** vs **-25.21%**.

This is encouraging because the 0.15 setting is selected by history ending in 2015 and then remains preferred when training expands through 2020. It is still not a pristine untouched holdout because the research design itself was developed after examining the historical tape, so it must be labelled pseudo-OOS rather than proof of future performance.

## Episode-ablation robustness

`sector_symbolic_v28_episode_ablation.py` suppresses one fast episode at a time from the best causal hybrid. The useful controllable episodes are not confined to one event:

- remove 2008-07: full CAGR falls about **0.64 pp/year**;
- remove 2015-08: falls about **0.33 pp/year**;
- remove 2018-10: falls about **0.83 pp/year**, and max DD worsens to about -27.29%;
- remove 2022-04: falls about **0.08 pp/year**, and max DD worsens to about -25.21%;
- 2008-10 is economically neutral in this path.

Thus the improvement is concentrated in a handful of crisis episodes — necessarily so because symbolic execution proves only 25 dates are controllable — but it is not dependent on a single one. Inevitable episodes such as 2020-02 are outside the peer model's discretion; suppressing them is an invalid peer-signal counterfactual and is retained only as diagnostic information.

## Why one raw correlation threshold cannot reproduce the exact oracle

The fast condition depends on both today's damaged breadth and the t-5 damaged breadth, so the effect of a correlation cutoff is non-monotonic. Exact threshold intervals on controllable days include:

- 2008-07-08 (oracle ON): ~0.1576-0.1691 or >0.3536
- 2011-08-04 (ON): >~0.147
- 2015-08-24 (ON): any threshold
- 2018-10-12 (ON): <~0.0759
- 2022-04-26 (ON): <~0.1552

No single global residual-correlation threshold can match all oracle choices. The causal hybrid succeeds because it combines dynamic residual similarity, co-distress history, and symbolic book geometry rather than treating correlation as the whole signal.

## Interpretation

The evidence now supports a stronger formulation than “find a better sector taxonomy”:

> Sentinel's useful latent variable is cross-sectional **contagion**, conditional on whether peer escalation is actually capable of changing the controller branch.

Static industry classification is a useful slow structural prior. Fast crisis detection is better served by dynamic market-residual peer relationships plus historical co-distress and symbolic branch relevance.

The exact DP shows the maximum terminal-wealth improvement available from the fast peer branch under the frozen controller. The causal hybrid captures almost all of that measured headroom, but its remaining problem is stability around a discrete correlation threshold, not lack of alpha headroom.

## Next research step

Do **not** optimize CAGR further against the same 20-year tape. The next research should focus on falsification:

1. replace the hard residual-correlation threshold with a continuous/probabilistic contagion score or a predeclared walk-forward calibration;
2. run rolling and leave-crisis-out validation;
3. bootstrap/perturb return histories and correlation estimates to test branch stability;
4. measure whether small input noise flips the 25 controllable symbolic decisions;
5. require any promotion candidate to preserve the current strategy under nearby peer-count/lookback/calibration choices.
