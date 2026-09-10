# Pre-run code review — Sentinel state-component ablation v1

## Scope reviewed

- exact V6 source-generation chain and selected-source hash guard;
- additive telemetry insertion seams;
- authoritative Native and CandidateA source preservation;
- close-decision / next-open allocation timing;
- independent current-Sentinel replay;
- variant-specific Native/effective-Native timing;
- all six one-component ablation transforms;
- Wealth Core leave-one-out and deterministic 1% dropout injection;
- baseline/current parity gate;
- evidence packaging and aggregate validation.

## Design decisions

The experiment does **not** add six live controllers to the engine. The engine executes the exact current Sentinel path and emits additional causal observation telemetry. After the engine finishes, the harness independently replays the authoritative current controller and the six ablations from that tape.

This is safer because:

- Wealth Core executes only once per fault;
- the current Sentinel execution path is not replaced or rerouted;
- the independent replay must match current allocation, NAV, Native target, effective-Native state, and reason before ablations are accepted;
- all variants share exactly the same Wealth Core observations and execution returns.

## Fail-closed controls

- exact V6 selected source must hash to `335e2ae06efd5e2ebfa11f0641029609d524f4e75e733a3dbd0a5efcf64ac42d` before instrumentation;
- authoritative Native and CandidateA class blocks must remain byte-identical after telemetry instrumentation;
- inherited causal-timing guard must still pass;
- telemetry seams must be unique;
- every ablation class transform must be unique and compile;
- synthetic state tests require every variant to remain in the legal exposure domain `{0, .55, .65, 1}`;
- full-PIT baseline is blocked behind the cheap preflight;
- all fault jobs are blocked behind baseline parity;
- aggregation requires exactly one baseline and all seven uniquely indexed cases with the same instrumented source hash and exact 5,032-session horizon.

## Ablation semantics reviewed

- `native_base_anchor`: removes only carried anchor history; duration and all other Native state remain.
- `native_base_duration`: removes elapsed duration memory by satisfying the duration gate whenever base is active; anchor and other predicates remain.
- `native_slow_persistence`: slow trigger remains; only post-trigger slow persistence/recovery age is removed.
- `native_recovery_ramp`: severe-state entry remains; only 55%/65% recovery-ramp persistence is removed.
- `ex3_episode_memory`: CandidateA episode entry/hold memory is disabled; divergence latch remains.
- `ex3_latch_memory`: CandidateA divergence-latch entry is disabled; episode recovery remains.

These are deliberately causal deletions, not production redesigns. Large economic changes are evidence that the removed state is economically important, not proof that the ablation itself is desirable.

## Pre-run verdict

No known blocker remains in the static design. The campaign is authorized to proceed only if the independent preflight passes; no economic result is accepted unless the full baseline reproduces the current V6 economics and the offline current replay matches the engine.
