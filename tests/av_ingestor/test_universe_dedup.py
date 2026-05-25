"""
Tests for duplicate-ticker handling in download_av_listing.

AV LISTING_STATUS can return the same ticker symbol on multiple exchanges
(e.g. NYSE:B "Barnes Group" and OTC:B "Barrick Gold Corp"). Without deduplication
the wrong name ends up in the DB and the dashboard shows the wrong company.
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "av-ingestor"))

from app.universe import _TICKER_RE, _WARRANT_RE, _DERIVATIVE_TICKER_RE, _NON_INVESTABLE_NAME_RE, _US_EXCHANGES


def _run_filter(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Inline replica of download_av_listing's filter loop (without HTTP call)."""
    accepted: list[dict] = []
    filtered: list[dict] = []
    seen: set[str] = set()
    for av_row in rows:
        ticker = av_row.get("symbol", "")
        if not _TICKER_RE.match(ticker):
            filtered.append({**av_row, "_filter_reason": "ticker_format"}); continue
        if _WARRANT_RE.search(ticker):
            filtered.append({**av_row, "_filter_reason": "warrant_or_unit"}); continue
        if _DERIVATIVE_TICKER_RE.search(ticker):
            filtered.append({**av_row, "_filter_reason": "derivative_ticker"}); continue
        if _NON_INVESTABLE_NAME_RE.search(av_row.get("name", "")):
            filtered.append({**av_row, "_filter_reason": "non_investable_name"}); continue
        if av_row.get("status", "").lower() != "active":
            filtered.append({**av_row, "_filter_reason": "inactive"}); continue
        if av_row.get("assetType", "") not in ("Stock",):
            filtered.append({**av_row, "_filter_reason": "non_stock"}); continue
        if av_row.get("exchange", "") not in _US_EXCHANGES:
            filtered.append({**av_row, "_filter_reason": "wrong_exchange"}); continue
        if ticker in seen:
            filtered.append({**av_row, "_filter_reason": "duplicate_ticker"}); continue
        seen.add(ticker)
        accepted.append({"ticker": ticker, "name": av_row.get("name") or None,
                          "weight_pct": None, "sector": None, "asset_class": "Equity"})
    return accepted, filtered


def _row(symbol: str, name: str, exchange: str = "NYSE") -> dict:
    return {"symbol": symbol, "name": name, "exchange": exchange,
            "assetType": "Stock", "status": "active"}


class TestDuplicateTickerDedup:
    def test_first_occurrence_wins(self):
        rows = [
            _row("B", "Barnes Group Inc",  "NYSE"),
            _row("B", "Barrick Gold Corp", "OTC"),
        ]
        accepted, filtered = _run_filter(rows)
        assert len(accepted) == 1
        assert accepted[0]["ticker"] == "B"
        assert accepted[0]["name"] == "Barnes Group Inc"

    def test_second_occurrence_marked_duplicate(self):
        rows = [
            _row("B", "Barnes Group Inc",  "NYSE"),
            _row("B", "Barrick Gold Corp", "OTC"),
        ]
        _, filtered = _run_filter(rows)
        dup = [r for r in filtered if r.get("_filter_reason") == "duplicate_ticker"]
        assert len(dup) == 1
        assert dup[0]["name"] == "Barrick Gold Corp"

    def test_three_listings_same_ticker_keeps_first(self):
        rows = [
            _row("A", "Agilent Technologies Inc", "NYSE"),
            _row("A", "Some OTC Company",         "OTC"),
            _row("A", "Another Exchange Company",  "BATS"),
        ]
        accepted, filtered = _run_filter(rows)
        assert len(accepted) == 1
        assert accepted[0]["name"] == "Agilent Technologies Inc"
        dups = [r for r in filtered if r["_filter_reason"] == "duplicate_ticker"]
        assert len(dups) == 2

    def test_different_tickers_both_accepted(self):
        rows = [
            _row("AAPL", "Apple Inc",      "NASDAQ"),
            _row("MSFT", "Microsoft Corp", "NASDAQ"),
        ]
        accepted, _ = _run_filter(rows)
        assert len(accepted) == 2
        tickers = {r["ticker"] for r in accepted}
        assert tickers == {"AAPL", "MSFT"}

    def test_single_char_ticker_dedup(self):
        rows = [_row("A", "Agilent Technologies", "NYSE"),
                _row("A", "OTC Duplicate",         "OTC")]
        accepted, _ = _run_filter(rows)
        assert len(accepted) == 1
        assert accepted[0]["name"] == "Agilent Technologies"

    def test_empty_input(self):
        accepted, filtered = _run_filter([])
        assert accepted == []
        assert filtered == []

    def test_all_unique_no_duplicates_filtered(self):
        rows = [_row(t, f"{t} Corp") for t in ["AA", "AB", "AC", "AD"]]
        accepted, filtered = _run_filter(rows)
        dups = [r for r in filtered if r["_filter_reason"] == "duplicate_ticker"]
        assert len(dups) == 0
        assert len(accepted) == 4

    def test_dedup_independent_of_other_filters(self):
        rows = [
            _row("AAPL", "Apple Inc",   "NASDAQ"),
            _row("AAPL", "Apple Corp",  "OTC"),    # clean name — only fails because duplicate
            _row("BAD!", "Bad Ticker",  "NYSE"),    # ticker format failure
        ]
        accepted, filtered = _run_filter(rows)
        assert len(accepted) == 1
        assert accepted[0]["ticker"] == "AAPL"
        reasons = {r["_filter_reason"] for r in filtered}
        assert "duplicate_ticker" in reasons
        assert "ticker_format" in reasons


class TestDistinctOnNamesQuery:
    """
    Simulate the DISTINCT ON (ticker) ORDER BY ticker, id ASC semantics
    that the API now applies to the names CTE. This ensures lowest id
    (first inserted = first in AV CSV) wins when duplicates exist in DB.
    """

    def _distinct_on_ticker(self, rows: list[dict]) -> dict[str, dict]:
        """Mirror: SELECT DISTINCT ON (ticker) ... ORDER BY ticker, id ASC"""
        by_ticker: dict[str, dict] = {}
        for r in sorted(rows, key=lambda r: (r["ticker"], r["id"])):
            if r["ticker"] not in by_ticker:
                by_ticker[r["ticker"]] = r
        return by_ticker

    def test_lowest_id_wins_for_same_ticker(self):
        rows = [
            {"id": 10, "ticker": "B", "name": "Barrick Gold Corp", "sector": None},
            {"id":  5, "ticker": "B", "name": "Barnes Group Inc",  "sector": None},
        ]
        result = self._distinct_on_ticker(rows)
        assert result["B"]["name"] == "Barnes Group Inc"  # id=5 wins

    def test_unique_tickers_all_returned(self):
        rows = [
            {"id": 1, "ticker": "AAPL", "name": "Apple Inc",      "sector": "IT"},
            {"id": 2, "ticker": "MSFT", "name": "Microsoft Corp",  "sector": "IT"},
        ]
        result = self._distinct_on_ticker(rows)
        assert len(result) == 2
        assert "AAPL" in result and "MSFT" in result

    def test_three_duplicates_lowest_id_wins(self):
        rows = [
            {"id": 30, "ticker": "A", "name": "Third Name",  "sector": None},
            {"id": 10, "ticker": "A", "name": "First Name",  "sector": None},
            {"id": 20, "ticker": "A", "name": "Second Name", "sector": None},
        ]
        result = self._distinct_on_ticker(rows)
        assert result["A"]["name"] == "First Name"
