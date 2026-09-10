# State architecture experiment — pre-run code review

## Scope reviewed

The experiment was reviewed end-to-end before permitting the historical replay fan-out.

Experiment code:

- `research/wealth-core-v5-ex3-v6-state-architecture-v1/run_state_architecture.py`
- `research/wealth-core-v5-ex3-v6-state-architecture-v1/preflight_state_architecture.py`
- `research/wealth-core-v5-ex3-v6-state-architecture-v1/aggregate_state_architecture.py`
- `.github/workflows/wealth-core-v5-ex3-v6-state-architecture-v1.yml`

Pinned adjacent authority and transformation paths:

- `research/wealth-core-v5-sentinel-ex3-v6-adversarial-v1/make_v6_runner.py` at replay-harness authority `eaddca3f04f279e99663f832bf7293e92ee15662`
- `research/wealth-core-v5-sentinel-ex3-v5-adversarial-v1/run_adversarial.py` at the same authority
- `research/wealth-core-v5-sentinel-ex3-impedance-v1/run_impedance.py` at the same authority
- `research/wealth-core-v5-affordability-fix-v1/v5_execution_harness.py` at the same authority
- `research/median5-open-sizing-10bp-ex3-v1/canonical_execution_harness.py` at the same authority
- `.github/actions/v5-ex3-v5-adversarial-setup/action.yml` at the same authority
- `research/median5-fullpit-recertification-v13/experiment_overlay.py` at `1c66096c1e3bd650233c630d4e9f71104ac8fc32`
- `research/wealth-core-v1-buffer-sweep-evidence/arms/10bp/buffer-10bp-generated.py` and `backtester/production_equivalent_economic_overlay.py` at `3dc74a8e54fdfe6e8368a8db3be0ecd127ee4689`
- exact source-level Native and CandidateA transition blocks, close-decision timing, allocation application, pending writes, and output evidence columns.

## Findings and corrections

### 1. Timing-guard incompatibility — fixed

The first implementation replaced the authoritative pending-allocation marker. The inherited causal-timing guard therefore correctly rejected the source before replay. The experiment never produced strategy evidence from that run.

Correction: preserve the authoritative marker exactly once and append the stateless pending write after it. Independent preflight now also verifies source order and rejects any direct same-session `eff[...]` treatment write.

### 2. Replay fan-out occurred before baseline validation — fixed

The initial workflow launched the no-fault baseline and all seven fault cases together. A single harness defect therefore failed all eight jobs.

Correction: execution is now `preflight -> baseline -> seven fault jobs -> aggregate`. The fault fan-out cannot begin until exact current-track economic parity has passed.

### 3. Aggregate evidence parsing was too permissive — fixed

The initial aggregate converted malformed selected-position JSON to an empty set and did not bind every package back to the preflight treatment-source hash and exact fault metadata.

Correction: selected-position evidence is now fail-closed; all 5,032 rows must parse. Every package must have the exact V6 config, research-only contract, treatment-source hash, expected dates and allocation domain. Each LOO case must prove that its excluded security was held in baseline and is absent from the faulted path.

### 4. `state-minimal 60` terminology was too strong — clarified

A 60-session replay window is a bounded-state intervention, not proof that 60 sessions is the mathematically minimal or optimal state representation. Current Sentinel can carry episode/anchor state longer than 60 sessions.

Correction: documentation and aggregate interpretation now call this a **bounded-state proxy**. Its purpose is to test the economic/robustness effect of putting a hard horizon on hidden Sentinel state without inventing new signal thresholds.

## Architecture semantics checked

### Current

- Uses the exact authoritative `Native` and `CandidateA` blocks from selected V6.
- Current Native and CandidateA blocks are byte-compared before execution.
- The current `a_d` close decision remains assigned to `pend['A']`.
- The inherited timing guard remains active.
- The no-fault baseline must reproduce CAGR `0.215572258056`, MDD `-0.273755457386`, and Sharpe `1.1210581190` within the existing tolerance.

### Bounded-state proxy

- Uses exact Native + CandidateA transition code.
- Reconstructs from only the most recent 60 observable sessions.
- History is truncated to exactly the configured bound.
- Synthetic preflight proves that two different older prefixes followed by an identical 60-session suffix produce identical retained history and output.
- No production/current state object is read or mutated.

### Stateless

- Uses exact Native + CandidateA transition code on one current-session observation only.
- No hidden Sentinel state object crosses a call boundary.
- Synthetic preflight proves that an intervening stress call cannot change the output of the same later neutral input.
- Rolling observable features such as R20/R40 remain legal inputs; the intervention removes hidden controller memory, not observable market history.

## Timing semantics checked

The generated source order must be exactly:

1. authoritative Native close decision;
2. authoritative CandidateA close decision;
3. bounded-state close decision;
4. stateless close decision;
5. application of the previous pending allocations to the current measurement session;
6. measurement row emission;
7. authoritative pending writes for the next session;
8. stateless pending write for the next session.

Any same-session write to `eff['A']`, `eff['B']`, or `eff['control']` from the new close decisions is rejected.

## Fault semantics checked

The experiment retains the same six deterministic held-security leave-one-out cases and one deterministic 1% universe dropout (`seed=11`) used in the prior convergence screen. Faults remain upstream in Wealth Core. The controller implementations do not receive the baseline path, future returns, or any future observation.

## Decision rule

No architecture is promoted by this workflow. The result is usable only if:

- preflight passes;
- the current no-fault path reproduces pinned V6 economics;
- all seven deterministic faults pass their integrity checks;
- aggregation passes fail-closed source, metadata, date, holdings, exposure and NAV validation.

Only then should robustness reduction be compared with the economic cost of reducing Sentinel state.
