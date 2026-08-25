# Orion PIT / Full-C harness reconstruction — WIP

Research branch only. **Do not use this harness for economics until the control gates pass.** Nothing here changes `main`.

## Current local reconstruction

The retained `fresh_current_main_backtest.py` File Library source is being reconstructed as the authoritative Wealth Core / Sentinel accounting base before Orion is layered on top.

Current local harness:

- filename: `orion_authoritative_ab_runner.py`
- SHA-256: `fbf6ec15c45ca87a169dd245283a7fc66fc45b875ffcb1c072fe2b4d31e14a9b`
- status: WIP / control calibration only

Changes relative to the rejected first attempt:

- restored current Common Stock category gate for the A-side control;
- restored first/last listing-interval eligibility;
- restored current Sharadar `relatedtickers` issuer-family blocking for the A-side control;
- restored entry/exit state resets and pending-signal bookkeeping;
- corrected effective-native timing so LD-RC sees the allocation that actually became effective at the open, rather than the newly computed close-time native target;
- added an explicit `current` arm using the authoritative raw FAST `damaged(t)-damaged(t-5) >= 0.40` predicate;
- added `CONTROL_ONLY=1` execution mode so control parity can be established without paying the dynamic-peer computation cost.

## Mandatory gates

Before accepting Experiment 1 or 2:

1. 2008-12-23 leadership parity must be `(population=101, overlap=7)`.
2. 2022-01-03 leadership parity must be `(population=96, overlap=8)`.
3. Current authoritative arm must reproduce 20-year `22.6302156206% / 1.213813871 / -21.6958215% / 59.1542869x`.
4. Frozen legacy Orion must then reproduce its retained session-level behavior/economics before PIT or Full-C deltas are accepted.

The WIP source hash is retained here because the local harness is not yet an accepted/reproducible research artifact. Once the gates pass, the runnable harness source itself will be committed under this experiment directory before candidate results are accepted.