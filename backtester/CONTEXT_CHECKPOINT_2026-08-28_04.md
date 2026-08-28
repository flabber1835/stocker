# Backtester continuation checkpoint — 2026-08-28 #04

This is an incremental continuation from `CONTEXT_CHECKPOINT_2026-08-28_03.md`.

## Shared Wealth Core equivalence harness

Run `33210057040` failed after completing the 252-session baseline through 1998-12-31. The economic path itself completed and ended at A=B=1.097576x. Runtime was 1755.62 seconds. The failure occurred only in the base runner's final unresolved-split audit: 19 split reconciliation conflicts were present in the deliberately bounded 1998 replay. The optimized arm never started, so this run supplied no evidence about optimization correctness.

Root cause of the failed audit bypass: `SPLIT_UNRESOLVED` is imported locally inside `run.py::main()`. Assigning `runner.SPLIT_UNRESOLVED` from the harness cannot affect that local import.

Fix commit: `26c507a2d42ac30783ac1d06d9447e83d89bf129`.

The equivalence workflow now modifies only its ephemeral checked-out copy of `backtester/experiments/2026-08-27-sector-abc/run.py`, adding an environment-gated condition around the final post-session split audit. Both baseline and accelerated arms set `BACKTESTER_EQUIV_IGNORE_FINAL_SPLIT_AUDIT=1`. The patch occurs after checkout inside the workflow and is not committed to the production/base runner. All 252 chronological sessions, normalization, strategy transitions, holdings, prices, decisions, and overlay accounting remain unchanged. Only the final audit that previously prevented output serialization is bypassed for this bounded equivalence test.

Corrected equivalence run: `33213523888`, job `98991973412`.

Acceptance remains strict: baseline and optimized `daily.csv.gz` and `metrics.csv` must compare byte-for-byte, and the daily SHA256 must match. No speedup claim is valid until this passes.

## Split conflicts discovered by bounded equivalence

The bounded 1998 baseline reported 19 unresolved split reconciliations. First examples:

- ENZB 1998-01-07 stated 1.05, derived 1.0
- OATS 1998-01-08 stated 1.5, derived 1.0
- EPAC 1998-02-03 stated 2.0, derived ~1.0000028673
- ALBC 1998-02-05 stated 3.0, derived 1.0
- CB 1998-03-03 stated 3.0, derived 1.0

These are a separate economic-integrity question from the acceleration test. The bounded test may legitimately finish with unresolved corpus certification because it is intentionally truncated; however any unresolved split that affects a held security can alter strategy economics. Do not dismiss these 19 events as harmless without checking whether they intersect Wealth Core holdings/admissions and whether later evidence resolves them in the full replay.

## Active runs

- A/D v2 full replay with current GPU repair: run `33210946520`, job `98983779472`, status in progress at this checkpoint.
- Original allocation-transition unresolved-open scanner: run `33196508963`, job `98934905157`, status in progress.
- Comprehensive held-terminal-gap scanner: run `33211049538`, job `98984067249`, status in progress. This is the preferred terminal-gap evidence because it records every held unresolved open, even when Sentinel exposure does not change.
- Corrected shared-Wealth-Core equivalence: run `33213523888`, job `98991973412`, status in progress.

GitHub live-job log blobs for the three long-running jobs continue to return temporary BlobNotFound 404s, so simulated-date progress must not be invented.

## Current terminal bundle

LIT1, CIT.A->TYC, and GPU settlement economics are production-verified. GPU no-election treatment is $36.50 cash/share; 204,677 diagnostic shares settle to exactly $7,470,710.50 and the holding is extinguished. GPU evidence availability is tightened to the prior close, 2001-11-06. Current terminal bundle verification is green.

## Next actions

1. Let corrected equivalence run complete. If byte-identical, measure observed speedup and approve shared-Wealth-Core computation reuse for subsequent A/D research runs.
2. Consume comprehensive held-terminal-gap scanner artifact when available and source/encode every economically relevant unresolved corporate action before trusting a full replay.
3. Examine unresolved split events for intersection with held securities and resolve any economically active conflicts before certifying final CAGR.
4. Keep the current unaccelerated A/D replay as continuity evidence while the optimization is being certified; do not replace its output with an accelerated result until equivalence passes.
5. Production `main` remains untouched by all work in this checkpoint.
