# Context checkpoint 09 — exact checkpoint/resume implementation

Date: 2026-08-28 PT

## Objective

Remove the GitHub-hosted six-hour job ceiling as a blocker for the authoritative
1998-01-02 -> 2026-07-31 causal/PIT A/D replay and the comprehensive terminal-gap
scan, without changing economics.

## Implemented

### Generic replay checkpoint engine

`backtester/checkpoint_runner.py`

Schema: `backtester.replay-checkpoint/1`

The engine persists:

- canonical A `SessionState.to_dict()`
- canonical D/B `SessionState.to_dict()`
- A/D production state hashes
- A/D overlay NAV/effective/pending state
- transition count/cost state
- prior Wealth Core close equity
- complete daily output prefix
- canonical daily-prefix SHA-256
- session pointer/checkpoint session/exact next session
- strategy identity
- frozen static input hashes
- exact production-main SHA
- exact research runner SHA
- experiment ID and configured end session
- experiment-specific extra identity

The outer checkpoint has a canonical payload SHA-256 plus a whole-file `.SHA256`
sidecar.

Resume restores production states only through pinned-main
`SessionState.from_dict()`, rechecks both state hashes, and requires Wealth Core
A/D parity at the checkpoint boundary.

The normalizer is deterministically re-run from 1998-01-02 through the checkpoint
session. This reconstructs raw-derived split/identity/feed-anchor bookkeeping from
frozen source data. Production strategy execution is skipped during that
fast-forward and restarts only on the exact next session.

### A/D v3 integration

`backtester/run_sector_ad_v3_checkpointable.py`

This composes:

- exact pinned main `c502d077cae9c494f8b74a41ee8be7f40b25837d`
- A/D v2 causal terminal terms
- v3 primary-source split adjudications
- the generic checkpoint engine

The launcher binds terminal/split JSON and checksum hashes into each checkpoint.
It also preserves the v2 historical 2001-06-04 terminal-boundary provenance
witness across restarts.

It accepts `--resume-checkpoint-sha256` to bind a transported checkpoint file to
an independently supplied expected digest.

A non-final segment emits a checkpoint only. The final resumed segment emits the
ordinary complete v3 result bundle and then runs the normal v2/v3 provenance
postprocessing.

### Equivalence harness

`backtester/run_checkpoint_equivalence_base.py`

Workflow:

`.github/workflows/backtester-checkpoint-resume-equivalence.yml`

Test design:

- uninterrupted 1998-01-02 -> 1998-06-30
- segmented 1998-01-02 -> 1998-03-31 checkpoint -> resume -> 1998-06-30
- exact same main SHA
- exact same research SHA
- byte compare `daily.csv.gz`, `metrics.csv`, `summary.json`

The first workflow attempt, run `#33228492784`, failed before executing any replay
logic because direct Python script execution did not place the repository root on
`sys.path`. `ModuleNotFoundError: No module named 'backtester'` occurred in the
launcher import. No economic code ran.

Import-root fixes:

- bounded equivalence launcher commit `da78b3a26f3b4017b1748a808a03ae12e3705075`
- v3 checkpoint launcher commit `450006ab1794c25ab233fbb1536b9124ced630bd`

Corrected equivalence run:

- run `#33228577567`
- current state at this checkpoint: `in_progress`
- setup/compile passed
- uninterrupted control step is running

Checkpoint/resume is NOT yet certified until this workflow is green.

## Documentation

Full design contract:

`backtester/CHECKPOINT_RESUME_DESIGN.md`

Commit creating the document:

`be463ed377cfa42e9a0321696dbf88cd0b35f8e0`

It records:

- persisted fields
- reconstructed fields
- validation order
- checkpoint hash rules
- segment behavior
- proposed approximately four-year segmentation
- final PIT acceptance gates
- prohibited restart shortcuts

## Proposed final segmentation

After remaining data defects are closed and checkpoint equivalence is green:

1. 1998-01-02 -> 2001-12-31
2. 2002-01-02 -> 2005-12-30
3. 2006-01-03 -> 2009-12-31
4. 2010-01-04 -> 2013-12-31
5. 2014-01-02 -> 2017-12-29
6. 2018-01-02 -> 2021-12-31
7. 2022-01-03 -> 2025-12-31
8. 2026-01-02 -> 2026-07-31 finalization

Exact boundaries must be checked against the frozen replay session axis.

## Related current status

Previously established:

- full split population = 128 unresolved under frozen main
- four primary-source split adjudications verified
- full-corpus adjudicated normalization = 46,238,394 bars through 2026-07-31,
  exact 128 -> 124 reduction
- complete split-window classification:
  - 44 shifted direct
  - 4 shifted inverse
  - 3 exact inverse
  - 66 no-transition/no-nearby-match
  - 11 genuine price-domain conflicts
- after four certified genuine-conflict repairs, seven genuine conflicts remain
- causal terminal bundle currently includes LIT1, CIT.A -> TYC, and GPU
- shared-Wealth-Core reuse is economically byte-identical over 252 sessions but
  current deep-copy implementation is slower than baseline
- original unresolved-open scanner reached 2009-01-09 before GitHub six-hour
  cancellation; GPU 2001-11-14 was the only logged unresolved-open transition
  through that point
- comprehensive held-terminal-gap scanner and legacy A/D v2 replay were still
  running at the prior status check

## Next steps

1. Require corrected checkpoint equivalence `#33228577567` to complete green.
2. If green, add a second stateful equivalence boundary after the strategy has
   active holdings/exposure history in late 1998.
3. Add/verify operational segmented v3 workflow using one immutable runner SHA.
4. Apply the same checkpoint transport to the comprehensive terminal-gap scanner.
5. Resolve the seven genuine split conflicts and any terminal gaps found.
6. Run the final checkpointed A/D v3 chronology and certify the resulting bundle.

Production `main` remains untouched.
