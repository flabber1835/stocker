"""Vendored, byte-identical copy of the pipeline's ranking math.

The evaluator's preview_ranking tool re-ranks a date under a candidate config
using the SAME rank_universe the production pipeline runs — a re-implementation
would drift and make the preview lie. Service images ship only their own app/,
so the module is copied here; tests/evaluator/test_vendor_sync.py fails CI if
this copy diverges by one byte. rank.py imports only pandas +
stock_strategy_shared, so it loads cleanly in the evaluator container.

To update: re-copy the source verbatim; never hand-edit.
"""
