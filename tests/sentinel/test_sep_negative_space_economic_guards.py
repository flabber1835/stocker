"""Regression coverage for SEP negative-space economic preservation."""
from __future__ import annotations

import datetime as dt

import pytest

from sentinel.feed import sep_negative_space_guarded as guarded
from sentinel.feed import sep_reconciliation as recon
from sentinel.feed import snapshot_source


class _RowsCursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, _sql, _params=()):
        self._rows = list(self.rows)

    def fetchall(self):
        return list(self._rows)


class _RowsConn:
    def __init__(self, rows):
        self.rows = rows

    def cursor(self):
        return _RowsCursor(self.rows)


def _key():
    return [{"security_id": "P:1", "session": "2026-04-02", "ticker": "AAA"}]


def test_retirement_refuses_fractional_split_event(monkeypatch):
    monkeypatch.setattr(guarded.core, "_load_retire_table", lambda *a, **k: None)
    monkeypatch.setattr(
        guarded.publication, "effective_split_ratio", lambda alias: "b.split_ratio")
    monkeypatch.setattr(
        guarded.publication, "visible_predicate", lambda alias: "TRUE")
    conn = _RowsConn([("P:1", dt.date(2026, 4, 2), "AAA", 1.25, 0.0)])

    with pytest.raises(
            guarded.SepNegativeSpaceRefused,
            match="carries an effective split event"):
        guarded._assert_retired_rows_have_no_economic_events(conn, _key())


def test_retirement_refuses_dividend_entitlement(monkeypatch):
    monkeypatch.setattr(guarded.core, "_load_retire_table", lambda *a, **k: None)
    monkeypatch.setattr(
        guarded.publication, "effective_split_ratio", lambda alias: "b.split_ratio")
    monkeypatch.setattr(
        guarded.publication, "visible_predicate", lambda alias: "TRUE")
    conn = _RowsConn([("P:1", dt.date(2026, 4, 2), "AAA", 1.0, 1.0)])

    with pytest.raises(
            guarded.SepNegativeSpaceRefused,
            match="carries a dividend entitlement"):
        guarded._assert_retired_rows_have_no_economic_events(conn, _key())


def test_retirement_allows_economically_empty_row(monkeypatch):
    monkeypatch.setattr(guarded.core, "_load_retire_table", lambda *a, **k: None)
    monkeypatch.setattr(
        guarded.publication, "effective_split_ratio", lambda alias: "b.split_ratio")
    monkeypatch.setattr(
        guarded.publication, "visible_predicate", lambda alias: "TRUE")
    conn = _RowsConn([("P:1", dt.date(2026, 4, 2), "AAA", 1.0, 0.0)])

    guarded._assert_retired_rows_have_no_economic_events(conn, _key())


def test_fractional_bridge_uses_unsnapped_price_evidence():
    prev = (10.0, 15.0)
    successor = (10.0, 10.0, 1.5)
    required = guarded.domains.unsnapped_split_ratio(
        prev[0], prev[1], successor[0], successor[1])
    assert required == pytest.approx(1.5)
    assert guarded.split_ratio_matches(successor[2], required)[0]


def test_production_rotating_reconciliation_uses_source_day(monkeypatch):
    class FixedDatetime(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 6, tzinfo=tz)

    monkeypatch.setattr(recon.dt, "datetime", FixedDatetime)
    market = dt.date(2026, 9, 4)
    assert recon._production_source_ceiling(
        snapshot_source.fetch_table, market) == dt.date(2026, 9, 6)


def test_injected_reconciliation_keeps_market_ceiling():
    market = dt.date(2026, 9, 4)

    def injected(*_args, **_kwargs):
        return iter(())

    assert recon._production_source_ceiling(injected, market) == market
