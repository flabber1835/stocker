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

`MANIFEST.csv` records the exact validated output files, row counts, sizes, output hashes, source files, and source hashes. `build_phase1_pit.py` is the deterministic extraction recipe.

## Persistence status

The validated binary dataset is 472,851,520 bytes across 31 `.csv.gz` files (46,931,241 data rows). The current GitHub connector cannot stream local binary files into GitHub, so the data bytes themselves are not yet committed. This directory therefore must not be treated as a complete replay input until every manifest-listed data file is present and hash-matches the manifest.
