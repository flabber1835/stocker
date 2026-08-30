# PIT input data

Purpose: become the complete historical point-in-time input set for day-by-day Orion CAGR replay.

## Current strict-PIT certification use

Phase 1 is now an upstream source layer for the canonical certification dataset.
Research and production do not consume these files independently during strict
certification. `backtester/canonical_pit_dataset.py` verifies them, combines them
with strict-prior SEC evidence and frozen adjudications, and emits one immutable
artifact used by both engines.

Start with
[`backtester/STRICT_PIT_CERTIFICATION_RUNBOOK.md`](../backtester/STRICT_PIT_CERTIFICATION_RUNBOOK.md)
and
[`backtester/CANONICAL_PIT_DATASET_DESIGN.md`](../backtester/CANONICAL_PIT_DATASET_DESIGN.md).

The current 2006-2007 diagnostic artifact is reproducible from committed,
hash-pinned sources and has dataset hash
`08db292b78f0968b149ec033671b5c5df62ad98a4b2692bcc5dfa575585fa4e6`.
The artifact itself is generated and uploaded by the strict-PIT workflow.

## Phase 1: already-PIT source fields

Validated dataset generated from the supplied Sharadar files:
- SEP 1998–2026: `ticker,date,volume,closeunadj`
- ACTIONS: `date,action,ticker,value`
- SFP: SPY and BIL only, `ticker,date,volume,closeunadj`

Fail-closed exclusions:
- SEP/SFP adjusted or split-adjusted price fields (`open,high,low,close,closeadj`)
- `lastupdated`
- all TICKERS snapshot fields
- ACTIONS descriptive/contra metadata (`name,contraticker,contraname`) until separately proven PIT or reconstructed

No reconstructed fields are included yet.

`MANIFEST.csv` pins the exact validated output files, row counts, sizes, output SHA-256 hashes, source files, and source SHA-256 hashes. `build_phase1_pit.py` is the deterministic fail-closed extraction recipe.

## GitHub runner

`.github/workflows/orion-build-pit-input.yml` is the supported repository-side population path for this phase and is restricted to branch `research/sentinel-fastgate-2026-08-24`.

Because a `workflow_dispatch` workflow is only exposed by GitHub when its workflow file also exists on the default branch, this research-only workflow has a branch-scoped `push` trigger. Main remains untouched. A push that changes the pinned Sharadar source files, source chunks, manifest, or builder starts the extraction.

The runner:
1. validates every raw source against the source SHA-256 pinned in `MANIFEST.csv`;
2. builds all 31 PIT-only gzip files in a temporary closed-world directory;
3. requires every output row count, byte count, header, and SHA-256 to match `MANIFEST.csv` exactly;
4. copies only those 31 manifest-listed files into this directory;
5. rejects raw Sharadar archives, TICKERS, adjusted-price fields, current metadata fields, or any unlisted data file;
6. commits only the validated `*_PIT_ONLY.csv.gz` outputs back to the research branch.

The generated-output commit does not retrigger the workflow because the push path filter excludes `PIT input data/*.csv.gz`.

### Large SFP source

The pinned `SHARADAR_SFP.zip` is about 285 MB, above GitHub's normal 100 MB single-file limit. The workflow therefore supports a split source on the research branch:

`sharadar/SHARADAR_SFP.zip.part-000`, `...part-001`, and so on.

It concatenates the parts only inside the ephemeral runner workspace. The reassembled archive must hash exactly to the `source_sha256` in `MANIFEST.csv`; otherwise the build stops. The raw reassembled archive is never added to `PIT input data` and is never included in the runner commit.

The same split mechanism is supported for `SHARADAR_ACTIONS.zip`, although that archive is small enough to commit whole.

## Current source status

SEP 1998–2026 is present on the research branch and byte-pinned. The run intentionally fails until the exact hash-pinned ACTIONS source and either the whole SFP source or all of its split parts are present. To avoid intentionally failed intermediate runs, stage ACTIONS plus every SFP part in one commit/push.

## Completion criterion

This directory is a complete Phase-1 replay input only when all 31 manifest-listed `.csv.gz` files are present and hash-match `MANIFEST.csv`. Until then it is incomplete and must not be used as a certified replay input.
