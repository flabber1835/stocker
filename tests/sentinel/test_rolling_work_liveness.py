"""Slow actual worker scans, without synthetic heartbeat calls in the test."""
from datetime import datetime, timedelta
from contextlib import contextmanager

import psycopg
import pytest

from sentinel import schema
from sentinel.feed import (rolling_go_inputs as inputs, rolling_jobs as jobs,
    rolling_store, rolling_work, rolling_source, action_history, operational_snapshot as op)
from tests.sentinel.test_rolling_go_inputs import issuer_source, operational_source  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401


@pytest.mark.parametrize("path,slow,fault", [
    ("go", "seal", None), ("go", "validation", None),
    ("go", "combined", None), ("scheduled", "combined", None),
    ("go", "seal", "deadline"), ("go", "seal", "fence"),
    ("go", "seal", "stall"),
    ("go", "publication", None), ("scheduled", "publication", None),
    ("go", "publication", "deadline"),
])
def test_real_work_renews_only_live_owned_job(conn, issuer_source, monkeypatch, path, slow, fault):
    schema.ensure_schema(conn)
    initial = conn.execute("SELECT clock_timestamp()").fetchone()[0]
    conn.commit()
    elapsed, active = [0], [None]

    class ClockCursor(psycopg.Cursor):
        def execute(self, query, params=None, **kwargs):
            if isinstance(query, str) and not query.lstrip().startswith(("CREATE", "ALTER", "DROP")):
                if (slow == "publication" and active[0] == "publication"
                        and query.startswith("SELECT security_id,ticker,close_signal")):
                    elapsed[0] += 3
                stamp = (initial + timedelta(seconds=elapsed[0])).isoformat()
                query = query.replace("clock_timestamp()", "'%s'::timestamptz" % stamp)
            return super().execute(query, params, **kwargs)
    conn.cursor_factory = ClockCursor
    monkeypatch.setattr(rolling_store, "BATCH_SIZE", 100)
    if slow == "publication":
        template = issuer_source["ACTIONS"][0]
        days = sorted({row["date"] for row in issuer_source["SEP"]})
        issuer_source["ACTIONS"][:1] = [dict(template, date=day) for day in days[1:]]

    @contextmanager
    def stage(name):
        active[0] = name
        try:
            yield
        finally:
            active[0] = None

    seal, validate, corroborate = rolling_store.seal, op.validate, rolling_source.SharadarSource.corroborate
    def sealing(*a, **kw):
        with stage("seal"):
            return seal(*a, **kw)
    def validating(*a, **kw):
        with stage("validation"):
            return validate(*a, **kw)
    def corroborating(*a, **kw):
        with stage("corroboration"):
            return corroborate(*a, **kw)
    append = action_history.append
    def publishing(*a, **kw):
        with stage("publication"):
            return append(*a, **kw)
    monkeypatch.setattr(rolling_store, "seal", sealing)
    monkeypatch.setattr(op, "validate", validating)
    monkeypatch.setattr(rolling_source.SharadarSource, "corroborate", corroborating)
    monkeypatch.setattr(action_history, "append", publishing)
    fold = rolling_store._fold
    damaged = [False]
    def slow_fold(*a):
        if active[0] == slow or (slow == "combined" and active[0] in {"seal", "validation"}):
            elapsed[0] += 1
            if fault and not damaged[0]:
                damaged[0] = True
                if fault == "stall":
                    elapsed[0] += 601
                elif fault == "fence":
                    conn.execute("UPDATE sentinel_snapshot_jobs SET fence=fence+1")
        return fold(*a)
    monkeypatch.setattr(rolling_store, "_fold", slow_fold)
    probe = rolling_source.snapshot_export.probe_snapshot
    def slow_probe(*a, **kw):
        if active[0] == "corroboration" and slow == "combined":
            elapsed[0] += 20
        return probe(*a, **kw)
    monkeypatch.setattr(rolling_source.snapshot_export, "probe_snapshot", slow_probe)

    budget = 1000 if fault == "deadline" else 7200
    if path == "go":
        run = lambda: inputs.prepare(conn, target_session="2026-09-14", budget_seconds=budget)
    else:
        # The scheduled route invokes _prepare with wait=False through the same publisher.
        run = lambda: inputs._prepare(conn, target_session="2026-09-14", budget_seconds=budget)
    if fault:
        with pytest.raises(jobs.JobDeadlineExceeded if fault == "deadline" else jobs.JobRefused):
            run()
        assert conn.execute("SELECT COUNT(*) FROM sentinel_corpus_publications").fetchone()[0] == 0
    else:
        result = run()
        assert result["status"] == "PUBLISHED" and elapsed[0] > 600
        state = jobs.status(conn, result["job_id"])
        assert datetime.fromisoformat(state["deadline"]) == initial + timedelta(seconds=budget)
        assert state["state"] == "PUBLISHED"
    # No scoped writer can escape into panel, GO read-only or broker input readers.
    conn.rollback()
    conn.execute("SET TRANSACTION READ ONLY")
    rolling_work.checkpoint()
    conn.rollback()


def test_nested_work_scope_restores_previous_owner_and_cleans_up():
    seen = []
    with rolling_work.renewing(lambda: seen.append("outer")):
        with pytest.raises(RuntimeError):
            with rolling_work.renewing(lambda: seen.append("inner")):
                raise RuntimeError("interrupted")
        rolling_work.checkpoint()
    rolling_work.checkpoint()
    assert seen == ["outer", "inner", "outer", "outer"]
