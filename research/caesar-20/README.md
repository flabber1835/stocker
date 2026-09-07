# Caesar 20

**Caesar 20** is the frozen name for the 20-stock Research Champion discovered during the corrected Champion alpha study.

Status: **research challenger, not production-certified replacement**.

## Definition

Caesar 20 changes only the portfolio capacity and nominal entry weight relative to the corrected certified 25-stock baseline:

- `N_SLOTS = 20`
- `ENTRY_W = 0.05`

The corrected baseline semantics remain fixed, including exact one-session dividend settlement, 21-session security/slot cooldown behavior, one-at-a-time initialized admissions, 119-session review boundary, 30% trailing stop, factual security classifier, immutable PIT corpus and next-session execution semantics.

## Corrected certified reference

Workflow run: `34071569702`
Artifact: `10001317230`
Source head: `1d3ab06a0b6c1ef5db4939bbecfe24953ae2195d`
Status: `PRODUCTION_EQUIVALENT_CERTIFIED`
Dividend lag: `1` session
Measurement: 2006-07-31 through 2026-07-31, 5,032 sessions

25-stock certified result:

| Metric | Result |
|---|---:|
| CAGR | 18.8008888% |
| Ending wealth | 31.3635x |
| Max drawdown | -24.9137% |
| Daily Sharpe (252) | 1.03634 |

The superseded 15-session dividend-lag run is not an authoritative baseline.

## Caesar 20 result

Caesar 20 was independently reproduced twice: first in the second adversarial experiment round and again in the dedicated portfolio-size robustness sweep. Both produced the same 20-year result.

| Metric | Caesar 20 |
|---|---:|
| CAGR | **19.9355414%** |
| Ending wealth | **37.9307x** |
| Max drawdown | **-23.8169%** |
| Daily Sharpe (252) | **1.08176** |
| Sessions | 5,032 |

Relative to the certified 25-stock baseline, Caesar 20 adds about **+1.135 CAGR percentage points**, improves max drawdown by about **1.10 percentage points**, and improves Sharpe.

## Experiment history

### First five adversarial interventions

Workflow run: `34074276212`

| Arm | CAGR | Max DD | Sharpe | Conclusion |
|---|---:|---:|---:|---|
| Fresh replacement | 17.6699% | -23.8320% | 1.0026 | Worse |
| Multi-refill | 17.4322% | -29.6987% | 0.9867 | Worse |
| Early weak review | 14.9190% | -26.6149% | 0.9009 | Much worse |
| Staged recovery | 18.7553% | -25.0260% | 1.0342 | Essentially flat/slightly worse |
| Combined | 12.9509% | -25.4500% | 0.7827 | Much worse |

These runs showed that the apparent 22-session vacancy fingerprint, one-at-a-time admission throttle, approximately 120-session review boundary and conservative recovery behavior were largely useful economic features.

### Second five adversarial interventions

Workflow run: `34076988256`

| Arm | CAGR | Max DD | Sharpe | Conclusion |
|---|---:|---:|---:|---|
| **20 holdings / 5% entries** | **19.9355%** | **-23.8169%** | **1.0818** | Clear winner |
| 30 holdings / 3.333% entries | 17.9841% | -24.2026% | 1.0499 | Worse |
| Review at 159 sessions | 15.0909% | -25.2306% | 0.8853 | Worse |
| 42-session slot cooldown | 15.2088% | -22.7407% | 0.9185 | Lower return |
| 25% trailing stop | 13.4886% | -25.3599% | 0.8607 | Much worse |

### Dedicated portfolio-size robustness sweep

Workflow run: `34079759743`
Source head: `b27ea672349e5cae9d666e2bf335bfe385a668f7`

| Holdings | CAGR | Ending wealth | Max DD | Sharpe |
|---:|---:|---:|---:|---:|
| 16 | 16.0623% | 19.6721x | -24.9587% | 0.8816 |
| 18 | 17.2107% | 23.9539x | -29.0754% | 0.9447 |
| **20** | **19.9355%** | **37.9307x** | **-23.8169%** | **1.0818** |
| 22 | 18.2883% | 28.7650x | -25.6029% | 1.0094 |
| 24 | 18.4193% | 29.4090x | **-22.7020%** | 1.0346 |
| Certified 25 | 18.8009% | 31.3635x | -24.9137% | 1.0363 |

The result is a **sharp historical optimum at 20**, not a broad 18-22 plateau. For that reason Caesar 20 remains a frozen research challenger. The 24-25 region is historically smoother and more conservative, while Caesar 20 has the best headline return/risk combination.

## PIT and classification integrity

Every completed intervention and portfolio-size arm used the corrected one-session dividend semantics, the immutable canonical PIT package, fresh chronological replay, the factual security classifier and no prerecorded decisions. The experiment reports recorded `classification_expansion_required=false`.

## Interpretation rule

Caesar 20 was discovered after substantial inspection of the same 20-year history. Its 19.94% CAGR is therefore **in-sample research evidence**. Do not describe Caesar 20 as prospectively validated until it accumulates frozen forward results.

See `EVIDENCE.json` for machine-readable provenance and `STRESS_TESTS.md` for local robustness calculations performed from the emitted daily paths.