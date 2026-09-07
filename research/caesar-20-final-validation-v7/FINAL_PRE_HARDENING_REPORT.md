# Caesar 20 — Final Pre-Hardening Validation Report

Date: 2026-09-07

## Status

**PRE-HARDENING VALIDATION COMPLETE.**

This document freezes the headline evidence and conclusions accumulated for the research candidate named **Caesar 20** before any hardening work. Caesar 20 is the 20-holding implementation with 5% entry weight evaluated on the corrected certified 20-year PIT reconstruction with exact one-session dividend settlement.

The evidence supports Caesar as a genuine strategy family and Caesar 20 as a defensible implementation point within that family. The largest demonstrated unresolved structural weakness is sensitivity to exact top-of-ranking candidate ordering.

## Certified Caesar 20 reference

| Horizon | CAGR | Max drawdown | Sharpe |
|---|---:|---:|---:|
| 5y | 26.95% | -21.66% | 1.287 |
| 10y | 24.87% | -23.82% | 1.230 |
| 15y | 20.04% | -23.82% | 1.105 |
| 20y | **19.94%** | **-23.82%** | **1.082** |

20-year terminal wealth: **37.93x**.

## Causal adversarial stresses

| Stress | 20y CAGR | Max DD | Sharpe |
|---|---:|---:|---:|
| Caesar 20 | **19.94%** | **-23.82%** | **1.082** |
| Entry +1 session | 17.11% | -29.13% | 0.965 |
| Entry +2 sessions | 18.14% | -25.97% | 1.014 |
| Exit +1 session | 17.62% | -27.23% | 1.024 |
| Top-3 ranking reversed | **14.88%** | -27.64% | **0.891** |
| 25 bps round-trip cost stress | 17.22% | -25.14% | 0.961 |
| 50 bps round-trip cost stress | 18.14% | -24.68% | 0.997 |

### Interpretation

The dominant demonstrated weakness is **exact cross-sectional candidate ordering**. Reversing only the top three candidates produces the largest degradation in the adversarial suite. The alpha is therefore materially concentrated in precise ordering near the top of the candidate queue.

Entry and exit timing perturbations demonstrate meaningful path sensitivity, but every timing arm retains substantial positive long-horizon compounding. Transaction-cost stresses demonstrate that implementation friction itself is not the principal fragility. The non-monotonic cost and timing results are evidence of causal path divergence: changed NAV/holdings alter later admissions and defensive states.

## Portfolio-size/path-divergence evidence

Targeted neighboring-size tests showed that Caesar 20 is not an isolated optimum.

| Holdings | CAGR | Max DD | Sharpe |
|---:|---:|---:|---:|
| 19 | 19.56% | -24.44% | 1.036 |
| **20** | **19.94%** | **-23.82%** | **1.082** |
| 21 | 18.95% | -23.04% | 1.039 |
| 22 | 18.29% | -25.60% | 1.009 |
| 23 | 17.22% | -25.48% | 0.964 |
| 24 | 18.42% | -22.70% | 1.035 |

Neighbor path diagnostics:

| Pair | Holdings Jaccard | Allocation agreement | Daily-return correlation | Tracking error |
|---|---:|---:|---:|---:|
| 19↔20 | 0.871 | 92.3% | 0.953 | 5.77% |
| 20↔21 | 0.758 | 93.2% | 0.959 | 5.29% |
| 21↔22 | 0.863 | 95.0% | 0.963 | 4.97% |
| 22↔23 | 0.845 | 95.4% | 0.978 | 3.84% |
| 23↔24 | 0.802 | 91.5% | 0.968 | 4.58% |

The evidence supports a concentrated high-alpha region around 19–20 and a broader stable region through the low 20s. Exactly 20 should not be treated as a uniquely privileged mathematical optimum.

## Five-way security-universe jackknife

Each arm permanently excluded a different disjoint 20% security-ID bucket.

| Removed bucket | CAGR | Max DD | Sharpe |
|---:|---:|---:|---:|
| 0 | **17.75%** | -24.41% | 0.992 |
| 1 | **18.91%** | -26.86% | 1.023 |
| 2 | **17.40%** | -26.33% | 0.967 |
| 3 | **17.00%** | -25.67% | 0.954 |
| 4 | **18.30%** | -25.59% | **1.031** |

### Interpretation

This is strong evidence against dependence on one broad subset of historical securities. Every disjoint 20% exclusion retains high long-horizon compounding. The worst jackknife remains at 17.00% CAGR.

## Liquidity/capacity stresses

The initial liquidity jobs produced valid causal replays but failed an over-strict validation assertion that required liquidity-stressed runs to traverse the exact baseline classification population. A tighter liquidity gate legitimately removes candidates before that traversal. The repaired validation requires frozen classifier/source/PIT/dividend identity, closed accounting, monotonic reductions versus baseline, and proof that the liquidity constraint binds.

The three repaired jobs passed.

| Variant | 20y CAGR | Δ vs Caesar | Max DD | Sharpe | Terminal wealth |
|---|---:|---:|---:|---:|---:|
| Caesar 20 | **19.94%** | — | **-23.82%** | **1.082** | **37.93x** |
| Same-day dollar volume ≥ $10M | **18.47%** | -1.47 pp | **-23.44%** | 1.020 | 29.66x |
| ADV20 ≥ $40M | **15.32%** | -4.62 pp | -34.45% | 0.943 | 17.30x |
| ADV20 ≥ $80M | **16.20%** | -3.74 pp | **-23.69%** | 0.982 | 20.14x |

The same-day-volume stress is particularly strong: doubling the decision-day dollar-volume floor from $5M to $10M retains 18.47% CAGR and slightly improves maximum drawdown.

The average-volume filters materially change the opportunity set. The $40M threshold removes roughly 31% of candidate observations and the $80M threshold roughly 56%. The $80M-only universe still compounds at 16.20% over twenty years with maximum drawdown almost identical to Caesar 20.

The $80M result exceeding the $40M result demonstrates path dependence and rules out a simple monotonic interpretation that progressively smaller securities mechanically generate all of the alpha. A meaningful portion of Caesar's excess return does come from access to the broader $20M+ ADV universe, while the strategy's alpha survives severe liquidity restriction.

Repaired liquidity run: https://github.com/flabber1835/stocker/actions/runs/34142621923

## Research-selection / overfitting statistics

### Deflated Sharpe Ratio

- Documented 33-trial penalty: **99.61% DSR probability**
- 100-trial sensitivity: **98.76%**
- 250-trial sensitivity: **97.37%**

Caesar's Sharpe remains statistically convincing under research-trial penalties materially larger than the documented search history.

### White-style block Reality Check

**p = 0.05097**

This is strong but borderline evidence at the conventional 5% significance boundary after accounting for selection across the tested candidate family.

### CSCV / Probability of Backtest Overfitting

**PBO = 48.27%**

The CSCV family consists of the closely related holding-count variants 16, 18, 19, 20, 21, 22, 23, 24 and 25. Caesar 20 was selected in-sample in 3,128 of 6,435 splits, substantially more frequently than most alternatives, while the exact best holding count moves materially between samples.

The appropriate conclusion is that the **strategy family is more stable than the assertion that exactly 20 holdings is uniquely optimal**. This agrees with the neighboring-size/path-divergence experiments.

## Integrated robustness assessment

### Very strong evidence

- Corrected PIT / forward-bias integrity
- Exact one-session dividend settlement
- 20-year persistence
- Five-way 20% security-universe jackknife
- Transaction-cost survival
- Same-day liquidity robustness
- Deflated Sharpe after research multiplicity penalties
- Neighboring holding-count variants retaining similar economics

### Strong evidence

- Survival under severe ADV restrictions
- Entry/exit delay survival
- Drawdown behavior
- Recent 5-year and 10-year economics

### Demonstrated structural weakness

**Top-of-ranking decision-path sensitivity.** Exact ordering among the highest-ranked candidates materially affects long-run outcomes. This is the primary economic robustness issue identified by the adversarial program.

### Statistical caveat

The evidence supports the strategy family much more strongly than it supports the claim that 20 holdings is the unique optimum. Portfolio size should be viewed as a robust-region implementation choice.

## Structural research hypothesis reserved for post-freeze work

The leading improvement hypothesis is to preserve strong rank conviction while smoothing admissions when the top candidates are effectively tied. Candidate mechanisms include top-3 consensus/persistence admission, confidence-dependent sleeve sizing, two-stage commitment, rank-robustness perturbation, and admission hysteresis.

Any such work constitutes a new research candidate. It must not retroactively alter this Caesar 20 evidence package.

## Final conclusion

**Caesar 20 has completed the planned pre-hardening validation program.**

The total evidence supports Caesar as a genuine, persistent strategy family and Caesar 20 as a defensible implementation point within that family. Performance survives large security-universe removals, substantial execution friction, delayed trading, and severe liquidity restrictions. Research-selection corrections remain broadly supportive.

The largest unresolved structural weakness is precise top-rank candidate dependence. This is an explicit known risk to carry into prospective paper trading and a clearly separated target for future research.

The next engineering phase may harden the frozen Caesar 20 candidate. Prospective paper trading remains the genuinely unseen out-of-sample validation stage.
