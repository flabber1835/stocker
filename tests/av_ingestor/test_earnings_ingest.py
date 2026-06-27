"""av-ingestor: AV EARNINGS parsing (get_earnings) and the SUE factor end-to-end.

Verifies the client maps AV's `quarterlyEarnings` to the columns the earnings
table / PEAD factor consume, that mock mode produces a usable history, and that a
real-shaped payload round-trips through the factor to score a beat above a miss.
"""
import os
import sys
from datetime import date
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from app.alpha_vantage import AVClient

# the factor lives in the pipeline service
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../services/pipeline/app"))
from factors import compute_earnings_surprise  # noqa: E402


_AV_PAYLOAD = {
    "symbol": "ACME",
    "quarterlyEarnings": [
        {"fiscalDateEnding": "2026-03-31", "reportedDate": "2026-04-20",
         "reportedEPS": "1.50", "estimatedEPS": "1.00", "surprise": "0.50",
         "surprisePercentage": "50.0"},
        {"fiscalDateEnding": "2025-12-31", "reportedDate": "2026-01-20",
         "reportedEPS": "1.00", "estimatedEPS": "1.00", "surprise": "0.0",
         "surprisePercentage": "0.0"},
        # AV often returns the string "None" for a missing estimate — must parse to None.
        {"fiscalDateEnding": "2025-09-30", "reportedDate": "2025-10-20",
         "reportedEPS": "0.90", "estimatedEPS": "None", "surprise": "None",
         "surprisePercentage": "None"},
    ],
}


@pytest.mark.asyncio
async def test_get_earnings_parses_av_payload():
    c = AVClient(api_key="k")
    c._get = AsyncMock(return_value=_AV_PAYLOAD)
    rows = await c.get_earnings("ACME")
    assert rows is not None and len(rows) == 3
    top = rows[0]
    assert top["fiscal_date_ending"] == "2026-03-31"
    assert top["reported_date"] == "2026-04-20"
    assert top["reported_eps"] == 1.50 and top["estimated_eps"] == 1.00
    # "None" string → None (not a float)
    assert rows[2]["estimated_eps"] is None


@pytest.mark.asyncio
async def test_get_earnings_none_when_no_quarterly():
    c = AVClient(api_key="k")
    c._get = AsyncMock(return_value={"symbol": "X"})  # no quarterlyEarnings
    assert await c.get_earnings("X") is None


@pytest.mark.asyncio
async def test_mock_mode_returns_usable_history():
    c = AVClient(api_key="k", mock_mode=True)
    rows = await c.get_earnings("AAPL")
    assert rows and len(rows) >= 6
    assert all("fiscal_date_ending" in r and "reported_date" in r for r in rows)


@pytest.mark.asyncio
async def test_parsed_payload_feeds_the_factor():
    # The parsed client output is exactly the shape the factor consumes.
    c = AVClient(api_key="k")
    c._get = AsyncMock(return_value=_AV_PAYLOAD)
    beat = await c.get_earnings("ACME")
    df = pd.DataFrame([{**r, "ticker": "ACME"} for r in beat])
    # add a miss so there's a cross-section
    df = pd.concat([df, pd.DataFrame([
        {"ticker": "FLOP", "fiscal_date_ending": "2026-03-31", "reported_date": "2026-04-20",
         "reported_eps": 0.5, "estimated_eps": 1.0},
    ])], ignore_index=True)
    s = compute_earnings_surprise(df, date(2026, 5, 1), min_quarters_for_sue=2)
    assert s["ACME"] > 0 > s["FLOP"]
