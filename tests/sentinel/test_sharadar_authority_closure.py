from __future__ import annotations

import pytest

from sentinel.feed import coherence, sharadar, universe


def _ticker_row(i: int, *, last: str = "2026-08-18") -> dict:
    return {
        "table": "SEP",
        "permaticker": f"P-{i:04d}",
        "ticker": f"T{i:04d}",
        "category": "Domestic Common Stock",
        "relatedtickers": "",
        "firstpricedate": "2000-01-03",
        "lastpricedate": last,
        "sector": "Technology",
        "isdelisted": "N",
    }


def _sep_row(i: int, session: str = "2026-08-18") -> dict:
    return {
        "ticker": f"T{i:04d}",
        "date": session,
        "open": 99.0,
        "close": 100.0,
        "closeunadj": 100.0,
        "volume": 1_000_000.0,
    }


def test_stable_partial_sep_cannot_false_green_against_tickers_population():
    tickers = [_ticker_row(i) for i in range(100)]
    partial = [_sep_row(i) for i in range(85)]

    def fetch(table, params=None, **_kwargs):
        if table == sharadar.TICKERS:
            return list(tickers)
        if table == sharadar.SEP:
            return list(partial)
        return []

    guarded = coherence.StableSharadarFetch(
        fetch, after_session="2026-08-17")
    guarded(sharadar.TICKERS)
    with pytest.raises(coherence.SepListingPopulationIncomplete,
                       match="identical partial SEP traversals"):
        list(guarded(
            sharadar.SEP,
            {"date.gte": "2026-08-18", "date.lte": "2026-08-18"}))


def test_legitimate_cross_section_contraction_is_predicted_by_tickers():
    # Five securities legitimately ended on the prior session.  The daily
    # completeness witness expects 95 rows, not yesterday's population of 100.
    tickers = [
        _ticker_row(i, last=("2026-08-17" if i < 5 else "2026-08-18"))
        for i in range(100)
    ]
    complete = [_sep_row(i) for i in range(5, 100)]

    def fetch(table, params=None, **_kwargs):
        if table == sharadar.TICKERS:
            return list(tickers)
        if table == sharadar.SEP:
            return list(complete)
        return []

    guarded = coherence.StableSharadarFetch(
        fetch, after_session="2026-08-17")
    guarded(sharadar.TICKERS)
    rows = list(guarded(
        sharadar.SEP,
        {"date.gte": "2026-08-18", "date.lte": "2026-08-18"}))
    assert len(rows) == 95


def test_calibrated_daily_listing_floor_allows_measured_sparse_tail():
    listings = [
        universe.Listing(
            permaticker=f"P-{i:04d}", ticker=f"T{i:04d}",
            first_session="2000-01-03", last_session="2026-08-18")
        for i in range(1000)
    ]
    observed = {"2026-08-18": {f"T{i:04d}" for i in range(999)}}
    # Exactly 99.9%; this is source completeness, not investability.
    coherence.assert_daily_sep_listing_population(observed, listings)


class _FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, _sql, _params=()):
        self.conn.query += 1

    def fetchone(self):
        assert self.conn.query == 1
        return (self.conn.corpus_lo, self.conn.corpus_hi)

    def fetchall(self):
        assert self.conn.query == 2
        return list(self.conn.candidates)


class _FakeConn:
    def __init__(self, candidates):
        self.corpus_lo = "2000-01-03"
        self.corpus_hi = "2026-08-17"
        self.candidates = candidates
        self.query = 0

    def cursor(self):
        return _FakeCursor(self)


def test_forward_only_listing_extension_does_not_reinterpret_history():
    # Normal daily shape: yesterday's lastpricedate advances into today's
    # unpublished session.  Clipped to published history, nothing changes.
    conn = _FakeConn([
        ("P1", "AAA", True, True,
         "2000-01-03", "2026-08-17",
         "2000-01-03", "2026-08-18"),
    ])
    universe.assert_candidate_listing_history_safe(conn, run_id="run-1")


def test_historical_listing_narrowing_is_refused_before_publication():
    conn = _FakeConn([
        ("P1", "AAA", True, True,
         "2000-01-03", "2026-08-17",
         "2010-01-04", "2026-08-18"),
    ])
    with pytest.raises(universe.HistoricalIdentityMutation,
                       match="re-key/tombstone"):
        universe.assert_candidate_listing_history_safe(conn, run_id="run-1")


def test_stable_partial_tickers_cannot_common_mode_false_green_with_sep():
    # A previously published historical listing disappears completely from an
    # otherwise stable full-snapshot candidate.  Repetition is not authority for
    # deleting that identity from the securities master.
    conn = _FakeConn([
        ("P1", "AAA", True, False,
         "2000-01-03", "2020-12-31", None, None),
    ])
    with pytest.raises(universe.HistoricalIdentityMutation,
                       match="changes or omits"):
        universe.assert_candidate_listing_history_safe(conn, run_id="run-1")


def test_new_listing_pair_may_start_after_but_not_inside_published_history():
    future = _FakeConn([
        ("P2", "IPO", False, True, None, None,
         "2026-08-18", "2026-08-18"),
    ])
    universe.assert_candidate_listing_history_safe(future, run_id="run-2")

    historical = _FakeConn([
        ("P2", "OLD", False, True, None, None,
         "2015-01-02", "2020-12-31"),
    ])
    with pytest.raises(universe.HistoricalIdentityMutation):
        universe.assert_candidate_listing_history_safe(
            historical, run_id="run-3")
