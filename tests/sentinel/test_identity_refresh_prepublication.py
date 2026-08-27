"""Prepublication proof must bind to daily without acquiring write authority."""
from __future__ import annotations

from contextlib import contextmanager
import datetime as dt
from types import SimpleNamespace

import pytest

from sentinel.feed import (
    coherence, identity_refresh, ingest, maintenance, recovery,
    sep_reconciliation, sharadar, snapshot_source, source_authority, universe)


def test_pinned_initial_tickers_fetch_serves_proven_candidate_once():
    candidate = [{"table": "SEP", "ticker": "YHNAU", "permaticker": 642732}]
    live_calls = []

    def live(table, params=None, **kwargs):
        live_calls.append((table, params, kwargs))
        return [{"table": "SEP", "ticker": "YHNAU", "permaticker": 642732}]

    fetch = identity_refresh.PinnedInitialTickersFetch(live, candidate)
    assert list(fetch(sharadar.TICKERS)) == candidate
    assert live_calls == []
    assert list(fetch(sharadar.TICKERS)) == candidate
    assert len(live_calls) == 1


def test_prevalidation_is_noop_when_cursor_already_covers_boundary(monkeypatch):
    monkeypatch.setattr(
        identity_refresh.maintenance_impl, "load_sep_cursor",
        lambda conn: SimpleNamespace(processed_through=dt.date(2026, 8, 25)))
    monkeypatch.setattr(
        identity_refresh.maintenance_impl, "_stable_rows",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("already-covered proof must not fetch source")))
    resolver = universe.IdentityResolver([])
    assert identity_refresh.prevalidate_pending_sep_mutations(
        object(), fetch=lambda *a, **k: (), through="2026-08-24",
        resolver=resolver) == []


def test_prevalidation_uses_candidate_resolver_without_cursor_write(monkeypatch):
    monkeypatch.setattr(
        identity_refresh.maintenance_impl, "load_sep_cursor",
        lambda conn: SimpleNamespace(processed_through=dt.date(2026, 8, 23)))
    monkeypatch.setattr(
        identity_refresh.maintenance_impl, "_retained_market_bounds",
        lambda conn: ("2026-08-01", "2026-08-21"))
    rows = [{
        "ticker": "YHNAU", "date": "2026-08-21",
        "closeunadj": 11.04, "lastupdated": "2026-08-24",
    }]
    monkeypatch.setattr(
        identity_refresh.maintenance_impl, "_stable_rows",
        lambda fetch, table, params: rows)
    monkeypatch.setattr(
        identity_refresh.maintenance_impl, "_write_cursor",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("prevalidation must not move the CDC cursor")))

    resolver = universe.IdentityResolver([
        universe.Listing("642732", "YHNAU", "2024-11-08", "2026-08-25")])
    assert identity_refresh.prevalidate_pending_sep_mutations(
        object(), fetch=lambda *a, **k: (), through="2026-08-24",
        resolver=resolver) == ["2026-08-21"]


def test_prevalidation_refuses_source_row_outside_exact_lastupdated_envelope(
        monkeypatch):
    monkeypatch.setattr(
        identity_refresh.maintenance_impl, "load_sep_cursor",
        lambda conn: SimpleNamespace(processed_through=dt.date(2026, 8, 23)))
    monkeypatch.setattr(
        identity_refresh.maintenance_impl, "_retained_market_bounds",
        lambda conn: ("2026-08-01", "2026-08-21"))

    def malformed_source(table, params=None, **kwargs):
        assert table == sharadar.SEP
        return [{
            "ticker": "YHNAU", "date": "2026-08-21",
            "closeunadj": 11.04, "lastupdated": "2026-08-25",
        }]

    resolver = universe.IdentityResolver([
        universe.Listing("642732", "YHNAU", "2024-11-08", "2026-08-25")])
    with pytest.raises(source_authority.SepUpdateEnvelopeViolation):
        identity_refresh.prevalidate_pending_sep_mutations(
            object(), fetch=malformed_source, through="2026-08-24",
            resolver=resolver)


def test_production_daily_prevalidates_exact_candidate_before_publication(
        monkeypatch):
    events = []
    candidate = [{
        "table": "SEP", "ticker": "YHNAU", "permaticker": 642732,
        "category": "Domestic Common Stock", "sector": "Industrials",
        "relatedtickers": "", "firstpricedate": "2024-11-08",
        "lastpricedate": "2026-08-25", "isdelisted": "N",
    }]

    def source(table, params=None, **kwargs):
        events.append(("live-source", table))
        return [dict(row) for row in candidate]

    @contextmanager
    def lock(_conn):
        yield

    monkeypatch.setattr(snapshot_source, "fetch_table", source)
    monkeypatch.setattr(ingest, "_validate_source_before_run", lambda fetch: None)
    monkeypatch.setattr(
        ingest._impl.feed_store, "corpus_write_lock", lambda conn: lock(conn))
    monkeypatch.setattr(ingest, "_recover_before_run", lambda conn: None)
    monkeypatch.setattr(maintenance, "load_sep_cursor", lambda conn: object())
    monkeypatch.setattr(recovery, "failed_live_candidates", lambda conn: [])
    monkeypatch.setattr(
        ingest._impl.feed_store, "latest_visible_session",
        lambda conn: "2026-08-21")
    monkeypatch.setattr(
        recovery, "extended_overlap_days", lambda conn, requested: requested)
    monkeypatch.setattr(
        identity_refresh, "stable_current_tickers",
        lambda fetch: events.append("candidate-proved") or candidate)
    monkeypatch.setattr(
        identity_refresh, "assert_candidate_history_safe",
        lambda conn, rows: events.append("history-safe"))
    candidate_resolver = universe.IdentityResolver([
        universe.Listing("642732", "YHNAU", "2024-11-08", "2026-08-25")])
    monkeypatch.setattr(
        identity_refresh, "resolver_with_candidate",
        lambda conn, rows: events.append("candidate-resolver") or candidate_resolver)
    monkeypatch.setattr(
        identity_refresh, "prevalidate_pending_sep_mutations",
        lambda conn, **kwargs: events.append("cdc-prevalidated") or [])
    monkeypatch.setattr(
        coherence, "StableSharadarFetch",
        lambda fetch, after_session=None: fetch)

    def daily_locked(conn, **kwargs):
        events.append("daily-open")
        # The first TICKERS observation must be the pre-proven candidate and must
        # not hit the live source. The second call delegates live authority.
        got = list(kwargs["fetch"](sharadar.TICKERS))
        assert got == candidate
        events.append("daily-first-tickers")
        list(kwargs["fetch"](sharadar.TICKERS))
        return SimpleNamespace(run_id="daily-candidate")

    monkeypatch.setattr(ingest._impl, "_daily_locked", daily_locked)
    monkeypatch.setattr(
        ingest, "_finish_publication_or_refuse",
        lambda conn, progress: events.append("daily-published") or object())
    monkeypatch.setattr(
        sep_reconciliation, "reconcile_next",
        lambda conn, **kwargs: events.append("sep-keyset"))
    monkeypatch.setattr(
        maintenance, "reconcile_sep_mutations",
        lambda conn, **kwargs: events.append("sep-cdc"))
    monkeypatch.setattr(
        maintenance, "reconcile_actions_if_due",
        lambda conn, **kwargs: events.append("actions"))
    monkeypatch.setattr(
        ingest, "_prove_recent_frontier",
        lambda conn, **kwargs: events.append("recent-proof"))

    ingest.daily(object(), fetch=source, today="2026-08-25")

    assert events.index("candidate-proved") < events.index("cdc-prevalidated")
    assert events.index("cdc-prevalidated") < events.index("daily-open")
    assert events.index("daily-first-tickers") < events.index("daily-published")
    assert events.index("daily-published") < events.index("sep-keyset")
    assert events.index("sep-keyset") < events.index("sep-cdc")
