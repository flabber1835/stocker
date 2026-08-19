from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from unittest import mock

from sentinel.feed import maintenance, readiness, recent_reconciliation as R


def _cursor(day="2026-08-19", version=7):
    return maintenance.SourceCursor(
        kind=R.CURSOR_KIND,
        processed_through=dt.date.fromisoformat(day),
        publication_version=version)


def test_recent_reconciliation_splits_cross_year_window_without_gaps(monkeypatch):
    sessions = ["2025-12-30", "2025-12-31", "2026-01-02"]
    monkeypatch.setattr(R, "REQUIRED_CLOSES", len(sessions))
    monkeypatch.setattr(R.calendar, "previous_sessions",
                        lambda through, count: list(sessions))
    calls = []

    def reconcile(conn, *, fetch, year, start, end):
        calls.append((year, start, end, fetch))
        return object()

    monkeypatch.setattr(R.sep_reconciliation, "reconcile_year", reconcile)
    monkeypatch.setattr(R.publication, "require_current",
                        lambda conn: SimpleNamespace(version=11))
    monkeypatch.setattr(
        R.maintenance, "_write_cursor",
        lambda conn, **kwargs: kwargs)

    result = R.reconcile_recent(object(), through="2026-01-02")
    assert [(y, lo, hi) for y, lo, hi, _ in calls] == [
        (2025, "2025-12-30", "2025-12-31"),
        (2026, "2026-01-01", "2026-01-02"),
    ]
    assert result["through"] == dt.date(2026, 1, 2)
    assert result["publication_version"] == 11


def test_readiness_refuses_missing_recent_complete_proof():
    result = readiness._impl.Readiness()
    with (mock.patch.object(readiness._recent, "load_cursor", return_value=None),
          mock.patch.object(readiness._publication, "require_current",
                            return_value=SimpleNamespace(version=8))):
        readiness._add_recent_check(
            object(), result,
            source_day=dt.date(2026, 8, 19),
            frontier_day=dt.date(2026, 8, 19))
    assert not result.ready
    assert result.failures[0].name == "SEP recent complete reconciliation"


def test_readiness_refuses_proof_for_preceding_corpus_version():
    result = readiness._impl.Readiness()
    with (mock.patch.object(readiness._recent, "load_cursor",
                            return_value=_cursor(version=7)),
          mock.patch.object(readiness._publication, "require_current",
                            return_value=SimpleNamespace(version=8))):
        readiness._add_recent_check(
            object(), result,
            source_day=dt.date(2026, 8, 19),
            frontier_day=dt.date(2026, 8, 19))
    assert not result.ready
    assert "current publication is v8" in result.failures[0].detail


def test_readiness_accepts_exact_frontier_and_publication_proof():
    result = readiness._impl.Readiness()
    with (mock.patch.object(readiness._recent, "load_cursor",
                            return_value=_cursor(version=8)),
          mock.patch.object(readiness._publication, "require_current",
                            return_value=SimpleNamespace(version=8))):
        readiness._add_recent_check(
            object(), result,
            source_day=dt.date(2026, 8, 19),
            frontier_day=dt.date(2026, 8, 19))
    assert result.ready
    assert result.checks[0].status == readiness._impl.PASS
