# Wealth Core V1 10 bp + Experiment 3 / Research Champion EX3

Status: **PASS_EXISTING_REPLAY_EX3_LAYER_VERIFIED**

The 10 bp replay already executed the Research Champion Candidate-A / EX3 controller path in parallel with the pure Wealth Core book. This verification proves the `control` path is exactly Candidate A and extracts the full-system result without rerunning market data.

## Result

| Metric | 0 bp Wealth Core + EX3 | 10 bp Wealth Core + EX3 | Delta |
|---|---:|---:|---:|
| CAGR | 17.435251% | **20.134530%** | **2.699279 pp** |
| Max DD | -24.364458% | **-22.473613%** | 1.890844 pp |
| Sharpe | 0.980495 | **1.085719** | 0.105225 |
| Ending multiple | 24.888474x | **39.209363x** | 14.320889x |

Pure 10 bp Wealth Core CAGR was 15.488288%; with EX3 layered on it the measured CAGR is **20.134530%**.

## Path effect

The 10 bp core first changed held positions on **2006-11-02**. Rankings never diverged, confirming the cash rule changed admissions/holdings rather than stock-ranking economics. The native risk target later diverged on **2015-10-26**, and the EX3 effective allocation first diverged on **2015-10-29**.

- days with different held-position hashes: 4787
- days with different native exposure target: 154
- days with different EX3/control allocation: 404
- 0 bp EX3 allocation transitions: 26
- 10 bp EX3 allocation transitions: 19
- 0 bp Candidate-A episodes: 8
- 10 bp Candidate-A episodes: 6

## Interpretation

The 10 bp reserve improves the pure Wealth Core path and also changes the inputs seen by Experiment 3. On this exact historical path the interaction is favorable: the combined CAGR rises by 2.699 percentage points, max drawdown becomes materially shallower, and Sharpe rises. This is still path-dependent evidence, not a claim that 10 bp mechanically creates alpha.

Dividend settlement is **1 session**, not 15. Whole shares only. Canonical PIT dataset hash is `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`.
