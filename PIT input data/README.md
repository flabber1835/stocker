# PIT input data

Purpose: become the complete historical point-in-time input set for day-by-day Orion CAGR replay.

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

`.github/workflows/orion-build-pit-input.yml` is the only supported repository-side population path for this phase. It is manual and restricted to branch `research/sentinel-fastgate-2026-08-24`.

The runner:
1. validates every raw source against the source SHA-256 pinned in `MANIFEST.csv`;
2. builds all 31 PIT-only gzip files in a temporary closed-world directory;
3. requires every output row count, byte count, header, and SHA-256 to match `MANIFEST.csv` exactly;
4. copies only those 31 manifest-listed files into this directory;
5. rejects raw Sharadar archives, TICKERS, adjusted-price fields, current metadata fields, or any unlisted data file;
6. commits only the validated `*_PIT_ONLY.csv.gz` outputs back to the research branch.

The run intentionally fails until the exact hash-pinned `SHARADAR_ACTIONS.zip` and `SHARADAR_SFP.zip` sources are present in the repository (normally under `sharadar/`). SEP 1998–2026 is already present on the research branch.

## Completion criterion

This directory is a complete Phase-1 replay input only when all 31 manifest-listed `.csv.gz` files are present and hash-match `MANIFEST.csv`. Until then it is incomplete and must not be used as a certified replay input.
