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

import pytest

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
        maintenance, "_retained_market_bounds",
        lambda conn: ("2019-01-02", "2026-08-18"))
    monkeypatch.setattr(
        maintenance, "_failed_action_reconcile_bar_footprint",
        lambda conn, **kwargs: ([], False))
    monkeypatch.setattr(
        maintenance, "_semantic_upgrade_replay_dates",
        lambda conn, **kwargs: [])
    monkeypatch.setattr(
        renormalize, "correction_windows",
        lambda dates, **kwargs: [("2019-12-31", "2020-01-03")])
    monkeypatch.setattr(
        "sentinel.feed.recovery.retire_failed_action_reconcile_bars_outside_market",
        lambda conn, **kwargs: 0)

    def write_actions(conn, current, *, run_id, window_start, window_end):
        events.append(("actions", run_id))
        return len(current)

    monkeypatch.setattr(store, "write_actions", write_actions)

    def replay(conn, *, fetch, run, dates, include_action_run_id, chunk_prefix,
               market_start, market_end, retire_failed_action_candidates):
        events.append(("replay", run.progress.run_id, include_action_run_id))
        assert include_action_run_id == run.progress.run_id
        assert (market_start, market_end) == ("2019-01-02", "2026-08-18")
        assert retire_failed_action_candidates is True
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


def test_full_actions_history_does_not_expand_a_short_price_seed(monkeypatch):
    events = []
    old = {
        "ticker": "OLD", "date": "1998-01-02", "action": "split",
        "name": None, "value": 2.0, "contraticker": None,
        "contraname": None,
    }
    recent = {
        "ticker": "NEW", "date": "2025-08-18", "action": "dividend",
        "name": None, "value": 0.5, "contraticker": None,
        "contraname": None,
    }
    monkeypatch.setattr(store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(store, "IngestRun", _Run)
    monkeypatch.setattr(maintenance, "load_actions_cursor", lambda conn: None)
    monkeypatch.setattr(
        maintenance, "_stable_rows",
        lambda fetch, table, params: [old, recent])
    monkeypatch.setattr(
        maintenance, "_active_action_rows",
        lambda conn: {"recent": recent})
    monkeypatch.setattr(
        maintenance, "_action_change_dates",
        lambda conn, rows: ["1998-01-02"])
    monkeypatch.setattr(
        maintenance, "_retained_market_bounds",
        lambda conn: ("2025-07-01", "2026-08-21"))
    monkeypatch.setattr(
        maintenance, "_failed_action_reconcile_bar_footprint",
        lambda conn, **kwargs: ([], False))
    monkeypatch.setattr(
        maintenance, "_semantic_upgrade_replay_dates",
        lambda conn, **kwargs: [])
    monkeypatch.setattr(
        "sentinel.feed.recovery.retire_failed_action_reconcile_bars_outside_market",
        lambda conn, **kwargs: 0)
    monkeypatch.setattr(
        store, "write_actions", lambda *args, **kwargs: 2)
    monkeypatch.setattr(
        renormalize, "renormalize",
        lambda *args, **kwargs: pytest.fail(
            "an action outside the retained market must not fetch SEP"))
    monkeypatch.setattr(
        publication, "publish",
        lambda conn, *, run_id, **kwargs: events.append(kwargs["evidence"])
        or _pub(run_id))
    monkeypatch.setattr(
        maintenance, "_write_cursor",
        lambda conn, **kwargs: maintenance.SourceCursor(
            kind=kwargs["kind"], processed_through=kwargs["through"],
            publication_version=kwargs["publication_version"]))

    maintenance.reconcile_actions_if_due(
        object(), fetch=object(), through="2026-08-21", force=True)

    evidence = events[0]
    assert evidence["changed_action_dates"] == 1
    assert evidence["affected_bar_dates"] == 1
    assert evidence["retained_market_window"] == ["2025-07-01", "2026-08-21"]
    assert evidence["replay_windows"] == []


def test_semantic_cursor_upgrade_replays_old_blockers_with_unchanged_source(
        monkeypatch):
    events = []
    row = {
        "ticker": "AAA", "date": "2026-08-14", "action": "split",
        "name": None, "value": 0.1, "contraticker": None,
        "contraname": None,
    }
    identity = "source-row"
    monkeypatch.setattr(store, "_assert_corpus_locked", lambda conn: None)
    monkeypatch.setattr(store, "IngestRun", _Run)
    monkeypatch.setattr(maintenance, "load_actions_cursor", lambda conn: None)
    monkeypatch.setattr(
        maintenance, "_stable_rows", lambda fetch, table, params: [row])
    monkeypatch.setattr(
        maintenance.action_source, "distinct_rows",
        lambda rows: [(identity, {}, row)])
    monkeypatch.setattr(
        maintenance, "_active_action_rows", lambda conn: {identity: {}})
    monkeypatch.setattr(
        maintenance, "_action_change_dates", lambda conn, rows: [])
    monkeypatch.setattr(
        maintenance, "_retained_market_bounds",
        lambda conn: ("2025-07-01", "2026-08-21"))
    monkeypatch.setattr(
        maintenance, "_failed_action_reconcile_bar_footprint",
        lambda conn, **kwargs: ([], False))
    monkeypatch.setattr(
        maintenance, "_semantic_upgrade_replay_dates",
        lambda conn, **kwargs: ["2026-08-14"])
    monkeypatch.setattr(
        renormalize, "correction_windows",
        lambda dates, **kwargs: [("2026-08-12", "2026-08-17")])
    monkeypatch.setattr(
        "sentinel.feed.recovery.retire_failed_action_reconcile_bars_outside_market",
        lambda conn, **kwargs: 0)
    monkeypatch.setattr(store, "write_actions", lambda *args, **kwargs: 1)

    def replay(conn, *, dates, **kwargs):
        events.append(("replay", list(dates)))
        return []

    monkeypatch.setattr(renormalize, "renormalize", replay)
    monkeypatch.setattr(
        publication, "publish",
        lambda conn, *, run_id, **kwargs: events.append(
            ("publish", kwargs["evidence"]["semantic_upgrade_dates"]))
        or _pub(run_id))
    monkeypatch.setattr(
        maintenance, "_write_cursor",
        lambda conn, **kwargs: maintenance.SourceCursor(
            kind=kwargs["kind"], processed_through=kwargs["through"],
            publication_version=kwargs["publication_version"]))

    maintenance.reconcile_actions_if_due(
        object(), fetch=object(), through="2026-08-21", force=True)

    assert events == [
        ("replay", ["2026-08-14"]),
        ("publish", 1),
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
        lambda conn, current, *, lo, hi, published_from, published_through:
            ["2020-01-02"])
    monkeypatch.setattr(
        maintenance, "_retained_market_bounds",
        lambda conn: ("2019-01-02", "2026-08-18"))
    monkeypatch.setattr(
        renormalize, "correction_windows",
        lambda dates, **kwargs: [("2019-12-31", "2020-01-03")])

    def replay(conn, *, fetch, run, dates, chunk_prefix, **kwargs):
        events.append(("replay", run.progress.run_id))
        assert kwargs == {
            "market_start": "2019-01-02", "market_end": "2026-08-18"}
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
