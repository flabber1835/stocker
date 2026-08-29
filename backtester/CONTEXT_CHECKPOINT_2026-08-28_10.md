# Context checkpoint 10 — six-hour timeout solution implemented

Date: 2026-08-28 PT

## What is now implemented

### Exact replay checkpoint/resume

Core:
- `backtester/checkpoint_runner.py`
- schema `backtester.replay-checkpoint/1`

Checkpoint-capable final replay launcher:
- `backtester/run_sector_ad_v3_checkpointable.py`

The checkpoint is self-hashed and includes canonical production A/D state,
production state hashes, overlay-account state, prior Wealth Core close, output
prefix, session pointer/next session, strategy identity, frozen input identity,
main SHA, research SHA, and terminal/split extension identity.

Resume re-normalizes frozen raw Sharadar history through the checkpoint session,
restores production state through `SessionState.from_dict()`, verifies state
hashes and Wealth Core parity, then executes production only from the exact next
session.

### Checkpoint equivalence certification

Workflow:
- `.github/workflows/backtester-checkpoint-resume-equivalence.yml`

Control:
- uninterrupted 1998-01-02 -> 1998-06-30

Restarted path:
- 1998-01-02 -> 1998-03-31
- write exact checkpoint
- restore
- continue -> 1998-06-30

Required equality:
- `daily.csv.gz` byte-identical
- `metrics.csv` byte-identical
- `summary.json` byte-identical

First attempt `#33228492784` failed before replay due launcher import-path
plumbing (`ModuleNotFoundError: backtester`). No economic code ran.

Import fixes:
- equivalence launcher `da78b3a26f3b4017b1748a808a03ae12e3705075`
- v3 launcher `450006ab1794c25ab233fbb1536b9124ced630bd`

Corrected equivalence:
- run `#33228577567`
- last checked: `in_progress`
- setup and compile green
- uninterrupted control executing

Checkpoint/resume is not yet called certified until the byte-comparison step is
green.

### Operational checkpointed full v3 replay

Reusable worker:
- `.github/workflows/backtester-v3-segment-worker.yml`
- commit `c9d7d3ca3a2b83aec4f0e076f6c8666bd672a678`

Manual orchestration:
- `.github/workflows/backtester-v3-checkpointed-full-replay.yml`
- commit `ef0a6a2530c19b228cdcf5a6b748e30e8442c441`

Eight sequential jobs:
1. 1998-01-02 -> 2001-12-31
2. -> 2005-12-30
3. -> 2009-12-31
4. -> 2013-12-31
5. -> 2017-12-29
6. -> 2021-12-31
7. -> 2025-12-31
8. -> 2026-07-31 final

All segments bind one immutable `${{ github.sha }}` as the research runner SHA and
exact main `c502d077...`.

Checkpoint transport:
- `actions/cache@v5` pinned commit
  `caa296126883cff596d87d8935842f9db880ef25`
- unique cache key per segment/run
- checkpoint SHA passed independently as reusable-workflow output
- receiving job verifies SHA before loading checkpoint
- every non-final checkpoint is also uploaded as an Actions artifact for evidence
- cache is transport; artifact is evidence

Each worker timeout is 330 minutes, leaving margin under the six-hour hosted-job
ceiling.

The full replay is `workflow_dispatch` only and has not been launched. It remains
gated on checkpoint equivalence plus the remaining PIT data repairs.

## Comprehensive held-terminal-gap scanner is also checkpointable

New scanner:
- `backtester/diagnostics/scan_all_held_terminal_gaps_checkpointable.py`
- initial commit `adcecf921be60a5215c9c1489690aeaeba0b4727`
- v3-alignment update `484ca3dcb2673ff8427da3898e9ab560d309bd80`

It uses:
- the same causal terminal bundle as v3
- the same current four primary-source split adjudications as v3
- A-only production execution with the second arm collapsed to the exact A result
- generic production SessionState checkpoint transport

Scanner-specific checkpoint extension persists:
- every captured gap episode
- first/last unresolved session and count
- collision sessions
- terminal pending/unresolved evidence
- diagnostic overlay invalid-from session
- cumulative production transition/collapse counts

On resume the extension is read from a validated checkpoint, the episode index is
rebuilt, and new sessions append to the existing evidence.

The scanner intentionally delegates the final unresolved-split verdict to the
separate full-corpus split certification. This allows terminal-gap evidence to be
completed even while split research remains open. Its production chronology uses
the currently adjudicated v3 split layer.

Reusable scanner worker:
- `.github/workflows/backtester-held-terminal-gap-segment-worker.yml`
- commit `b13975b848208b2ac0c479cedfe2ca4930eeb836`

Manual full scanner orchestration:
- `.github/workflows/backtester-held-terminal-gap-checkpointed-full.yml`
- commit `a94f5edc1e3fcb0a8fdca339751d00f82d1eb1ad`

It uses the same eight chronological boundaries and checkpoint transport model.
It has not been launched yet.

## Documentation

Primary design document:
- `backtester/CHECKPOINT_RESUME_DESIGN.md`
- initial commit `be463ed377cfa42e9a0321696dbf88cd0b35f8e0`
- operational transport update `83bea59619be8467412fdb92ca3f4787b073aacc`

Prior implementation checkpoint:
- `backtester/CONTEXT_CHECKPOINT_2026-08-28_09.md`
- commit `67462e07bc15aff5512ebe1dfbcd864fd27ead13`

## Existing data gates still apply

Checkpointing solves runtime continuity only.

Current split state:
- 128 original unresolved split conflicts
- 4 primary-source adjudications certified
- full-corpus 128 -> 124 reduction verified across 46,238,394 bars
- classification: 44 shifted direct, 4 shifted inverse, 3 exact inverse,
  66 no-transition/no-nearby-match, 11 genuine price-domain conflicts
- 7 genuine price-domain conflicts remain after the four certified repairs

Current terminal state:
- LIT1, CIT.A -> TYC, GPU repaired and verified
- old one-job terminal scanner could not finish before six-hour cutoff
- checkpointed scanner exists specifically to complete this population safely

## Acceptance before authoritative PIT metrics

Do not launch/certify the final full v3 result until:
1. checkpoint uninterrupted-vs-resumed equivalence is green
2. a second stateful checkpoint equivalence after active strategy history is green
3. remaining seven genuine split conflicts are dispositioned
4. checkpointed held-terminal-gap scan completes and all economic gaps are repaired
5. full v3 eight-segment chronology completes through 2026-07-31
6. final normalization, Wealth Core parity, terminal, split, identity, timing, and
   immutable output-hash gates pass

Production `main` remains untouched.
