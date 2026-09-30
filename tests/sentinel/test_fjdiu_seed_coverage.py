"""The reviewed FJDIU onset gap is exact and cannot mask later source loss."""

import json

import pytest

from sentinel.feed import source_authority, symbol_identity


_CATEGORY = "Domestic Common Stock Secondary Class"
_SESSIONS = ["2026-09-24", "2026-09-25", "2026-09-28"]


def _listing(**changes):
    row = {
        "table": "SEP",
        "permaticker": "6401378",
        "ticker": "FJDIU",
        "category": _CATEGORY,
        "firstpricedate": "2026-09-24",
        "lastpricedate": "2026-09-29",
    }
    row.update(changes)
    return row


def _evidence(monkeypatch, *, listing=None, observed="2026-09-28",
              sessions=_SESSIONS):
    projection = source_authority.SeedListingProjection(
        [listing or _listing()], source_digest="a" * 64)
    monkeypatch.setattr(
        source_authority.coverage.calendar, "sessions_in_range",
        lambda start, end: sessions)
    coverage = source_authority.SeedCoverageAccumulator(
        projection, lambda ticker, session: "6401378")
    try:
        coverage.add({"ticker": "FJDIU", "date": observed,
                      "open": 10.02, "close": 10.02, "volume": 15800})
        return coverage.require_complete(
            date_from=sessions[0], date_to=sessions[-1])
    finally:
        coverage.close()


def test_fjdiu_two_reviewed_opening_absences_are_accepted(monkeypatch):
    evidence = _evidence(monkeypatch)
    assert evidence["expected_eligible_total"] == 3
    assert evidence["received_eligible_total"] == 1
    assert evidence["reviewed_exceptions_applied_total"] == 2


def test_fjdi_and_fjdiu_keep_distinct_native_identities(monkeypatch):
    listings = [
        _listing(),
        _listing(permaticker="6400999", ticker="FJDI",
                 category="Domestic Common Stock Primary Class",
                 firstpricedate="2026-08-04"),
    ]
    actions = [
        {"date": "2026-09-24", "action": "tickerchangeto",
         "ticker": "FJDI", "contraticker": "FJDI"},
        {"date": "2026-09-24", "action": "tickerchangefrom",
         "ticker": "FJDI", "contraticker": "FJDIU"},
    ]
    identity = symbol_identity.SymbolProjection(
        listings, actions, through="2026-09-29")
    assert identity.rejections[0]["reason_code"] == (
        "RENAME_ANCHOR_IDENTITY_OR_CATEGORY_AMBIGUOUS")
    resolver = identity.resolver()
    assert resolver.resolve("FJDI", "2026-09-24") == "6400999"
    assert resolver.resolve("FJDIU", "2026-09-24") == "6401378"
    projection = source_authority.SeedListingProjection(
        listings, source_digest="a" * 64)
    monkeypatch.setattr(
        source_authority.coverage.calendar, "sessions_in_range",
        lambda start, end: _SESSIONS)
    coverage = source_authority.SeedCoverageAccumulator(
        projection, resolver.resolve)
    try:
        for session in _SESSIONS:
            coverage.add({"ticker": "FJDI", "date": session,
                          "open": 9.85, "close": 9.85, "volume": 1000})
        coverage.add({"ticker": "FJDIU", "date": "2026-09-28",
                      "open": 10.02, "close": 10.02, "volume": 15800})
        evidence = coverage.require_complete(
            date_from=_SESSIONS[0], date_to=_SESSIONS[-1])
        assert evidence["expected_eligible_total"] == 6
        assert evidence["received_eligible_total"] == 4
        assert evidence["reviewed_exceptions_applied_total"] == 2
    finally:
        coverage.close()


@pytest.mark.parametrize("listing,observed,sessions", [
    (_listing(permaticker="6401379"), "2026-09-28", _SESSIONS),
    (_listing(ticker="FJDI.V"), "2026-09-28", _SESSIONS),
    (_listing(category="ADR Common Stock Secondary Class"), "2026-09-28", _SESSIONS),
    (_listing(firstpricedate="2026-09-23"), "2026-09-28", _SESSIONS),
    (_listing(), "2026-09-29", ["2026-09-24", "2026-09-25", "2026-09-28", "2026-09-29"]),
    (_listing(), "2026-09-28", ["2026-09-24", "2026-09-25", "2026-09-28", "2026-09-29"]),
])
def test_fjdiu_exception_refuses_changed_identity_or_unreviewed_gap(
        monkeypatch, listing, observed, sessions):
    with pytest.raises(source_authority.SourceAuthorityRefused) as caught:
        _evidence(monkeypatch, listing=listing, observed=observed,
                  sessions=sessions)
    evidence = json.loads(str(caught.value).split(": ", 1)[1])
    assert evidence["missing_eligible_total"] == 1
