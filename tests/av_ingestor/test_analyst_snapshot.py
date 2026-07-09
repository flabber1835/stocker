"""av-ingestor: AV OVERVIEW forward-looking analyst fields → analyst_snapshots.

The analyst block (target price, rating distribution, forward PE, PEG) rides in the
SAME OVERVIEW payload already fetched for fundamentals (no extra API call). It is
snapshotted point-in-time (keyed by snapshot_date) as the raw history a future
revision factor will diff across. These tests verify the client extraction, that
the analyst block does NOT leak into the fundamentals upsert, and that the snapshot
upsert binds a date OBJECT (the asyncpg DATE-binding pitfall) with the right params.
"""
from datetime import date
from unittest.mock import AsyncMock

import pytest

from app.alpha_vantage import AVClient
from app.main import _upsert_analyst_snapshot, _upsert_fundamentals


_AV_OVERVIEW = {
    "Symbol": "ACME",
    "PERatio": "20.0", "PriceToBookRatio": "3.0", "ReturnOnEquityTTM": "0.25",
    "DebtToEquityRatio": "1.1", "QuarterlyRevenueGrowthYOY": "0.12",
    "QuarterlyEarningsGrowthYOY": "0.18", "MarketCapitalization": "1000000000",
    "GrossProfitTTM": "5000000000", "Sector": "TECHNOLOGY",
    # forward-looking analyst fields
    "AnalystTargetPrice": "150.5",
    "AnalystRatingStrongBuy": "8", "AnalystRatingBuy": "5", "AnalystRatingHold": "3",
    "AnalystRatingSell": "1", "AnalystRatingStrongSell": "0",
    "ForwardPE": "18.2", "PEGRatio": "1.4",
}


@pytest.mark.asyncio
async def test_get_overview_extracts_analyst_block():
    c = AVClient(api_key="k")
    c._get = AsyncMock(return_value=_AV_OVERVIEW)
    ov = await c.get_overview("ACME")
    assert ov is not None
    a = ov["analyst"]
    assert a["target_price"] == 150.5
    assert a["rating_strong_buy"] == 8 and a["rating_buy"] == 5
    assert a["rating_hold"] == 3 and a["rating_sell"] == 1 and a["rating_strong_sell"] == 0
    assert a["forward_pe"] == 18.2 and a["peg_ratio"] == 1.4


@pytest.mark.asyncio
async def test_get_overview_analyst_tolerates_missing_fields():
    # AV often returns "None"/absent for thin coverage — must parse to None, not crash.
    c = AVClient(api_key="k")
    c._get = AsyncMock(return_value={"Symbol": "X", "AnalystTargetPrice": "None"})
    ov = await c.get_overview("X")
    a = ov["analyst"]
    assert a["target_price"] is None and a["rating_strong_buy"] is None
    assert a["forward_pe"] is None and a["peg_ratio"] is None


@pytest.mark.asyncio
async def test_mock_overview_includes_analyst_block():
    c = AVClient(api_key="k", mock_mode=True)
    ov = await c.get_overview("AAPL")
    a = ov["analyst"]
    assert {"target_price", "rating_strong_buy", "rating_buy", "rating_hold",
            "rating_sell", "rating_strong_sell", "forward_pe", "peg_ratio"} <= a.keys()
    assert a["target_price"] is not None


@pytest.mark.asyncio
async def test_upsert_analyst_snapshot_binds_date_object_and_params():
    captured = []

    class _Sess:
        async def execute(self, _sql, params=None):
            captured.append(params)

    analyst = {
        "target_price": 150.5, "rating_strong_buy": 8, "rating_buy": 5,
        "rating_hold": 3, "rating_sell": 1, "rating_strong_sell": 0,
        "forward_pe": 18.2, "peg_ratio": 1.4,
    }
    await _upsert_analyst_snapshot(_Sess(), "ACME", analyst, date(2026, 6, 28))
    assert len(captured) == 1
    p = captured[0]
    assert isinstance(p["d"], date) and p["d"] == date(2026, 6, 28)
    assert not isinstance(p["d"], str)        # the asyncpg DATE-binding pitfall
    assert p["t"] == "ACME" and p["tp"] == 150.5
    assert p["rsb"] == 8 and p["rss"] == 0 and p["fpe"] == 18.2 and p["peg"] == 1.4


@pytest.mark.asyncio
async def test_upsert_analyst_snapshot_noops_on_empty():
    calls = []

    class _Sess:
        async def execute(self, _sql, params=None):
            calls.append(params)

    await _upsert_analyst_snapshot(_Sess(), "ACME", None, date(2026, 6, 28))
    await _upsert_analyst_snapshot(_Sess(), "ACME", {}, date(2026, 6, 28))
    assert calls == []   # nothing written for a missing/empty analyst block


@pytest.mark.asyncio
async def test_fundamentals_upsert_does_not_leak_analyst_block():
    # The **overview spread into the fundamentals INSERT must not carry the nested
    # analyst dict (it's snapshotted separately). _upsert_fundamentals pops it.
    captured = []

    class _Result:
        # repair_queue.record_check reads the prev row via .mappings().first()
        def mappings(self): return self
        def first(self): return None

    class _Sess:
        async def execute(self, _sql, params=None):
            captured.append(params)
            return _Result()

    c = AVClient(api_key="k")
    c._get = AsyncMock(return_value=_AV_OVERVIEW)
    ov = await c.get_overview("ACME")
    await _upsert_fundamentals(_Sess(), "ACME", ov, date(2026, 6, 28))
    # The fundamentals UPSERT — not the repair_queue prev-row SELECT that now also
    # runs inside _upsert_fundamentals (identify by the fundamentals param shape).
    upsert = next(p for p in captured if p and "market_cap" in p)
    assert "analyst" not in upsert
    assert upsert["market_cap"] == 1000000000   # real fundamentals still bind
