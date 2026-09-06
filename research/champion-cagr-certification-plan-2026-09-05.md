# Research Champion CAGR certification plan — 2026-09-05

Status: IN PROGRESS / NOT YET CERTIFIED

Candidate corrected replay: GitHub Actions run 34007704385
Artifact: champion-corrected-classification-34007704385-1
Artifact id: 9981966560
Artifact digest: sha256:4860751ea45f7480f785e927bc4cebba1c8be3783b354d186ce059d6fb09a841
Head: ba74e79490beb8950611b1d17f5d124833b3d91e
Frozen profile: strategy9-e3-research-champion-v1

Current corrected candidate metrics:
- 20y CAGR: ~20.09%
- ending multiple: ~38.91x
- max drawdown: ~-23.83%
- Sharpe: ~1.10
- trailing CAGR: 5y ~25.42%, 10y ~23.04%, 15y ~18.70%, 20y ~20.09%

These metrics are candidate results only until the gates below close.

## Proven historical classification corrections already included

- PDS: trust units non-common through 2010-06-01; corporation common shares from 2010-06-02.
- EQM: limited-partnership common units treated non-common during the admitted partnership interval.

Controlled attribution established that PDS has essentially zero economic effect and EQM explains essentially the full reviewed-baseline-to-corrected path change.

## Remaining decision-relevant inferred-common surface

From `decision-relevant-inferred-common-audit.csv` in the corrected artifact:
- total decision-relevant inferred-common securities: 1,492
- HELD_OR_PENDING: 83
- LEADERSHIP_SIGNAL: 1,298
- DURABLE_RANKED: 28
- RANKING_INPUT: 83

The 83 HELD_OR_PENDING names are the highest-priority historical-class verification set because an error can directly alter the realized stock-selection/execution path.

The 1,298 LEADERSHIP_SIGNAL names are separately important only because the current LDRC controller derives recent leadership from the classified eligible universe. A classification error can therefore alter controller state even when the security is never held.

## Certification gates

### Gate A — immutable replay identity
Require exact binding of source commit, frozen runtime, profile hash, canonical PIT dataset hash, classification ledgers, correction ledger, generated replay, metrics and artifact digest.

### Gate B — chronological / no-lookahead execution
Require proof that all decisions use only information available by the decision session, including prices, actions, identity/classification, membership/eligibility and controller inputs.

### Gate C — realized execution-path classification
Authoritatively verify the 83 HELD_OR_PENDING inferred-common securities, prioritizing legal-security structures capable of defeating coarse vendor categories: partnership/common units, trusts, depositary/preferred structures, units/warrants, conversions/reorganizations and identity discontinuities.

Any demonstrated defect must be corrected with effective-session dates, authoritative contemporaneous evidence, then replayed from the frozen baseline.

### Gate D — current-controller classification dependency
If the current universe-derived leadership controller remains the Champion, resolve enough of the 1,298 LEADERSHIP_SIGNAL inferred-common names to support the controller input path, with targeted emphasis on names that can enter or displace the leadership cutoff.

If a classification-independent SPY/VIX controller is adopted after independent research, this gate can be removed from the CAGR certification scope for that controller because those security classifications would no longer feed risk allocation directly. Stock-selection Gate C would still remain.

### Gate E — causal closure after corrections
After the final authoritative classification ledger is frozen, run a fresh 20-year chronological replay. Require:
- exact hashes recorded;
- no unresolved correctness failures on the realized execution path;
- 5/10/15/20-year trailing metrics;
- max drawdown, Sharpe, ending multiple and SPY comparison;
- first-divergence analysis versus the prior candidate if any correction changes the path.

### Gate F — claim wording
Certification applies to the exact reconstructed 2006–2026 execution path under the frozen dataset/runtime/profile and the documented PIT authority set. It does not imply that every possible historical security in the broad universe has complete perfect metadata, nor that future performance will match the backtest.

## Current claim

The ~20.09% CAGR is presently a corrected, reproducible research result, not yet a certified CAGR.

The immediate certification work is Gate C: close the 83 HELD_OR_PENDING classifications. In parallel, the SPY/VIX controller experiment determines whether Gate D remains necessary for the final architecture.
