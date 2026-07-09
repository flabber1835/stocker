"""Vendored, byte-identical copies of the deterministic math the live chain uses.

The backtester's config-replay (G1) must re-rank and re-select under a candidate
config using the SAME code the production pipeline + portfolio-builder run — a
re-implementation would silently drift and make the evaluator tool untrustworthy.
At container runtime a service image only ships its own `app/`, so the backtester
cannot import the sibling services' modules; we copy them here instead.

Sources (kept in sync by tests/backtester/test_vendor_sync.py, which fails CI if a
copy diverges even by one byte):
  rank.py   ← services/pipeline/app/rank.py
  regime.py ← services/pipeline/app/regime.py
  select.py ← services/portfolio-builder/app/select.py

These modules import ONLY numpy/pandas/math + stock_strategy_shared (all present in
stocker-base), so the copies import cleanly with no sibling-service dependency.

To update: re-copy the source file verbatim; never hand-edit a vendored copy.
"""
