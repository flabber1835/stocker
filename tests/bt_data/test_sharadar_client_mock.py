"""The mock Sharadar client must yield well-formed rows for SEP/SF1/TICKERS so the
backfill, the data-depth report, and the engine can run end-to-end before the real
Sharadar subscription is live (BT_MOCK_DATA / no SHARADAR_API_KEY)."""
import asyncio
import os

os.environ["BT_MOCK_DATA"] = "true"

from app.sharadar_client import fetch_table, is_mock  # noqa: E402
from app.sharadar_adapter import map_sep_row, map_sf1_row, map_tickers_row  # noqa: E402


def _collect(table, **kw):
    async def run():
        return [r async for r in fetch_table(table, **kw)]
    return asyncio.run(run())


def test_is_mock_true_without_key():
    assert is_mock() is True


def test_mock_sep_rows_map_cleanly():
    rows = _collect("SEP")
    assert len(rows) > 100
    mapped = [map_sep_row(r) for r in rows]
    # every mapped row has a usable adjusted_close and the pipeline columns
    assert all(m["adjusted_close"] is not None for m in mapped)
    assert {"AAA", "BBB", "CCC", "SPY"}.issubset({m["ticker"] for m in mapped})
    assert all(set(m) >= {"ticker", "date", "adjusted_close", "close", "volume"} for m in mapped)


def test_mock_sf1_rows_map_with_datekey():
    rows = _collect("SF1")
    mapped = [map_sf1_row(r) for r in rows]
    assert all(m is not None for m in mapped)
    assert all(m["as_of_date"] for m in mapped)
    assert all(m["pe_ratio"] is not None for m in mapped)


def test_mock_tickers_filters_etf():
    rows = _collect("TICKERS")
    mapped = [map_tickers_row(r, "2023-01-01") for r in rows]
    kept = [m for m in mapped if m is not None]
    tickers = {m["ticker"] for m in kept}
    assert "SPY" not in tickers          # ETF excluded
    assert {"AAA", "BBB", "CCC"}.issubset(tickers)


def test_mock_sep_has_spy_for_benchmark_and_regime():
    rows = _collect("SEP")
    spy = [r for r in rows if r["ticker"] == "SPY"]
    assert len(spy) > 200   # enough for the 200-day regime SMA
