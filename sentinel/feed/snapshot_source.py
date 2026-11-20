"""Read archived table rows with an independent completeness witness.

TICKERS row values distinguish a missing field from an explicitly empty field.
A separately captured export authenticates only its complete set of keys.
Historical ACTIONS removal requires the corresponding complete export.
"""
from __future__ import annotations

from typing import Mapping

from sentinel.feed import archive_tables, snapshot_export


def fetch_table(table: str, params: Mapping[str, str] | None = None):
    """Read captured rows and check the complete TICKERS key set."""
    rows = archive_tables.fetch_table(table, params)
    if table != archive_tables.TICKERS:
        return rows

    # Materialize only TICKERS (~identity cardinality, not price history). The
    # same rows are later fingerprinted/bracketed by coherence.StableTableFetch.
    paged = list(rows)
    export_keys, _evidence = snapshot_export.fetch_complete_ticker_keys()
    snapshot_export.assert_complete_ticker_keys(paged, export_keys)
    return iter(paged)


__all__ = ["fetch_table"]
