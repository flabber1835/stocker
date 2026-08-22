"""#185/#108: legacy multi-candidate state converges through full feed-seed."""
from __future__ import annotations

from contextlib import contextmanager

import pytest

from sentinel.feed import ingest, maintenance, recovery, reseed


def _pending(run_id: str):
    return recovery.PendingPublication(
        run_id=run_id, kind="daily", date_from="2026-08-17",
        date_to="2026-08-18", chunks_total=4, chunks_done=4,
        rows_written=10, rows_dropped=0)


def test_seed_chooses_complete_reseed_instead_of_ordering_two_successes(monkeypatch):
    calls = []
    monkeypatch.setattr(
        ingest._impl.feed_store, "reclaim_orphans",
        lambda conn: calls.append("reclaim"))
    monkeypatch.setattr(
        recovery, "pending_validated",
        lambda conn: [_pending("run-a"), _pending("run-b")])
    monkeypatch.setattr(
        recovery, "live_candidates",
        lambda conn: [
            recovery.LiveCandidate("run-a", "daily", "success"),
            recovery.LiveCandidate("run-b", "daily", "success"),
        ])
    monkeypatch.setattr(
        recovery, "resume_pending_publication",
        lambda *a, **k: calls.append("WRONG-resume"))
    expected = recovery.FullReseedPlan(
        "1997-01-02", "2026-08-18", ("run-a", "run-b"))
    monkeypatch.setattr(
        recovery, "prepare_full_reseed",
        lambda conn, **kwargs: calls.append(("reseed", kwargs)) or expected)

    assert ingest._recover_before_seed(
        object(), date_from="1998-01-01", date_to="2026-08-18") == expected
    assert calls == [
        "reclaim",
        ("reseed", {"date_from": "1998-01-01", "date_to": "2026-08-18"}),
    ]


def test_seed_still_resumes_one_complete_pending_candidate_cheaply(monkeypatch):
    calls = []
    pending = _pending("run-a")
    monkeypatch.setattr(
        ingest._impl.feed_store, "reclaim_orphans", lambda conn: None)
    monkeypatch.setattr(recovery, "pending_validated", lambda conn: [pending])
    monkeypatch.setattr(
        recovery, "live_candidates",
        lambda conn: [recovery.LiveCandidate("run-a", "daily", "success")])
    monkeypatch.setattr(
        recovery, "resume_pending_publication",
        lambda conn: calls.append("resume"))
    monkeypatch.setattr(
        recovery, "prepare_full_reseed",
        lambda *a, **k: calls.append("WRONG-reseed"))

    plan = ingest._recover_before_seed(
        object(), date_from="1998-01-01", date_to="2026-08-18")
    assert plan.retired_run_ids == ()
    assert calls == ["resume"]


class _Cursor:
    def __init__(self, conn):
        self.conn = conn
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=()):
        self.conn.sql.append((" ".join(str(sql).split()), params))
        self.rowcount = 2


class _Conn:
    def __init__(self):
        self.sql = []
        self.commits = 0

    def cursor(self):
        return _Cursor(self)

    def commit(self):
        self.commits += 1


def test_prepare_full_reseed_widens_to_candidate_rows_and_retires_no_publication(
        monkeypatch):
    conn = _Conn()
    aborted = []
    monkeypatch.setattr(
        "sentinel.feed.store._assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(
        recovery, "pending_validated",
        lambda conn: [_pending("run-a"), _pending("run-b")])
    monkeypatch.setattr(
        recovery, "live_candidates",
        lambda conn: [
            recovery.LiveCandidate("run-a", "daily", "success"),
            recovery.LiveCandidate("run-b", "sep_mutations", "failed"),
        ])
    monkeypatch.setattr(
        recovery, "_candidate_session_bounds",
        lambda conn, ids: ("1997-07-01", "2026-08-18"))
    monkeypatch.setattr(
        "sentinel.feed.actions.abort_run",
        lambda conn, **kwargs: aborted.append(("actions", kwargs["run_id"])))
    monkeypatch.setattr(
        "sentinel.feed.anomalies.abort_run",
        lambda conn, **kwargs: aborted.append(("anomalies", kwargs["run_id"])))

    plan = recovery.prepare_full_reseed(
        conn, date_from="1998-01-01", date_to="2026-08-18")

    assert plan == recovery.FullReseedPlan(
        "1997-07-01", "2026-08-18", ("run-a", "run-b"))
    update_sql, params = conn.sql[-1]
    assert "SET status='failed'" in update_sql
    assert "NOT EXISTS" in update_sql and "sentinel_corpus_publications" in update_sql
    assert params[1:] == ("run-a", "run-b")
    assert aborted == [
        ("actions", "run-a"), ("anomalies", "run-a"),
        ("actions", "run-b"), ("anomalies", "run-b"),
    ]
    assert conn.commits == 1


def test_failed_actions_replay_cleanup_is_scoped_by_kind_and_market_boundary(
        monkeypatch):
    conn = _Conn()
    monkeypatch.setattr(
        "sentinel.feed.store._assert_corpus_locked", lambda conn: None)

    outside = recovery.retire_failed_action_reconcile_bars_outside_market(
        conn, run_id="new-run", market_start="2025-07-01",
        market_end="2026-08-21")
    inside = recovery.retire_failed_action_reconcile_bars_in_window(
        conn, run_id="new-run", start="2025-07-01", end="2025-07-03")

    assert (outside, inside) == (2, 2)
    outside_sql, outside_params = conn.sql[-2]
    inside_sql, inside_params = conn.sql[-1]
    for sql in (outside_sql, inside_sql):
        assert "r.kind='actions_reconcile'" in sql
        assert "r.status='failed'" in sql
        assert "sentinel_corpus_publications" in sql
    assert "b.session<%s OR b.session>%s" in outside_sql
    assert outside_params == ("new-run", "2025-07-01", "2026-08-21")
    assert "b.session BETWEEN %s AND %s" in inside_sql
    assert inside_params == ("new-run", "2025-07-01", "2025-07-03")
    assert conn.commits == 2


class _Progress:
    run_id = "new-seed"
    kind = "seed"
    rows_written = 0
    rows_dropped = 0


class _Run:
    def __init__(self, conn, kind, **kwargs):
        self.progress = _Progress()

    @contextmanager
    def chunk(self, label):
        yield self.progress

    def finish(self, status="success", error=None):
        assert status == "success"


def _full_reseed_fixture(monkeypatch, *, actions_rows):
    events = []
    action_requests = []
    final_scopes = []
    monkeypatch.setattr(reseed.feed_store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(reseed.feed_store, "IngestRun", _Run)
    monkeypatch.setattr(
        reseed.sharadar, "year_chunks",
        lambda lo, hi: [("2025-12-31", "2025-12-31"),
                        ("2026-01-01", "2026-01-02")])
    monkeypatch.setattr(
        reseed.universe, "write_universe", lambda *a, **k: 1)
    monkeypatch.setattr(reseed.feed_store, "write_actions", lambda *a, **k: 1)
    def write_sfp_family(_conn, rows, **kwargs):
        materialized = tuple(rows)
        events.append(("sfp", tuple(row["ticker"] for row in materialized),
                       kwargs))
        return len(materialized)

    monkeypatch.setattr(
        reseed.feed_store, "write_spy_total_return", write_sfp_family)
    monkeypatch.setattr(
        reseed.feed_store, "write_defensive_bars", write_sfp_family)
    monkeypatch.setattr(
        maintenance, "_active_action_rows", lambda conn: {})
    monkeypatch.setattr(
        "sentinel.feed.ingest_impl._action_maps",
        lambda *a, **k: ({}, {}, [], []))
    monkeypatch.setattr(
        "sentinel.feed.ingest_impl._ordered_sep",
        lambda conn, rows, **kwargs: rows)
    monkeypatch.setattr(
        "sentinel.feed.ingest_impl._persist_chunk_evidence",
        lambda *a, **k: None)
    monkeypatch.setattr(
        reseed.domains, "normalise_sep_rows",
        lambda rows, **kwargs: list(rows))

    def previous(conn, lo):
        events.append(("previous", lo))
        return {}

    monkeypatch.setattr(reseed.feed_store, "previous_observations", previous)

    def write_bars(conn, bars, **kwargs):
        materialized = tuple(bars)
        events.append(("write", materialized))
        return len(materialized)

    monkeypatch.setattr(reseed.feed_store, "write_bars", write_bars)

    def retire(conn, **kwargs):
        events.append(("retire", kwargs["start"], kwargs["end"]))
        return 1

    monkeypatch.setattr(
        recovery, "retire_failed_bars_in_stable_seed_window", retire)

    def covered(conn, **kwargs):
        final_scopes.append(("covered", kwargs))
        events.append("covered")

    monkeypatch.setattr(
        recovery, "assert_full_reseed_covered_live_rows", covered)

    def retire_nonbar(conn, **kwargs):
        final_scopes.append(("retired", kwargs))
        events.append("retire-nonbar")
        return {}

    monkeypatch.setattr(
        recovery, "retire_failed_nonbar_rows_after_full_seed", retire_nonbar)
    monkeypatch.setattr(
        "sentinel.feed.ingest_impl._publish_version",
        lambda *a, **k: events.append("publish"))

    def fetch(table, params=None):
        if table == reseed.sharadar.ACTIONS:
            action_requests.append(dict(params or {}))
            return list(actions_rows)
        if table == reseed.sharadar.SEP:
            return [params["date.gte"]]
        if table == reseed.sharadar.SFP:
            return [
                {"ticker": "SPY", "date": params["date.lte"],
                 "closeadj": 600.0},
                {"ticker": "BIL", "date": params["date.lte"],
                 "open": 90.9, "close": 91.0, "closeadj": 91.1,
                 "closeunadj": 91.0},
            ]
        return []

    return events, action_requests, final_scopes, fetch


def test_full_reseed_uses_complete_actions_scope_and_retires_bars_before_next_predecessor(
        monkeypatch):
    action = {
        "ticker": "AAA", "date": "2025-01-02", "action": "dividend",
        "name": None, "value": 1.0, "contraticker": None, "contraname": None,
    }
    events, action_requests, final_scopes, fetch = _full_reseed_fixture(
        monkeypatch, actions_rows=[action])

    reseed.full_reseed_locked(
        object(), date_from="2025-12-31", date_to="2026-01-02",
        fetch=fetch, resolve_identity=lambda ticker, session: ticker)

    assert action_requests == [{
        "date.gte": maintenance.ACTIONS_FULL_WINDOW_START,
        "date.lte": "2026-01-02",
    }]
    first_retire = events.index(("retire", "2025-12-31", "2025-12-31"))
    second_previous = events.index(("previous", "2026-01-01"))
    assert first_retire < second_previous
    expected_scope = {
        "run_id": "new-seed",
        "market_start": "2025-12-31",
        "actions_start": maintenance.ACTIONS_FULL_WINDOW_START,
        "end": "2026-01-02",
    }
    assert final_scopes == [
        ("covered", expected_scope), ("retired", expected_scope)]
    assert [event[1] for event in events if isinstance(event, tuple)
            and event[0] == "sfp"] == [("SPY",), ("BIL",)]
    assert events[-3:] == ["covered", "retire-nonbar", "publish"]


def test_full_reseed_refuses_stably_empty_actions_before_any_bar_retirement(
        monkeypatch):
    events, _requests, _scopes, fetch = _full_reseed_fixture(
        monkeypatch, actions_rows=[])

    with pytest.raises(maintenance.SharadarMutationRefused,
                       match="zero rows"):
        reseed.full_reseed_locked(
            object(), date_from="2025-12-31", date_to="2026-01-02",
            fetch=fetch, resolve_identity=lambda ticker, session: ticker)

    assert not any(isinstance(event, tuple) and event[0] == "retire"
                   for event in events)
    assert "publish" not in events
