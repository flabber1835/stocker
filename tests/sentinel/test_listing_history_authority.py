"""Published listing intervals cannot be reinterpreted by later metadata."""
import pytest
from sentinel.feed import universe


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
