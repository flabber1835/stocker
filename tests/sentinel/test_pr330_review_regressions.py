from __future__ import annotations

import datetime as dt
import os

import pytest

from sentinel.feed import sep_negative_space_guarded as guarded
from sentinel.feed import sep_reconciliation as recon


class _SeqCursor:
    def __init__(self, conn):
        self.conn = conn
        self._row = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, _sql, _params=()):
        self._row = self.conn.responses.pop(0)

    def fetchone(self):
        return self._row


class _SeqConn:
    def __init__(self, responses):
        self.responses = list(responses)

    def cursor(self):
        return _SeqCursor(self)


def _key(session="2026-04-02"):
    return [{"security_id": "P:1", "session": session, "ticker": "AAA"}]


@pytest.mark.parametrize("value", [None, 0.0, -0.25])
def test_retirement_refuses_unusable_current_actions_dividend(monkeypatch, value):
    from sentinel.feed import ingest_impl

    rows = [{
        "ticker": "AAA", "date": "2026-04-02",
        "action": "dividend", "value": value,
    }]
    monkeypatch.setattr(
        ingest_impl, "_action_maps",
        lambda *a, **k: ({}, {}, rows, []))

    with pytest.raises(
            guarded.SepNegativeSpaceRefused,
            match="current authoritative ACTIONS dividend entitlement"):
        guarded._assert_current_actions_have_no_retirement_events(object(), _key())


def test_retirement_refuses_prefix_removal_when_successor_has_derived_split(monkeypatch):
    monkeypatch.setattr(
        guarded.publication, "effective_split_ratio", lambda alias: "b.split_ratio")
    monkeypatch.setattr(
        guarded.publication, "visible_predicate", lambda alias: "TRUE")
    conn = _SeqConn([
        None,
        (50.0, 25.0, 2.0),
    ])

    with pytest.raises(
            guarded.SepNegativeSpaceRefused,
            match="no surviving predecessor remains"):
        guarded._assert_retirement_preserves_split_chain(conn, _key())


def test_retirement_allows_prefix_removal_when_successor_is_unit_split(monkeypatch):
    monkeypatch.setattr(
        guarded.publication, "effective_split_ratio", lambda alias: "b.split_ratio")
    monkeypatch.setattr(
        guarded.publication, "visible_predicate", lambda alias: "TRUE")
    conn = _SeqConn([
        None,
        (50.0, 50.0, 1.0),
    ])

    guarded._assert_retirement_preserves_split_chain(conn, _key())


def test_complete_export_source_spools_months_and_replays(monkeypatch):
    from sentinel.feed import snapshot_export

    calls = []

    def fetch_complete_sep(*, start, end):
        calls.append((start, end))
        return ([{
            "ticker": "AAA", "date": start,
            "open": "10", "close": "10", "closeunadj": "10",
            "volume": "100", "lastupdated": "2026-09-07",
        }], {
            "authority": "nasdaq-data-link-table-export/v1",
            "table": "SEP", "source_rows": 1,
            "data_snapshot_time": "2026-09-07T20:00:00+00:00",
            "last_refreshed_time": "2026-09-07T19:59:00+00:00",
        })

    monkeypatch.setattr(snapshot_export, "fetch_complete_sep", fetch_complete_sep)
    fetch, evidence = recon._complete_export_source(
        start="2026-01-15", end="2026-03-02")
    try:
        expected_params = {"date.gte": "2026-01-15", "date.lte": "2026-03-02"}
        first = list(fetch("SEP", expected_params))
        second = list(fetch("SEP", expected_params))
        assert first == second
        assert [row["date"] for row in first] == [
            "2026-01-15", "2026-02-01", "2026-03-01"]
        assert calls == [
            ("2026-01-15", "2026-01-31"),
            ("2026-02-01", "2026-02-28"),
            ("2026-03-01", "2026-03-02"),
        ]
        assert evidence["source_rows"] == 3
        assert len(evidence["parts"]) == 3
        path = fetch.cleanup.__closure__[0].cell_contents if fetch.cleanup.__closure__ else None
    finally:
        fetch.cleanup()

    if isinstance(path, str):
        assert not os.path.exists(path)
