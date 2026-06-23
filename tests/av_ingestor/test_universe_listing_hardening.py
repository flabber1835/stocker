"""Audit P2 — LISTING_STATUS hardening: OTC dropped (spec), case-insensitive
assetType/exchange (format-drift), and explicit detection of AV JSON throttle bodies /
missing CSV headers (clear failure instead of a silent ~0-row universe).
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.universe import download_av_listing, _US_EXCHANGES

_HEADER = "symbol,name,exchange,assetType,ipoDate,delistingDate,status"


def _sess(text_body):
    resp = MagicMock()
    resp.text = text_body
    resp.raise_for_status = MagicMock()
    s = MagicMock()
    s.get = AsyncMock(return_value=resp)
    return s


def _csv(*rows):
    return _HEADER + "\n" + "\n".join(rows)


def test_otc_not_in_exchange_set():
    assert "OTC" not in _US_EXCHANGES


@pytest.mark.asyncio
async def test_otc_listings_dropped(monkeypatch):
    monkeypatch.setenv("AV_MIN_UNIVERSE_SIZE", "1")
    body = _csv(
        "AAA,Alpha Inc,OTC,Stock,2000-01-01,null,Active",     # OTC → drop
        "BBB,Beta Corp,NYSE,Stock,2000-01-01,null,Active",    # keep
    )
    rows, _ = await download_av_listing(_sess(body), "k")
    assert {r["ticker"] for r in rows} == {"BBB"}


@pytest.mark.asyncio
async def test_case_and_spacing_insensitive(monkeypatch):
    monkeypatch.setenv("AV_MIN_UNIVERSE_SIZE", "1")
    body = _csv(
        "CCC,C Corp,nyse,stock,2000-01-01,null,Active",        # lowercase exch+type
        "DDD,D Corp,NYSE Arca,Stock,2000-01-01,null,Active",   # mixed-case "NYSE Arca"
    )
    rows, _ = await download_av_listing(_sess(body), "k")
    assert {r["ticker"] for r in rows} == {"CCC", "DDD"}


@pytest.mark.asyncio
async def test_json_throttle_body_raises():
    body = '{"Information":"you have reached the 75 requests per minute rate limit"}'
    with pytest.raises(ValueError) as ei:
        await download_av_listing(_sess(body), "k")
    assert "non-CSV" in str(ei.value)


@pytest.mark.asyncio
async def test_note_throttle_body_raises():
    body = '{"Note":"Thank you for using Alpha Vantage! 5 calls per minute"}'
    with pytest.raises(ValueError):
        await download_av_listing(_sess(body), "k")


@pytest.mark.asyncio
async def test_missing_required_header_raises():
    body = "symbol,name,exchange,status\nAAA,Alpha,NYSE,Active"  # no assetType column
    with pytest.raises(ValueError) as ei:
        await download_av_listing(_sess(body), "k")
    assert "missing expected columns" in str(ei.value)
