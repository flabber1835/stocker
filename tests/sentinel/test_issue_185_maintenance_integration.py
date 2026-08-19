"""Integration seams for #185 historical SEP/ACTIONS maintenance.

These are deliberately small state-machine tests: they prove that correction
replay uses the same run identity as the candidate source change, that ACTIONS
acquisition is bounded to the exact authority window, and that the mutation
cursor moves only after publication returns.
"""
from __future__ import annotations

import datetime as dt
from contextlib import contextmanager
from types import SimpleNamespace

from sentinel.feed import maintenance, publication, renormalize, store


class _Run:
    def __init__(self, conn, kind, *, date_from=None, date_to=None, chunks_total=0):
        self.conn = conn
        self.progress = SimpleNamespace(
            run_id=f"{kind}-run", kind=kind, rows_written=0, rows_dropped=0,
            chunks_done=0, chunks_total=chunks_total)
        self.finished = []

    @contextmanager
    def chunk(self, label):
        yield self.progress
        self.progress.chunks_done += 1

    def finish(self, status="success", error=None):
        self.finished.append((status, error))


class _FrontierCursor:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, *_args, **_kwargs):
        return None

    def fetchone(self):
        return (dt.date(2020, 1, 2),)


class _FrontierConn:
    def cursor(self):
        return _FrontierCursor()


def _pub(run_id):
    return publication.Publication(
        version=12, previous_version=11, run_id=run_id,
        window_start="2020-01-01", window_end="2026-08-18", evidence={})


def test_actions_split_correction_replays_against_candidate_before_publication(
        monkeypatch):
    events = []
    action_params = []
    rows = [{
        "ticker": "AAA", "date": "2020-01-02", "action": "split",
        "name": None, "value": 2.0, "contraticker": None, "contraname": None,
    }]
    monkeypatch.setattr(store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(store, "IngestRun", _Run)
    monkeypatch.setattr(maintenance, "load_actions_cursor", lambda conn: None)

    def stable_rows(fetch, table, params):
        action_params.append(dict(params))
        return rows

    monkeypatch.setattr(maintenance, "_stable_rows", stable_rows)
    monkeypatch.setattr(
        maintenance, "_active_action_rows",
        lambda conn: {"old-row-id": dict(rows[0], value=1.5)})
    monkeypatch.setattr(
        maintenance, "_action_change_dates", lambda conn, current: ["2020-01-02"])
    monkeypatch.setattr(
        renormalize, "correction_windows",
        lambda dates: [("2019-12-31", "2020-01-03")])

    def write_actions(conn, current, *, run_id, window_start, window_end):
        events.append(("actions", run_id))
        return len(current)

    monkeypatch.setattr(store, "write_actions", write_actions)

    def replay(conn, *, fetch, run, dates, include_action_run_id, chunk_prefix):
        events.append(("replay", run.progress.run_id, include_action_run_id))
        assert include_action_run_id == run.progress.run_id
        return []

    monkeypatch.setattr(renormalize, "renormalize", replay)

    def publish(conn, *, run_id, **kwargs):
        events.append(("publish", run_id))
        return _pub(run_id)

    monkeypatch.setattr(publication, "publish", publish)
    monkeypatch.setattr(
        maintenance, "_write_cursor",
        lambda conn, **kwargs: events.append(("cursor", kwargs["publication_version"]))
        or maintenance.SourceCursor(
            kind=kwargs["kind"], processed_through=kwargs["through"],
            publication_version=kwargs["publication_version"]))

    maintenance.reconcile_actions_if_due(
        object(), fetch=object(), through="2026-08-18", force=True)

    assert action_params == [{
        "date.gte": maintenance.ACTIONS_FULL_WINDOW_START,
        "date.lte": "2026-08-18",
    }]
    assert events == [
        ("actions", "actions_reconcile-run"),
        ("replay", "actions_reconcile-run", "actions_reconcile-run"),
        ("publish", "actions_reconcile-run"),
        ("cursor", 12),
    ]


def test_sep_mutation_cursor_moves_only_after_bounded_replay_publication(monkeypatch):
    events = []
    cursor = maintenance.SourceCursor(
        kind="sharadar-sep-lastupdated/v1",
        processed_through=dt.date(2026, 8, 16), publication_version=10)
    rows = [{
        "ticker": "AAA", "date": "2020-01-02", "lastupdated": "2026-08-17",
        "open": 9.0, "close": 10.0, "closeunadj": 10.0, "volume": 1000,
    }]
    monkeypatch.setattr(store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(store, "IngestRun", _Run)
    monkeypatch.setattr(maintenance, "load_sep_cursor", lambda conn: cursor)
    monkeypatch.setattr(
        maintenance, "_stable_rows", lambda fetch, table, params: rows)
    monkeypatch.setattr(
        maintenance, "_validate_sep_mutation_rows",
        lambda conn, current, *, lo, hi, published_through: ["2020-01-02"])
    monkeypatch.setattr(
        renormalize, "correction_windows",
        lambda dates: [("2019-12-31", "2020-01-03")])

    def replay(conn, *, fetch, run, dates, chunk_prefix, **kwargs):
        events.append(("replay", run.progress.run_id))
        return []

    monkeypatch.setattr(renormalize, "renormalize", replay)

    def publish(conn, *, run_id, **kwargs):
        events.append(("publish", run_id))
        return _pub(run_id)

    monkeypatch.setattr(publication, "publish", publish)
    monkeypatch.setattr(
        maintenance, "_write_cursor",
        lambda conn, **kwargs: events.append(("cursor", kwargs["publication_version"]))
        or maintenance.SourceCursor(
            kind=kwargs["kind"], processed_through=kwargs["through"],
            publication_version=kwargs["publication_version"]))

    maintenance.reconcile_sep_mutations(
        _FrontierConn(), fetch=object(), through="2026-08-18")

    assert events == [
        ("replay", "sep_mutations-run"),
        ("publish", "sep_mutations-run"),
        ("cursor", 12),
    ]
