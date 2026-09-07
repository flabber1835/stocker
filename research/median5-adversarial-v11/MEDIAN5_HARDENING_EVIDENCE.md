# Median-5 — Hardening Evidence and Conclusions

Date: 2026-09-07

## Purpose

This file records the research path from frozen Caesar 20 through the admission-hardening experiments that produced the Median-5 challenger. It preserves the distinction between the already-validated Caesar 20 baseline and the newly selected Median-5 strategy candidate.

## Frozen Caesar 20 reference

- 20 holdings / slots
- 5% entry weight
- corrected one-session dividend settlement
- immutable canonical PIT corpus
- frozen classifier/runtime/source pins
- 20-year CAGR: **19.94%**
- 20-year max drawdown: **-23.82%**
- 20-year Sharpe: **1.082**
- terminal wealth: **37.93x**

The principal demonstrated Caesar 20 weakness was exact top-of-ranking decision-path sensitivity. Reversing only the daily top three candidates reduced 20-year CAGR to **14.88%**, max drawdown to **-27.64%**, and Sharpe to **0.891**.

## Hardening discovery hypothesis

The objective was to reduce dependence on one-session ordering among the highest-ranked candidates while preserving the frozen 20-slot / 5%-entry accounting model and all other Caesar economics.

The discovery suite changed only the admission-selection seam. All rank history used current and prior decision sessions only. No future information or prerecorded decisions were used.

## Six discovery arms

| Arm | 20y CAGR | Delta vs Caesar 20 | Max DD | Sharpe | Terminal |
|---|---:|---:|---:|---:|---:|
| Caesar 20 | **19.94%** | — | **-23.82%** | **1.082** | **37.93x** |
| Consensus median 5 | **19.70%** | **-0.24 pp** | -26.39% | 1.047 | 36.48x |
| Top-3 persistence 3 | **19.08%** | -0.86 pp | **-23.20%** | **1.048** | 32.87x |
| Gap-5% + consensus 3 | 18.75% | -1.19 pp | -29.87% | 1.037 | 31.08x |
| Gap-2% + consensus 3 | 18.66% | -1.28 pp | **-23.20%** | 1.031 | 30.61x |
| Top-3 vote 3 | 17.93% | -2.01 pp | -24.26% | 0.988 | 27.09x |
| Consensus median 3 | 17.54% | -2.40 pp | -27.75% | 0.967 | 25.33x |

### Discovery conclusions

- Five-session consensus preserved nearly all of Caesar 20's canonical economics.
- Three-session consensus was too aggressive and sacrificed too much alpha.
- Persistence-3 produced the cleanest risk profile among the alternatives but surrendered more canonical CAGR than Median-5.
- Gap-threshold rules did not dominate the simpler persistence/median designs.

The best two candidates were therefore **Consensus Median-5** and **Top-3 Persistence-3**.

Discovery run: https://github.com/flabber1835/stocker/actions/runs/34146059708

## Strict top-3 reversal confirmation

The two finalists were then tested under the same adversarial top-three reversal concept that exposed Caesar 20's primary weakness. The perturbation was applied before the hardener and before rank-history storage, so the hardener only saw the perturbed causal ranking stream.

| Strategy | Normal CAGR | Reversed CAGR | Reversal penalty | Reverse DD | Reverse Sharpe |
|---|---:|---:|---:|---:|---:|
| Caesar 20 | **19.94%** | 14.88% | **-5.06 pp** | -27.64% | 0.891 |
| Median-5 | **19.70%** | **17.01%** | **-2.69 pp** | **-23.44%** | 0.952 |
| Persistence-3 | 19.08% | **17.04%** | **-2.04 pp** | -24.43% | **0.961** |

### Median-5 reversed horizon results

| Horizon | CAGR |
|---:|---:|
| 5y | **19.40%** |
| 10y | **18.70%** |
| 15y | **17.02%** |
| 20y | **17.01%** |

Adversarial max drawdown: **-23.44%**  
Adversarial Sharpe: **0.952**  
Adversarial terminal wealth: **23.14x**

### Persistence-3 reversed horizon results

| Horizon | CAGR |
|---:|---:|
| 5y | 15.20% |
| 10y | 17.89% |
| 15y | 16.68% |
| 20y | **17.04%** |

Adversarial max drawdown: **-24.43%**  
Adversarial Sharpe: **0.961**  
Adversarial terminal wealth: **23.25x**

### Confirmation conclusion

**Median-5 is the selected hardening challenger.**

It gives up only **0.24 percentage points** of canonical 20-year CAGR versus Caesar 20 while improving the strict top-3 reversal result by **2.13 percentage points** and reducing the reversal penalty from **5.06 pp to 2.69 pp**. Its reversed max drawdown also improves materially relative to Caesar 20.

The evidence indicates that Caesar's rank-1 information is real, but a single decision session's exact top-three ordering contains meaningful noise. A five-session median-rank consensus retains nearly all canonical alpha while reducing dependence on one day's precise ordering.

Reversal confirmation run: https://github.com/flabber1835/stocker/actions/runs/34148933220

## Median-5 canonical headline results

| Horizon | Median-5 CAGR | SPY CAGR | Max DD | Sharpe |
|---:|---:|---:|---:|---:|
| 5y | **29.22%** | 12.83% | **-19.04%** | **1.307** |
| 10y | **24.55%** | 15.01% | -26.39% | **1.170** |
| 15y | **19.67%** | 14.44% | -26.39% | **1.059** |
| 20y | **19.70%** | 11.26% | -26.39% | **1.047** |

Median-5 beats SPY on CAGR across all reported horizons.

## Current validation status

Median-5 is now undergoing its own full adversarial validation because it is a newly selected strategy candidate. Eight fresh causal 20-year PIT tests were launched:

1. Entry +1 session
2. Entry +2 sessions
3. Exit +1 session
4. 25 bps round-trip cost
5. 50 bps round-trip cost
6. ADV20 >= $40M
7. ADV20 >= $80M
8. Same-day dollar volume >= $10M

The strict top-3 reversal test above is already complete and is not being repeated.

Median-5 adversarial suite: https://github.com/flabber1835/stocker/actions/runs/34152208682

## Research hygiene / governance

- Caesar 20 remains the frozen research benchmark.
- Median-5 is a separate challenger identity.
- No Median-5 result is allowed to rewrite or reinterpret the Caesar 20 evidence package.
- Any further modifications to Median-5 create a new candidate and require separate evidence.
- Hardening conclusions will be updated only after the eight-arm adversarial suite finishes and is analyzed.

## Current conclusion

Median-5 is the strongest hardening candidate found so far. It has demonstrated a favorable asymmetric trade: negligible loss of canonical CAGR with a large reduction in top-of-queue reversal fragility. Its promotion decision remains pending completion of the full eight-arm adversarial suite.
