"""Tests for the gross-profit / total-assets ingestion (AVClient).

Covers OVERVIEW GrossProfitTTM parsing, the new BALANCE_SHEET fetch for
total_assets, mock-mode shapes, and the _upsert_fundamentals tolerance for
overview dicts that lack the new keys.
"""
import asyncio
from datetime import date

import pytest

from app.alpha_vantage import AVClient, _mock_overview, _mock_balance_sheet
from app.main import _upsert_fundamentals


def _run(coro):
    return asyncio.run(coro)


def _client(mock=False):
    return AVClient(api_key="demo", mock_mode=mock)


# ── OVERVIEW: gross_profit ────────────────────────────────────────────────────

def test_overview_parses_gross_profit_ttm():
    c = _client()

    async def fake_get(params):
        assert params["function"] == "OVERVIEW"
        return {"Symbol": "AAA", "GrossProfitTTM": "1234567890",
                "ReturnOnEquityTTM": "0.25", "Sector": "Technology"}

    c._get = fake_get
    try:
        ov = _run(c.get_overview("AAA"))
    finally:
        _run(c.close())
    assert ov["gross_profit"] == pytest.approx(1234567890.0)
    assert ov["roe"] == pytest.approx(0.25)
    assert ov["sector"] == "Technology"


def test_overview_gross_profit_none_when_missing():
    c = _client()

    async def fake_get(params):
        return {"Symbol": "BBB"}  # no GrossProfitTTM

    c._get = fake_get
    try:
        ov = _run(c.get_overview("BBB"))
    finally:
        _run(c.close())
    assert ov["gross_profit"] is None


# ── BALANCE_SHEET: total_assets ───────────────────────────────────────────────

def test_balance_sheet_prefers_latest_quarterly():
    c = _client()

    async def fake_get(params):
        assert params["function"] == "BALANCE_SHEET"
        return {
            "symbol": "AAA",
            "quarterlyReports": [
                {"fiscalDateEnding": "2024-03-31", "totalAssets": "5000"},
                {"fiscalDateEnding": "2023-12-31", "totalAssets": "4800"},
            ],
            "annualReports": [{"fiscalDateEnding": "2023-12-31", "totalAssets": "4800"}],
        }

    c._get = fake_get
    try:
        bs = _run(c.get_balance_sheet("AAA"))
    finally:
        _run(c.close())
    assert bs["total_assets"] == pytest.approx(5000.0)  # most-recent quarter


def test_balance_sheet_parses_shares_yoy_from_annual():
    """Shares now vs prior fiscal year come from annualReports[0] and [1]."""
    c = _client()

    async def fake_get(params):
        return {
            "symbol": "AAA",
            "quarterlyReports": [{"totalAssets": "5000"}],
            "annualReports": [
                {"fiscalDateEnding": "2024-12-31", "totalAssets": "4900", "commonStockSharesOutstanding": "900"},
                {"fiscalDateEnding": "2023-12-31", "totalAssets": "4700", "commonStockSharesOutstanding": "1000"},
            ],
        }

    c._get = fake_get
    try:
        bs = _run(c.get_balance_sheet("AAA"))
    finally:
        _run(c.close())
    assert bs["shares_outstanding"] == pytest.approx(900.0)
    assert bs["shares_outstanding_prior"] == pytest.approx(1000.0)  # → -10% net issuance


def test_balance_sheet_shares_none_when_single_annual_report():
    """Only one annual report → no prior-year shares (None), still returns total_assets."""
    c = _client()

    async def fake_get(params):
        return {
            "quarterlyReports": [{"totalAssets": "5000"}],
            "annualReports": [{"commonStockSharesOutstanding": "900"}],
        }

    c._get = fake_get
    try:
        bs = _run(c.get_balance_sheet("AAA"))
    finally:
        _run(c.close())
    assert bs["shares_outstanding"] == pytest.approx(900.0)
    assert bs["shares_outstanding_prior"] is None


def test_mock_balance_sheet_has_shares():
    from app.alpha_vantage import _mock_balance_sheet
    bs = _mock_balance_sheet("NVDA")
    assert bs["shares_outstanding"] > 0 and bs["shares_outstanding_prior"] > 0


def test_balance_sheet_falls_back_to_annual():
    c = _client()

    async def fake_get(params):
        return {"annualReports": [{"totalAssets": "9999"}]}  # no quarterly

    c._get = fake_get
    try:
        bs = _run(c.get_balance_sheet("AAA"))
    finally:
        _run(c.close())
    assert bs["total_assets"] == pytest.approx(9999.0)


def test_balance_sheet_none_on_empty_reports():
    c = _client()

    async def fake_get(params):
        return {"symbol": "AAA", "quarterlyReports": [], "annualReports": []}

    c._get = fake_get
    try:
        bs = _run(c.get_balance_sheet("AAA"))
    finally:
        _run(c.close())
    assert bs is None


def test_balance_sheet_none_when_total_assets_unparseable():
    c = _client()

    async def fake_get(params):
        return {"quarterlyReports": [{"totalAssets": "None"}]}

    c._get = fake_get
    try:
        bs = _run(c.get_balance_sheet("AAA"))
    finally:
        _run(c.close())
    assert bs is None


# ── mock mode ─────────────────────────────────────────────────────────────────

def test_mock_overview_includes_gross_profit():
    ov = _mock_overview("AAPL")
    assert "gross_profit" in ov and ov["gross_profit"] > 0


def test_mock_balance_sheet_total_assets_positive():
    bs = _mock_balance_sheet("AAPL")
    assert bs["total_assets"] > 0


def test_mock_helpers_deterministic():
    assert _mock_overview("MSFT") == _mock_overview("MSFT")
    assert _mock_balance_sheet("MSFT") == _mock_balance_sheet("MSFT")


def test_mock_client_methods_round_trip():
    c = _client(mock=True)
    try:
        ov = _run(c.get_overview("NVDA"))
        bs = _run(c.get_balance_sheet("NVDA"))
    finally:
        _run(c.close())
    assert ov["gross_profit"] > 0
    assert bs["total_assets"] > 0


# ── _upsert_fundamentals param tolerance ──────────────────────────────────────

class _FakeSession:
    def __init__(self):
        self.calls = []

    async def execute(self, stmt, params=None):
        self.calls.append((stmt, params))


def _base_overview(**extra):
    ov = {
        "pe_ratio": 10.0, "pb_ratio": 2.0, "roe": 0.2, "debt_to_equity": 1.0,
        "revenue_growth": 0.1, "eps_growth": 0.1, "market_cap": 1_000_000_000,
        "avg_volume": 1_000_000, "sector": "Technology",
    }
    ov.update(extra)
    return ov


def test_upsert_defaults_new_keys_when_absent():
    """An overview dict that never got gross_profit/total_assets (e.g. balance
    sheet disabled) must still upsert, with those columns defaulting to NULL."""
    sess = _FakeSession()
    _run(_upsert_fundamentals(sess, "AAA", _base_overview(), date(2024, 1, 1)))
    _, params = sess.calls[0]
    assert params["gross_profit"] is None
    assert params["total_assets"] is None
    assert params["ticker"] == "AAA"
    assert "sector" not in params  # popped before the INSERT


def test_upsert_uses_supplied_gross_profit_and_total_assets():
    sess = _FakeSession()
    ov = _base_overview(gross_profit=5e9, total_assets=1e11)
    _run(_upsert_fundamentals(sess, "BBB", ov, date(2024, 1, 1)))
    _, params = sess.calls[0]
    assert params["gross_profit"] == pytest.approx(5e9)
    assert params["total_assets"] == pytest.approx(1e11)
