# Context checkpoint 2026-08-28 11

Branch: `research/backtester`

Pinned production main for this experiment family:
`c502d077cae9c494f8b74a41ee8be7f40b25837d`

## Checkpoint/resume certification run #33228577567

The corrected checkpoint/resume workflow completed all three execution phases successfully:

1. uninterrupted control through 1998-06-30 — success
2. first segment through 1998-03-31 and checkpoint write — success
3. resume from 1998-03-31 checkpoint through 1998-06-30 — success

Checkpoint evidence:

- checkpoint session: `1998-03-31`
- exact next session: `1998-04-01`
- checkpoint file SHA-256: `83bfda7d7167c7356f08d7398b3a66f0db908bc8d622f50fd41b544a5dc064a4`
- both production state hashes were present and validated
- deterministic input fast-forward completed before production execution resumed

The final byte-equivalence step failed because `daily.csv.gz` column order changed after JSON checkpoint round-trip. The checkpoint envelope is serialized with sorted JSON keys, so each checkpointed daily-row dictionary is reloaded in alphabetical key order. Pandas then uses that key order when constructing the resumed DataFrame.

Independent artifact inspection established:

- uninterrupted daily columns:
  `date,A_nav,B_nav,SPY_level,wealth_core_equity,A_allocation,B_allocation,A_native,B_native,A_damaged,B_damaged,green`
- resumed daily columns:
  `A_allocation,A_damaged,A_native,A_nav,B_allocation,B_damaged,B_native,B_nav,SPY_level,date,green,wealth_core_equity`
- row count: 124 in both
- after reindexing resumed columns to uninterrupted canonical order, `DataFrame.equals(...) == True`
- maximum absolute numerical difference for every numeric column = `0.0`
- `metrics.csv` is already byte-identical
- `summary.json` is already byte-identical

Therefore this failure is a deterministic output-serialization defect, not an economic/state restart divergence.

Required repair: preserve one explicit canonical daily-column schema across fresh and resumed output, then rerun #33228577567-equivalent and require byte-identical `daily.csv.gz`, `metrics.csv`, and `summary.json`.

## A/D v2 run #33210946520

Run completed with failure after progressing past 2007-07-11.

Last printed checkpoint before failure:

- session `2007-07-11`
- sessions `2394`
- A multiple `5.8454889361`
- D multiple `5.8454889361`
- running A/D CAGR `20.3790533354%`

The run then failed at a later session with:

`RuntimeError: A allocation transition coincides with unresolved Wealth Core open; exact next-open attribution is impossible`

This is a new unresolved-open/corporate-action boundary after 2007-07-11. The exact session/security was not printed by the v2 exception path. It should be identified by the comprehensive held-terminal-gap scanner and added to the causal terminal repair queue.

No A/D headline result from this run is authoritative.

## Comprehensive held-terminal-gap scanner #33211049538

Still running as of this checkpoint. It remains the preferred source for the exact new unresolved held security and any additional held terminal gaps.

## Six-hour solution implementation

Built on `research/backtester`:

- `backtester/checkpoint_runner.py`
- `backtester/run_sector_ad_v3_checkpointable.py`
- `.github/workflows/backtester-v3-checkpointed-full-replay.yml`
- `.github/workflows/backtester-v3-segment-worker.yml`
- `backtester/diagnostics/scan_all_held_terminal_gaps_checkpointable.py`
- `.github/workflows/backtester-held-terminal-gap-checkpointed-full.yml`
- `.github/workflows/backtester-held-terminal-gap-segment-worker.yml`
- `backtester/CHECKPOINT_RESUME_DESIGN.md`

Manual segmented workflows remain gated on checkpoint equivalence certification and remaining PIT data repairs.

## Immediate continuation

1. Fix canonical daily CSV column order in checkpoint runner.
2. Rerun uninterrupted-vs-resumed equivalence and require byte identity.
3. Run the second stateful equivalence window after positions/controller state are active.
4. Consume held-terminal scanner evidence and repair the newly encountered post-2007 unresolved-open boundary.
5. Continue split-conflict adjudication.
6. Only then run the full segmented v3 PIT replay.
