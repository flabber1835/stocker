"""Tests for the Sharadar→pipeline column-contract mapping.

These lock the field mapping so it can't silently drift from what the live
pipeline factor functions expect:
  prices       → ticker, date, adjusted_close, close, volume
  fundamentals → ticker, as_of_date, pe_ratio, pb_ratio, roe, debt_to_equity,
                 revenue_growth, eps_growth   (as_of_date = POINT-IN-TIME datekey)
"""
from app.sharadar_adapter import (  # noqa: E402
    MAX_MAGNITUDE, map_sep_row, map_sf1_row, map_tickers_row, compute_growth,
)


# ── SEP prices ──────────────────────────────────────────────────────────────

def test_sep_maps_closeadj_to_adjusted_close():
    row = {"ticker": "AAPL", "date": "2023-01-03", "open": 130, "high": 131,
           "low": 129, "close": 130.5, "closeadj": 129.8, "volume": 1000000}
    m = map_sep_row(row)
    assert m["ticker"] == "AAPL"
    assert m["date"] == "2023-01-03"
    assert m["adjusted_close"] == 129.8   # closeadj, NOT close
    assert m["close"] == 130.5
    assert m["volume"] == 1000000.0


def test_sep_handles_missing_values():
    m = map_sep_row({"ticker": "X", "date": "2023-01-03", "closeadj": "", "volume": None})
    assert m["adjusted_close"] is None
    assert m["volume"] is None


def test_sep_drops_reverse_split_artifact_prices():
    # BINI-class reverse-split penny stock: backward-adjusted prices balloon to
    # 1e17+, overflow the NUMERIC column, and are useless. They must map to None
    # (adjusted_close None → the backfill skips the row) rather than crash-insert.
    row = {"ticker": "BINI", "date": "2018-10-24",
           "open": 4.5e17, "high": 4.68e17, "low": 4.21e17,
           "close": 4.25e17, "closeadj": 4.25e17, "volume": 0}
    m = map_sep_row(row)
    assert m["adjusted_close"] is None
    assert m["open"] is None and m["close"] is None


def test_sep_keeps_high_but_legit_prices():
    # a genuinely expensive stock (BRK.A-scale, ~$700k) is well under the cap
    row = {"ticker": "BRK.A", "date": "2023-01-03", "close": 700000.0,
           "closeadj": 700000.0, "volume": 100}
    m = map_sep_row(row)
    assert m["adjusted_close"] == 700000.0
    assert MAX_MAGNITUDE > 700000.0


def test_sep_contract_has_exactly_pipeline_columns():
    m = map_sep_row({"ticker": "X", "date": "2023-01-03", "close": 1, "closeadj": 1, "volume": 1})
    # the pipeline reads: ticker, date, adjusted_close, close, volume
    for col in ("ticker", "date", "adjusted_close", "close", "volume"):
        assert col in m


# ── SF1 fundamentals (point-in-time) ──────────────────────────────────────────

def test_sf1_uses_datekey_as_point_in_time_asof():
    row = {"ticker": "MSFT", "datekey": "2023-04-25", "calendardate": "2023-03-31",
           "dimension": "ARQ", "pe": 30.0, "pb": 12.0, "roe": 0.40, "de": 0.5,
           "revenue": 52000, "eps": 2.45}
    m = map_sf1_row(row)
    # as_of_date is the FILING date (datekey), not the fiscal period end —
    # this is what prevents look-ahead bias.
    assert m["as_of_date"] == "2023-04-25"
    assert m["pe_ratio"] == 30.0
    assert m["pb_ratio"] == 12.0
    assert m["roe"] == 0.40
    assert m["debt_to_equity"] == 0.5
    # growth left None for the caller to compute from successive filings
    assert m["revenue_growth"] is None
    assert m["eps_growth"] is None
    # raw helpers carried for the caller's YoY computation
    assert m["_revenue"] == 52000.0
    assert m["_eps"] == 2.45


def test_sf1_without_datekey_is_dropped():
    assert map_sf1_row({"ticker": "X", "pe": 10}) is None


def test_sf1_fiscal_period_for_audit():
    m = map_sf1_row({"ticker": "X", "datekey": "2023-04-25",
                     "calendardate": "2023-03-31", "dimension": "ARQ"})
    assert m["fiscal_period"] == "2023-03-31/ARQ"


# ── Universe / tickers ─────────────────────────────────────────────────────────

def test_tickers_includes_common_stock_on_major_exchange():
    m = map_tickers_row({"ticker": "AAPL", "name": "Apple", "sector": "Technology",
                         "category": "Domestic Common Stock", "exchange": "NASDAQ"},
                        "2023-06-30")
    assert m is not None
    assert m["ticker"] == "AAPL"
    assert m["sector"] == "Technology"
    assert m["snapshot_date"] == "2023-06-30"


def test_tickers_excludes_etf_and_otc():
    assert map_tickers_row({"ticker": "SPY", "category": "ETF", "exchange": "NYSEARCA"},
                           "2023-06-30") is None
    assert map_tickers_row({"ticker": "XYZ", "category": "Domestic Common Stock",
                            "exchange": "OTC"}, "2023-06-30") is None


# ── YoY growth ─────────────────────────────────────────────────────────────────

def test_compute_growth_basic():
    assert compute_growth(110, 100) == 0.10
    assert compute_growth(90, 100) == -0.10


def test_compute_growth_none_when_missing_or_zero():
    assert compute_growth(None, 100) is None
    assert compute_growth(100, None) is None
    assert compute_growth(100, 0) is None


def test_compute_growth_negative_base_uses_abs():
    # year-ago was -50, now -25 → improvement; (−25 − −50)/|−50| = +0.5
    assert compute_growth(-25, -50) == 0.5
