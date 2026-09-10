# Current hardening champion

## Champion

**Wealth Core V5 + Sentinel EX3 V6 with Native Sentinel recovery-ramp state removed/neutralized.**

This is the current **research hardening champion** based on the completed state-component ablation campaign. It is **not promoted to production/main** by this document.

## Evidence authority

- Experiment branch: `research/wealth-core-v5-ex3-v6-state-component-ablation-v1`
- Experiment head: `ddabaa9ac5c35a722c1f429fad4192a6d232b7b2`
- GitHub Actions run: `34515342448`
- Exact selected V6 source SHA-256: `335e2ae06efd5e2ebfa11f0641029609d524f4e75e733a3dbd0a5efcf64ac42d`
- Full-PIT measurement: 2006-07-31 through 2026-07-31, 5,032 sessions
- Perturbation set: six held-security leave-one-out cases plus one deterministic 1% universe-dropout case

## Baseline economics

Current Sentinel EX3 V6:

- CAGR: **21.56%**
- max drawdown: **-27.38%**
- Sharpe: **1.121**

Native recovery-ramp ablation:

- CAGR: **22.16%**
- max drawdown: **-25.87%**
- Sharpe: **1.145**

Observed change versus current:

- CAGR: approximately **+0.60 percentage point**
- max drawdown: approximately **+1.51 percentage points better**
- Sharpe: approximately **+0.024**

## Robustness result

The recovery-ramp ablation produced the strongest robustness improvement among the six one-component ablations:

- median integrated allocation-divergence area reduction: approximately **31.0%**
- it reduced divergence in **every perturbation where current Sentinel exposure actually diverged**
- it introduced no regression in the two leave-one-out cases where current Sentinel had zero exposure divergence

Per-case integrated allocation-divergence area:

| Fault | Current | Recovery-ramp ablation | Change |
|---|---:|---:|---:|
| LOO 0 | 199.7 | 157.6 | -21% |
| LOO 1 | 335.4 | 221.6 | -34% |
| LOO 2 | 230.8 | 125.4 | -46% |
| LOO 3 | 242.8 | 167.6 | -31% |
| LOO 4 | 0.0 | 0.0 | unchanged |
| LOO 5 | 0.0 | 0.0 | unchanged |
| 1% universe dropout | 360.8 | 280.1 | -22% |

## Interpretation

This result is stronger than a median-only win. The recovery-ramp ablation improved all five affected perturbations, including all affected leave-one-out cases and the deterministic universe-dropout case.

The relevant state is in **Native Sentinel**, not Wealth Core:

- `ramp`
- `ramp_idx`
- `ramp_h`
- `r40hist`

The current evidence therefore points to Native Sentinel recovery-ramp state as the best next hardening target. It appears to contribute materially to path amplification while also degrading baseline economics in this campaign.

## Current ranking context

The completed one-component experiment ranked the recovery-ramp ablation ahead of the other tested components on the robustness/economics tradeoff. Other ablations either delivered materially less robustness improvement or caused more economic damage.

## Promotion guard

This is a **research champion**, not a production authority. Before promotion, the recovery behavior should be redesigned deliberately and then subjected to a separate certification campaign covering at minimum:

- exact next-session timing and restart equivalence;
- full-PIT historical parity outside the intended recovery change;
- adversarial controller/state-machine tests;
- leave-one-out and universe perturbation robustness;
- economic regression gates for CAGR, drawdown, Sharpe, and defensive behavior;
- production/runtime integration and state persistence/recovery semantics.

No automatic promotion to main is authorized by this finding.
