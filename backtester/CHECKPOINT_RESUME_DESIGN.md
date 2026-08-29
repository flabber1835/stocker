# Exact replay checkpoint/resume contract

Date: 2026-08-28

Scope: `research/backtester` only. Production `main` remains pinned read-only at
`c502d077cae9c494f8b74a41ee8be7f40b25837d` for this experiment family.

## Purpose

GitHub-hosted jobs have a six-hour ceiling. A financially defensible 1998-2026
chronological replay cannot rely on one uninterrupted hosted job. The replay must
be restartable without changing any strategy decision, price, share count,
corporate-action entitlement, controller state, accounting state, or output row.

Checkpoint/resume is therefore an execution transport for one deterministic
chronology. It is not a strategy shortcut and it does not replay prerecorded
holdings or decisions.

## Implementation

Core engine:

- `backtester/checkpoint_runner.py`
- schema: `backtester.replay-checkpoint/1`

A/D v3 launcher:

- `backtester/run_sector_ad_v3_checkpointable.py`

Bounded equivalence launcher:

- `backtester/run_checkpoint_equivalence_base.py`

Certification workflow:

- `.github/workflows/backtester-checkpoint-resume-equivalence.yml`

## Persisted economic state

Each checkpoint contains:

1. Exact A `SessionState.to_dict()` restart image.
2. Exact D/B `SessionState.to_dict()` restart image.
3. `SessionState.state_hash` for both arms.
4. Overlay account state for each arm:
   - NAV
   - effective exposure
   - pending next-open exposure
   - initialization state
   - cumulative transition cost
   - transition count
5. Previous Wealth Core close equity used by next-session overlay accounting.
6. Complete daily output prefix through the checkpoint session.
7. SHA-256 of the canonical daily output prefix.
8. Chronological session pointer, checkpoint session, and exact next session.
9. Strategy identity.
10. Frozen static-input identities.
11. Exact pinned `main` SHA.
12. Exact research runner SHA.
13. Experiment identity and configured replay end.
14. Extra experiment identity for A/D v3:
    - terminal-term JSON hash
    - terminal-term checksum hash
    - split-adjudication JSON hash
    - split-adjudication checksum hash
    - historical terminal-boundary witness state required by v2 provenance

The checkpoint is wrapped in a canonical payload SHA-256 and is also emitted with
a full-file `.SHA256` sidecar.

## State intentionally reconstructed on resume

The following state is derived again from frozen raw input while the normalizer
fast-forwards from 1998-01-02 through the checkpoint session:

- accumulated split factors by permanent security ID
- seen-session counts
- prior signal closes/indexes
- latest historical ticker by security ID
- normalizer price-domain predecessor state
- split-reconciliation stream state
- normalization audit counters

This is safe because these values are deterministic functions of the frozen raw
corpus. Reconstructing them avoids persisting hidden normalizer internals and
causes all source files encountered during fast-forward to be re-hashed through
the ordinary loader.

No production strategy transition is executed during fast-forward. Production
execution resumes strictly on the first session after the checkpoint.

## Resume validation order

A resume fails closed unless all of these match:

1. checkpoint schema
2. checkpoint canonical payload hash
3. checkpoint file SHA-256 sidecar when present
4. experiment ID
5. pinned production-main SHA
6. exact research runner SHA
7. chain start and configured end session
8. strategy identity
9. terminal/split extra identity
10. frozen static-input hashes
11. checkpoint session against current SPY/XNYS session axis
12. exact next-session witness
13. daily-prefix length and final date
14. daily-prefix SHA-256
15. A and D `SessionState.from_dict()` validation
16. restored A and D state hashes
17. Wealth Core parity at the restart boundary

The v3 launcher additionally accepts `--resume-checkpoint-sha256` so a caller can
bind a downloaded checkpoint to an independently transported expected digest.

## Why `SessionState.to_dict()` is authoritative

The pinned production state envelope already owns restart semantics. Its restart
image preserves path-dependent portfolio/controller/LD-RC state and bounds feed
history to the required deterministic restart window while retaining protected
security anchors. Resume uses production `SessionState.from_dict()` and verifies
its state hash after reconstruction.

The backtester does not invent a parallel serialization of Wealth Core or
Sentinel state.

## Output semantics

A checkpointing segment emits no CAGR/Sharpe/headline result bundle.

Only the final segment writes the ordinary complete replay outputs. The output
format is deliberately unchanged so checkpointed execution can be compared
byte-for-byte with uninterrupted execution.

## Equivalence certification

Workflow `backtester-checkpoint-resume-equivalence.yml` runs the same bounded
chronology twice:

A. uninterrupted from 1998-01-02 through 1998-06-30

B. 1998-01-02 through 1998-03-31, write checkpoint, restore checkpoint, then
continue through 1998-06-30

It requires byte equality for:

- `daily.csv.gz`
- `metrics.csv`
- `summary.json`

The bounded equivalence run alone may suppress the final full-history split audit
because that audit necessarily contains events outside the bounded window. The
simulated session economics and normalizer behavior inside the bounded window are
unchanged.

Checkpoint/resume is not certified for promotion until this workflow is green.

## Proposed full PIT segmentation

After the remaining split and held-terminal gaps are closed, run checkpointable
A/D v3 under one immutable research runner SHA with approximately four-year
segments:

1. 1998-01-02 -> 2001-12-31
2. 2002-01-02 -> 2005-12-30
3. 2006-01-03 -> 2009-12-31
4. 2010-01-04 -> 2013-12-31
5. 2014-01-02 -> 2017-12-29
6. 2018-01-02 -> 2021-12-31
7. 2022-01-03 -> 2025-12-31
8. 2026-01-02 -> 2026-07-31 finalization

Exact boundaries must be members of the frozen replay session axis. The final
orchestration should choose the nearest valid session if a listed calendar date
is not present.

Each segment must run comfortably below the six-hour GitHub job ceiling. The
fast-forward normalization cost is acceptable because it is much smaller than
strategy execution and independently re-verifies the frozen corpus on every
resume.

## Final PIT acceptance gates

Checkpoint/resume solves only hosted-runtime continuity. A final v3 result is
certifiable only after all existing economic gates also pass:

- no economically unresolved held terminal event
- all materially reachable split conflicts have causal dispositions
- exact terminal settlement terms
- exact next-open allocation accounting
- strict-prior SEC SIC -> FF12 D grouping
- A/D Wealth Core parity every session
- frozen input hashes
- pinned production-main SHA
- pinned research runner SHA
- complete 1998-01-02 through 2026-07-31 chronology
- final normalization audit
- immutable result bundle and output hashes

## Prohibited restart shortcuts

A checkpoint implementation must never:

- save or replay future strategy decisions
- save future holdings/trades
- skip market sessions
- substitute closes for missing opens
- fabricate corporate-action terms
- change the universe or eligibility rules
- reduce the historical lookback required by production state
- project current metadata backward
- continue after a state/input hash mismatch
- resume under a different runner SHA
- resume under a different production-main SHA

Any such change creates a different experiment and invalidates PIT certification.
