"""Production Sharadar source membrane above the strict paginated transport.

SEP/SFP/ACTIONS values continue through :mod:`sentinel.feed.sharadar`. TICKERS
adds one independent negative-space proof: the paginated response's `table=SEP`
identity keys must equal a current vendor whole-table export.

The export is deliberately *not* used as TICKERS metadata authority. CSV cannot
preserve Sharadar's semantic distinction between a nullable field and an
observed empty string; Sentinel needs that distinction for `relatedtickers`
carry-forward versus authoritative clearing. The paginated JSON remains the
field-value source while the exporter answers only "did pagination omit a row?".

ACTIONS removal authority is handled separately by maintenance's daily complete
export reconciliation. Its ordinary daily window may be used for candidate
normalisation, but cannot by itself earn negative-space authority.
"""
from __future__ import annotations

from typing import Mapping

from sentinel.feed import sharadar, snapshot_export


def validate_config() -> None:
    sharadar.validate_config()
    snapshot_export.validate_config()


def _export_kwargs(kwargs: dict) -> dict:
    """Share deterministic transport seams without leaking pagination-only args."""
    return {key: value for key, value in kwargs.items()
            if key in {"http", "sleep", "now"}}


def fetch_table(table: str, params: Mapping[str, str] | None = None, **kwargs):
    """Fetch through strict pages; add whole-export key authority for TICKERS."""
    rows = sharadar.fetch_table(table, params, **kwargs)
    if table != sharadar.TICKERS:
        return rows

    # Materialize only TICKERS (~identity cardinality, not price history). The
    # same rows are later fingerprinted/bracketed by coherence.StableSharadarFetch.
    paged = list(rows)
    export_keys, _evidence = snapshot_export.fetch_complete_ticker_keys(
        **_export_kwargs(dict(kwargs)))
    snapshot_export.assert_complete_ticker_keys(paged, export_keys)
    return iter(paged)


__all__ = ["fetch_table", "validate_config"]
