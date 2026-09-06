import json

import pytest

from sentinel.feed import source_authority


COMMON = "Domestic Common Stock"


def _ticker(*, last="2026-09-03"):
    return {
        "table": "SEP",
        "permaticker": "640227",
        "ticker": "APGE",
        "category": COMMON,
        "firstpricedate": "2023-07-14",
        "lastpricedate": last,
    }


def test_apge_reviewed_terminal_no_trade_session_is_accepted(monkeypatch):
    projection = source_authority.SeedListingProjection(
        [_ticker()], source_digest="a" * 64)
    monkeypatch.setattr(
        source_authority.coverage.calendar,
        "sessions_in_range",
        lambda start, end: ["2026-09-03"],
    )

    coverage = source_authority.SeedCoverageAccumulator(
        projection, lambda ticker, session: "640227")
    try:
        evidence = coverage.require_complete(
            date_from="2026-09-03", date_to="2026-09-03")
        assert evidence["expected_eligible_total"] == 1
        assert evidence["received_eligible_total"] == 0
        assert evidence["reviewed_exceptions_applied_total"] == 1
        assert evidence["missing_eligible_total"] == 0
    finally:
        coverage.close()


def test_apge_terminal_exception_is_bound_to_exact_tickers_last_session(monkeypatch):
    projection = source_authority.SeedListingProjection(
        [_ticker(last="2026-09-04")], source_digest="a" * 64)
    monkeypatch.setattr(
        source_authority.coverage.calendar,
        "sessions_in_range",
        lambda start, end: ["2026-09-03"],
    )

    coverage = source_authority.SeedCoverageAccumulator(
        projection, lambda ticker, session: "640227")
    try:
        with pytest.raises(source_authority.SourceAuthorityRefused) as caught:
            coverage.require_complete(
                date_from="2026-09-03", date_to="2026-09-03")
        evidence = json.loads(str(caught.value).split(": ", 1)[1])
        assert evidence["missing_eligible"] == [
            {"permaticker": "640227", "ticker": "APGE"}
        ]
        assert evidence["reviewed_exceptions_applied"] == []
    finally:
        coverage.close()
