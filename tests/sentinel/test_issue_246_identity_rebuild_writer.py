"""The #246 full-history writer claims unchanged published bar keys in one pass."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from sentinel.feed import identity_rebuild_writer as W
from sentinel.feed import publication as P
from sentinel.feed import store as S
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


def _bar():
    vendor = SimpleNamespace(
        security_id="P1", session="2026-08-21", ticker="KEEP",
        raw_close=10.0, raw_open=9.9, volume=1000.0,
        split_ratio=1.0, dividend_per_share=0.0)
    return SimpleNamespace(vendor=vendor, close_signal=10.0)


def test_writer_claims_an_economically_unchanged_published_row(conn):
    published = S.IngestRun(conn, "seed")
    old_run = published.progress.run_id
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_bars"
            " (security_id,session,ticker,close_signal,close_unadjusted,"
            "  open_unadjusted,volume,split_ratio,dividend_per_share,"
            "  last_written_run_id)"
            " VALUES ('P1','2026-08-21','KEEP',10,10,9.9,1000,1,0,%s)",
            (old_run,))
    conn.commit()
    published.finish("success")
    P.publish(conn, run_id=old_run)

    replacement = S.IngestRun(conn, "seed")
    with S.corpus_write_lock(conn):
        assert W.write_bars_claiming(
            conn, [_bar()], run_id=replacement.progress.run_id,
            batch_size=1) == 1

    with conn.cursor() as cur:
        cur.execute(
            "SELECT ticker,close_unadjusted,last_written_run_id::text"
            " FROM sentinel_bars WHERE security_id='P1'"
            "   AND session='2026-08-21'")
        ticker, close, owner = cur.fetchone()
    assert ticker == "KEEP" and close == 10.0
    assert owner == replacement.progress.run_id
