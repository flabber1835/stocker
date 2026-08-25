"""Issue #251: a complete identity rebuild replaces current listing bounds."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from sentinel.feed import identity_rebuild as IR
from sentinel.feed import publication as P
from sentinel.feed import store as S
from sentinel.feed import universe as U
from sentinel.feed import universe_projection as UP
from tests.support.postgres import _EphemeralPostgres


@pytest.fixture(scope="module")
def pg():
    try:
        server = _EphemeralPostgres()
        server.start()
    except Exception as exc:                                  # noqa: BLE001
        pytest.skip(f"ephemeral Postgres unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def conn(pg):
    connection = S.connect(pg.sync_dsn)
    with connection.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        for (table,) in cur.fetchall():
            cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    connection.commit()
    S.migrate_schema(connection)
    yield connection
    connection.close()


def _ticker(*, first: str) -> dict:
    return {
        "table": "SEP",
        "ticker": "AAA",
        "permaticker": "P1",
        "category": "Domestic Common Stock",
        "sector": "Technology",
        "relatedtickers": "",
        "firstpricedate": first,
        "lastpricedate": "2026-08-21",
        "isdelisted": "N",
    }


def _bar(session: str):
    vendor = SimpleNamespace(
        security_id="P1", session=session, ticker="AAA",
        raw_close=10.0, raw_open=10.0, volume=1000.0,
        split_ratio=1.0, dividend_per_share=0.0)
    return SimpleNamespace(vendor=vendor, close_signal=10.0)


def _publish_stale_today_snapshot(conn):
    run = S.IngestRun(
        conn, "seed", date_from="2026-08-20", date_to="2026-08-21")
    run_id = run.progress.run_id
    U.write_universe(
        conn, [_ticker(first="2026-08-20")], "2026-08-24", run_id=run_id)
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO sentinel_bars"
            " (security_id,session,ticker,close_signal,close_unadjusted,"
            "  open_unadjusted,volume,split_ratio,dividend_per_share,"
            "  last_written_run_id)"
            " VALUES ('P1',%s,'AAA',10,10,10,1000,1,0,%s)",
            [("2026-08-20", run_id), ("2026-08-21", run_id)])
    conn.commit()
    run.finish("success")
    return P.publish(
        conn, run_id=run_id, window_start="2026-08-20",
        window_end="2026-08-21")


def _prepare_older_corrected_generation(conn):
    plan = IR.prepare(
        conn, date_from="2026-08-20", date_to="2026-08-21",
        observed_on="2026-08-24")
    # 2026-08-24 is occupied by the stale raw snapshot, so immutable evidence
    # must use an older unused date. That date must not weaken its generation
    # authority.
    assert plan.snapshot_date == "2026-08-23"
    run = S.IngestRun(
        conn, "seed", date_from=plan.market_start, date_to=plan.market_end)
    IR.record_plan(conn, run_id=run.progress.run_id, plan=plan)
    rows = IR.verify_candidate(
        conn, run_id=run.progress.run_id, plan=plan,
        rows=[_ticker(first="2026-08-21")])
    # The narrowed listing legitimately retires the 2026-08-20 bar and retains
    # the same surviving (permaticker,ticker) pair from 2026-08-21 onward.
    IR.write_bars_claiming(
        conn, [_bar("2026-08-21")], run_id=run.progress.run_id)
    return plan, run, rows


def _projection(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT first_price_date,last_price_date,snapshot_date"
            " FROM feed_universe_current"
            " WHERE permaticker='P1' AND ticker='AAA'")
        row = cur.fetchone()
    return tuple(str(value) for value in row)


def test_older_complete_rebuild_replaces_surviving_pair_bounds_and_reprojects(
        conn, pg):
    base = _publish_stale_today_snapshot(conn)
    with S.corpus_write_lock(conn):
        plan, run, rows = _prepare_older_corrected_generation(conn)
        replacement = IR.publish_completed_run(
            conn, run=run, rows=rows, plan=plan)

    assert replacement.previous_version == base.version
    assert _projection(conn) == (
        "2026-08-21", "2026-08-21", "2026-08-23")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT session FROM sentinel_bars WHERE security_id='P1'"
            " ORDER BY session")
        assert [str(row[0]) for row in cur.fetchall()] == ["2026-08-21"]

    # A fresh process sees the same corrected projection immediately.
    restarted = S.connect(pg.sync_dsn)
    try:
        assert _projection(restarted) == (
            "2026-08-21", "2026-08-21", "2026-08-23")
    finally:
        restarted.close()

    # Reprojection/migration must use publication-generation precedence rather
    # than allowing the pre-rebuild 2026-08-24 observation date to win again.
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE feed_universe_current"
            " SET first_price_date='2026-08-20',snapshot_date='2026-08-24'"
            " WHERE permaticker='P1' AND ticker='AAA'")
    conn.commit()
    S.migrate_schema(conn)
    assert _projection(conn) == (
        "2026-08-21", "2026-08-21", "2026-08-23")


def test_failure_after_projection_replacement_rolls_back_projection_and_bars(
        conn, monkeypatch):
    base = _publish_stale_today_snapshot(conn)
    with S.corpus_write_lock(conn):
        plan, run, rows = _prepare_older_corrected_generation(conn)
        monkeypatch.setattr(
            UP, "_assert_identity_projection",
            lambda *a, **k: (_ for _ in ()).throw(
                RuntimeError("forced post-replacement failure")))
        with pytest.raises(RuntimeError, match="post-replacement failure"):
            IR.publish_completed_run(conn, run=run, rows=rows, plan=plan)

    assert P.require_current(conn).version == base.version
    assert _projection(conn) == (
        "2026-08-20", "2026-08-21", "2026-08-24")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT session FROM sentinel_bars WHERE security_id='P1'"
            " ORDER BY session")
        assert [str(row[0]) for row in cur.fetchall()] == [
            "2026-08-20", "2026-08-21"]
        cur.execute(
            "SELECT status FROM feed_ingest_runs WHERE run_id=%s",
            (run.progress.run_id,))
        assert cur.fetchone()[0] == "failed"
