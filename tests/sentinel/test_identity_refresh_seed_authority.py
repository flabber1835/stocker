"""Seed/reseed must reject ambiguous permanent identity before writing history."""
from __future__ import annotations

import pytest

from sentinel.feed import ingest, sharadar, snapshot_source, tickers_authority


def test_production_seed_rejects_overlapping_ticker_reuse(monkeypatch):
    rows = [
        {
            "table": "SEP", "permaticker": "100", "ticker": "ABC",
            "category": "Domestic Common Stock", "sector": "Industrials",
            "relatedtickers": "", "firstpricedate": "2020-01-01",
            "lastpricedate": "2026-08-25", "isdelisted": "N",
        },
        {
            "table": "SEP", "permaticker": "200", "ticker": "ABC",
            "category": "Domestic Common Stock", "sector": "Industrials",
            "relatedtickers": "", "firstpricedate": "2026-01-01",
            "lastpricedate": "2026-08-25", "isdelisted": "N",
        },
    ]

    def source(table, params=None, **kwargs):
        if table == sharadar.TICKERS:
            return [dict(row) for row in rows]
        return []

    monkeypatch.setattr(snapshot_source, "fetch_table", source)
    _tracked, guarded = ingest._seed_source(source, final_hi="2026-08-25")

    with pytest.raises(
            tickers_authority.TickersStructureInvalid,
            match="nonoverlapping_ticker_reuse_intervals"):
        list(guarded(sharadar.TICKERS))
