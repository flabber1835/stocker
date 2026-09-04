from __future__ import annotations

import datetime as dt

import pytest

from sentinel.feed import ingest, maintenance, maintenance_impl, recent_reconciliation


FUTURE = dt.date(2026, 8, 28)
THROUGH = "2026-08-27"


def _future_cursor(kind: str) -> maintenance.SourceCursor:
    return maintenance.SourceCursor(
        kind=kind,
        processed_through=FUTURE,
        publication_version=17,
    )


def test_sep_future_cursor_refuses_before_vendor_fetch(monkeypatch):
    monkeypatch.setattr(
        maintenance_impl.store, "_assert_corpus_locked", lambda _conn: None)
    monkeypatch.setattr(
        maintenance,
        "load_sep_cursor",
        lambda _conn: _future_cursor("sharadar-sep-lastupdated/v1"),
    )

    calls = []

    def forbidden_fetch(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("future cursor must refuse before Sharadar is contacted")

    with pytest.raises(
        maintenance.SharadarMutationRefused,
        match="SEP mutation cursor .* is ahead of requested reconciliation",
    ):
        maintenance.reconcile_sep_mutations(
            object(), fetch=forbidden_fetch, through=THROUGH)

    assert calls == []


def test_daily_caller_accepts_vendor_cursor_ahead_of_market_target(monkeypatch):
    source_day = dt.datetime.now(dt.timezone.utc).date()
    market_target = source_day - dt.timedelta(days=1)
    current = maintenance.SourceCursor(
        kind="sharadar-sep-lastupdated/v1",
        processed_through=source_day,
        publication_version=17,
    )
    monkeypatch.setattr(ingest.maintenance, "load_sep_cursor", lambda _conn: current)
    monkeypatch.setattr(
        ingest.maintenance, "reconcile_sep_mutations",
        lambda *_args, **_kwargs: pytest.fail(
            "vendor cursor already covering market target must not reconcile backwards"),
    )

    assert ingest._reconcile_sep_for_market_target(
        object(), fetch=object(), target=market_target.isoformat()) is current


def test_daily_caller_refuses_vendor_cursor_beyond_source_observation_date(
        monkeypatch):
    source_day = dt.datetime.now(dt.timezone.utc).date()
    impossible = maintenance.SourceCursor(
        kind="sharadar-sep-lastupdated/v1",
        processed_through=source_day + dt.timedelta(days=1),
        publication_version=17,
    )
    monkeypatch.setattr(
        ingest.maintenance, "load_sep_cursor", lambda _conn: impossible)

    with pytest.raises(
        maintenance.SharadarMutationRefused,
        match="ahead of current source observation date",
    ):
        ingest._reconcile_sep_for_market_target(
            object(), fetch=object(), target=source_day.isoformat())


def test_actions_future_cursor_refuses_before_export_or_vendor_fetch(monkeypatch):
    monkeypatch.setattr(
        maintenance_impl.store, "_assert_corpus_locked", lambda _conn: None)
    monkeypatch.setattr(
        maintenance_impl,
        "load_actions_cursor",
        lambda _conn: _future_cursor(maintenance.ACTIONS_CURSOR_KIND),
    )

    calls = []

    def forbidden_fetch(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("future cursor must refuse before source traversal")

    with pytest.raises(
        maintenance.SharadarMutationRefused,
        match="ACTIONS reconciliation cursor .* is ahead of requested reconciliation",
    ):
        maintenance.reconcile_actions_if_due(
            object(), fetch=forbidden_fetch, through=THROUGH)

    assert calls == []


def test_recent_sep_future_cursor_refuses_before_complete_export(monkeypatch):
    monkeypatch.setattr(
        recent_reconciliation.store,
        "_assert_corpus_locked",
        lambda _conn: None,
    )
    monkeypatch.setattr(
        recent_reconciliation,
        "load_cursor",
        lambda _conn: _future_cursor(recent_reconciliation.CURSOR_KIND),
    )
    calls = []

    def forbidden_fetch(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("future recent cursor must refuse before export")

    with pytest.raises(
        maintenance.SharadarMutationRefused,
        match="recent SEP reconciliation cursor .* is ahead of requested reconciliation",
    ):
        recent_reconciliation.reconcile_recent(
            object(), through=THROUGH, fetch=forbidden_fetch)

    assert calls == []


def test_equal_sep_cursor_is_terminal_current_without_vendor_fetch(monkeypatch):
    monkeypatch.setattr(
        maintenance_impl.store, "_assert_corpus_locked", lambda _conn: None)
    current = maintenance.SourceCursor(
        kind="sharadar-sep-lastupdated/v1",
        processed_through=dt.date.fromisoformat(THROUGH),
        publication_version=17,
    )
    monkeypatch.setattr(maintenance, "load_sep_cursor", lambda _conn: current)

    def forbidden_fetch(*_args, **_kwargs):
        raise AssertionError("equal cursor should remain the legitimate current fast path")

    assert maintenance.reconcile_sep_mutations(
        object(), fetch=forbidden_fetch, through=THROUGH) == current
