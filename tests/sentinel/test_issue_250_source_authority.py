"""Issue #250 source-envelope, identity-model, seed, and CLI falsifiers."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from sentinel.__main__ import _resolve_feed_daily_through
from sentinel.feed import coherence, source_validation


def _bar(**overrides):
    row = {
        "ticker": "AAA", "date": "2026-08-24", "open": 10,
        "close": 11, "closeunadj": 11, "volume": 100,
        "lastupdated": "2026-08-24",
    }
    row.update(overrides)
    return row


def _ticker(permaticker="P1", ticker="AAA", **overrides):
    row = {
        "table": "SEP", "permaticker": permaticker, "ticker": ticker,
        "category": "Domestic Common Stock", "firstpricedate": "2026-08-24",
        "lastpricedate": "2026-08-24", "isdelisted": "N",
    }
    row.update(overrides)
    return row


def test_market_envelope_collapses_exact_repeat_and_refuses_conflict():
    params = {"date.gte": "2026-08-24", "date.lte": "2026-08-24"}
    assert len(list(source_validation.validated_market_rows(
        "SEP", [_bar(), _bar()], params))) == 1
    with pytest.raises(source_validation.ConflictingSourceDuplicate):
        list(source_validation.validated_market_rows(
            "SEP", [_bar(), _bar(close=12)], params))


@pytest.mark.parametrize("row,params,through", [
    (_bar(date="2026-08-21"),
     {"date.gte": "2026-08-24", "date.lte": "2026-08-24"}, None),
    (_bar(date="2026-08-23"),
     {"date.gte": "2026-08-23", "date.lte": "2026-08-23"}, None),
    (_bar(lastupdated="2026-08-25"),
     {"date.gte": "2026-08-24", "date.lte": "2026-08-24"}, "2026-08-24"),
    (_bar(lastupdated="2026-08-20"),
     {"lastupdated.gte": "2026-08-21", "lastupdated.lte": "2026-08-24"}, None),
])
def test_market_envelope_refuses_outside_non_session_and_watermark(row, params, through):
    with pytest.raises(source_validation.SourceEnvelopeRefused):
        list(source_validation.validated_market_rows(
            "SEP", [row], params, observation_through=through))


@pytest.mark.parametrize("rows", [
    [_ticker(firstpricedate="2026-08-25", lastpricedate="2026-08-24")],
    [_ticker(isdelisted="MAYBE")],
    [_ticker(), _ticker(category="Preferred Stock")],
    [_ticker("P1", "AAA", firstpricedate="2026-08-20", lastpricedate="2026-08-24"),
     _ticker("P2", "AAA", firstpricedate="2026-08-24", lastpricedate="2026-08-25")],
])
def test_tickers_impossible_or_conflicting_models_refuse(rows):
    with pytest.raises(source_validation.SourceEnvelopeRefused):
        source_validation.validate_tickers(rows)


def test_tickers_exact_duplicate_collapses():
    assert len(source_validation.validate_tickers([_ticker(), _ticker()])) == 1


def test_stable_partial_seed_missing_one_eligible_listing_refuses_exactly():
    expected = (
        coherence.SeedExpectedListing("AAA", "2026-08-24", "2026-08-24", True),
        coherence.SeedExpectedListing("BBB", "2026-08-24", "2026-08-24", True),
        coherence.SeedExpectedListing("ETF", "2026-08-24", "2026-08-24", False),
    )
    with pytest.raises(coherence.SeedHistoryIncomplete) as failure:
        coherence.assert_seed_listing_coverage(
            {"2026-08-24": {"AAA"}}, expected,
            date_from="2026-08-24", date_to="2026-08-24")
    evidence = failure.value.coverage_evidence[0]
    assert evidence["missing_eligible"] == ["BBB"]
    assert evidence["extra"] == []
    assert evidence["absent_ineligible_count"] == 1


def test_daily_boundary_ignores_utc_rollover_and_refuses_non_session_future():
    # 17:30 PDT is already 00:30 UTC on Aug 25; the decision boundary is
    # still the fully closed Aug 24 XNYS session.
    now = datetime(2026, 8, 24, 17, 30, tzinfo=ZoneInfo("America/Los_Angeles"))
    assert _resolve_feed_daily_through(None, now_et=now) == "2026-08-24"
    with pytest.raises(ValueError, match="not an XNYS session"):
        _resolve_feed_daily_through("2026-08-23", now_et=now)
    with pytest.raises(ValueError, match="later than latest fully closed"):
        _resolve_feed_daily_through("2026-08-25", now_et=now)
