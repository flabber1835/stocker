# Sentinel 1.1 terminal-order corrected replay

This package contains a raw-Sharadar standalone replay with the terminal corporate-action ordering defect corrected.

Important files:
- `sentinel_1p1_standalone.py` — corrected standalone source
- `sentinel_1p1_summary.json` — corrected headline metrics
- `sentinel_1p1_daily.csv` — corrected 20-year Sentinel path
- `terminal_pending_entry_blocks.csv` — pending entries cancelled due to terminal status
- `terminal_close_admission_blocks.csv` — terminal securities excluded from same-close admissions
- `executed_buys.csv` — all corrected Wealth Core buys
- `ending_holdings_named.csv` — current endpoint Wealth Core book with company names
- `allocation_path_differences.csv` — sessions where corrected Sentinel allocation differs from prior raw reference
- `VALIDATION.json` — machine-readable validation results
- `CORRECTION_REPORT.md` — human-readable audit report
- `SHA256SUMS.txt` — artifact hashes

Raw Sharadar data is not included.
