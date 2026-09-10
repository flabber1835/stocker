"""Source/replay authority regressions that execute locally and in replay CI."""
import datetime as dt
import json
from types import SimpleNamespace

import pytest

from sentinel.feed import calendar, ingest, maintenance_impl as maintenance, sharadar
from sentinel.feed import source_authority
from sentinel.feed.source_authority import fetch as source_fetch


def _reference_rows(days, tickers=("SPY", "BIL")):
    return [{"ticker": ticker, "date": day, "open": 99.0, "close": 100.0,
             "closeadj": 101.0, "closeunadj": 102.0}
            for day in days for ticker in tickers]


def _read_recovery(rows, days):
    guarded = source_authority.StableSharadarFetch(
        lambda *args, **kwargs: iter(rows), reference_recovery=True)
    return list(guarded(sharadar.SFP, {
        "ticker": "SPY,BIL", "date.gte": days[0], "date.lte": days[-1]}))


@pytest.mark.parametrize("count", [1, 41, 42])
@pytest.mark.parametrize("ticker", ["SPY", "BIL"])
@pytest.mark.parametrize("offset", [0, -1])
def test_daily_recovery_requires_both_reference_boundaries(count, ticker, offset):
    days = calendar.previous_sessions("2026-08-18", count)
    rows = [row for row in _reference_rows(days)
            if (row["ticker"], row["date"]) != (ticker, days[offset])]
    with pytest.raises(source_authority.SourceAuthorityRefused, match="SFP recovery"):
        _read_recovery(rows, days)


@pytest.mark.parametrize("count", [1, 41, 42])
def test_complete_daily_recovery_passes(count):
    days = calendar.previous_sessions("2026-08-18", count)
    rows = _reference_rows(days)
    assert _read_recovery(rows, days) == rows


def test_same_day_guard_falsifier_reaches_missing_bil(monkeypatch):
    monkeypatch.setattr(source_fetch, "_require_complete_recovery_reference_tail",
                        lambda rows, params: rows)
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_daily_recovery_requires_both_reference_boundaries(41, "BIL", 0)


def test_injected_seed_retains_its_explicit_source_contract():
    rows = _reference_rows(["2021-12-30", "2021-12-31"], tickers=("SPY",))
    tracked, _ = ingest._seed_source(
        lambda *args, **kwargs: iter(rows), final_hi="2021-12-31")
    assert list(tracked(sharadar.SFP, {
        "ticker": "SPY,BIL", "date.gte": "2021-01-01",
        "date.lte": "2021-12-31"})) == rows


class _MarkerConnection:
    """Small cursor ledger; economic rows can change independently of markers."""
    def __init__(self):
        self.markers = {}
        self.bars = [("SEC-AAA", dt.date(2026, 3, 3), 100.0, 100.0,
                      99.0, 1000.0, 1.0, 0.0)]

    def cursor(self):
        return _MarkerCursor(self)


class _MarkerCursor:
    def __init__(self, conn):
        self.conn = conn
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def execute(self, query, params):
        if query.startswith("DELETE FROM sentinel_processed_sessions"):
            self.conn.markers = {
                key: value for key, value in self.conn.markers.items()
                if not params[1] <= value["session"] <= params[2]}
        elif query.startswith("INSERT INTO sentinel_processed_sessions"):
            self.conn.markers[params[0]] = json.loads(params[2])
        elif query.startswith("SELECT cursor_name"):
            self.rows = [(key, value["session"], value)
                         for key, value in sorted(self.conn.markers.items())]
        elif "FROM sentinel_bars" in query:
            self.rows = list(self.conn.bars)
        else:
            raise AssertionError(query)

    def fetchall(self):
        return self.rows


@pytest.fixture
def marker_state(monkeypatch):
    conn = _MarkerConnection()
    row = {"kind": "SPLIT_DISAGREEMENT", "ticker": "AAA",
           "session": "2026-03-03", "detail": "stated=2 derived=1",
           "publication_version": 7}
    monkeypatch.setattr(maintenance, "_ensure_cursor_table", lambda conn: None)
    monkeypatch.setattr(maintenance.publication, "require_current",
                        lambda conn: SimpleNamespace(version=9))
    monkeypatch.setattr(maintenance.anomalies, "active_rows",
                        lambda *args, **kwargs: [row])
    return conn, row


def _record(conn, version):
    maintenance._record_unresolved_split_replay_markers(
        conn, replay_windows=[("2026-03-02", "2026-03-04")],
        replayed_publication_version=version)


def _pending(conn):
    return maintenance._unresolved_split_replay_rows(
        conn, market_start="2026-03-02", market_end="2026-03-04")


def test_old_blocker_cannot_earn_completed_replay_authority(marker_state):
    conn, row = marker_state
    _record(conn, 8)
    assert conn.markers == {}
    assert _pending(conn) == [row]


def test_evaluated_unchanged_economics_replay_once(marker_state):
    conn, row = marker_state
    _record(conn, 7)
    assert len(conn.markers) == 1
    assert _pending(conn) == []
    row["publication_version"] = 8
    assert _pending(conn) == []


def test_price_correction_earns_new_replay_with_same_disposition(marker_state):
    conn, row = marker_state
    _record(conn, 7)
    assert _pending(conn) == []
    conn.bars[0] = (*conn.bars[0][:2], 101.0, *conn.bars[0][3:])
    assert _pending(conn) == [row]
    row["publication_version"] = 8
    _record(conn, 8)
    assert _pending(conn) == []


def test_legacy_marker_must_reearn_source_binding(marker_state):
    conn, row = marker_state
    _record(conn, 7)
    marker = next(iter(conn.markers.values()))
    marker["schema"] = "sharadar-unresolved-split-replay/v1"
    del marker["source_sha256"]
    assert _pending(conn) == [row]


def test_broken_price_binding_is_killed(marker_state, monkeypatch):
    monkeypatch.setattr(maintenance, "_unresolved_split_source_digest",
                        lambda *args: "a" * 64)
    with pytest.raises(AssertionError):
        test_price_correction_earns_new_replay_with_same_disposition(marker_state)
