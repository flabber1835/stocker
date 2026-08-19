"""#185/#108: legacy multi-candidate state converges through full feed-seed."""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

from sentinel.feed import ingest, recovery, reseed


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


def test_full_reseed_retires_each_old_bar_window_before_next_predecessor(
        monkeypatch):
    events = []
    monkeypatch.setattr(reseed.feed_store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(reseed.feed_store, "IngestRun", _Run)
    monkeypatch.setattr(
        reseed.sharadar, "year_chunks",
        lambda lo, hi: [("2025-12-31", "2025-12-31"),
                        ("2026-01-01", "2026-01-02")])
    monkeypatch.setattr(
        reseed.universe, "write_universe", lambda *a, **k: 1)
    monkeypatch.setattr(reseed.feed_store, "write_actions", lambda *a, **k: 1)
    monkeypatch.setattr(
        reseed.feed_store, "write_spy_total_return", lambda *a, **k: 1)
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
        events.append(("write", tuple(bars)))
        return len(tuple(bars))

    monkeypatch.setattr(reseed.feed_store, "write_bars", write_bars)

    def retire(conn, **kwargs):
        events.append(("retire", kwargs["start"], kwargs["end"]))
        return 1

    monkeypatch.setattr(
        recovery, "retire_failed_bars_in_stable_seed_window", retire)
    monkeypatch.setattr(
        recovery, "assert_full_reseed_covered_live_rows",
        lambda conn, **kwargs: events.append("covered"))
    monkeypatch.setattr(
        recovery, "retire_failed_nonbar_rows_after_full_seed",
        lambda conn, **kwargs: events.append("retire-nonbar") or {})
    monkeypatch.setattr(
        "sentinel.feed.ingest_impl._publish_version",
        lambda *a, **k: events.append("publish"))

    def fetch(table, params=None):
        if table == reseed.sharadar.SEP:
            return [params["date.gte"]]
        return []

    reseed.full_reseed_locked(
        object(), date_from="2025-12-31", date_to="2026-01-02",
        fetch=fetch, resolve_identity=lambda ticker, session: ticker)

    first_retire = events.index(("retire", "2025-12-31", "2025-12-31"))
    second_previous = events.index(("previous", "2026-01-01"))
    assert first_retire < second_previous
    assert events[-3:] == ["covered", "retire-nonbar", "publish"]
