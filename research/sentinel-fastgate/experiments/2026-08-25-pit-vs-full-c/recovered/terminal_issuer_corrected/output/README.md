# Sentinel 1.1 — Terminal + Issuer Identity Corrected

This package supersedes the earlier terminal-order-corrected standalone reference. It includes both corrections:

- atomic terminal-action / pending-entry reconciliation;
- certified Sharadar `relatedtickers` parsing and duplicate-economic-issuer prevention.

`sentinel_1p1_standalone.py` remains oracle-free strategy code: runtime strategy inputs are raw Sharadar SEP, TICKERS, ACTIONS and SFP files.

See `ISSUER_CORRECTION_REPORT.md`, `VALIDATION.json`, `trailing_scorecard_vs_spy.csv`, and `issuer_correction_trade_diff.csv`.
