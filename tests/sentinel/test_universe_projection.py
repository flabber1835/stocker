"""Regression tests for the bounded TICKERS current-state projection."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from sentinel.core import loader as L  # noqa: E402
from sentinel.feed import publication as P  # noqa: E402
from sentinel.feed import store as S  # noqa: E402
from sentinel.feed import universe as U  # noqa: E402
from tests.support.postgres import _EphemeralPostgres  # noqa: E402


@pytest.fixture(scope="module")
def pg():
    try:
        server = _EphemeralPostgres()
        server.start()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ephemeral Postgres unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def conn(pg):
    c = S.connect(pg.sync_dsn)
    with c.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        for (table,) in cur.fetchall():
            cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    c.commit()
    S.migrate_schema(c)
    yield c
    c.close()


def _publish_snapshot(conn, snapshot_date: str, row: dict) -> None:
    ingest = S.IngestRun(conn, "daily")
    run_id = ingest.progress.run_id
    U.write_universe(conn, [row], snapshot_date, run_id=run_id)
    ingest.finish("success")
    P.publish(conn, run_id=run_id)


def test_meta_uses_each_fields_own_observation_date_across_ticker_pairs(conn):
    """A newer blank ticker-pair row must not make an older label look newest.

    The raw historical implementation ordered each non-null field by the row's
    snapshot date across the whole permaticker. The projection stores one row per
    ticker pair, so it must carry and consult per-field observation dates to keep
    exactly that behavior.
    """
    _publish_snapshot(
        conn, "2024-01-01",
        {"permaticker": "P1", "ticker": "OLD", "category": "older-category",
         "relatedtickers": "OLDLINK"},
    )
    _publish_snapshot(
        conn, "2024-01-02",
        {"permaticker": "P1", "ticker": "NEW", "category": "newer-category",
         "relatedtickers": "NEWLINK"},
    )
    # OLD is observed again later, but the vendor leaves its optional labels
    # blank. That makes OLD the newest ticker while NEW still owns the newest
    # non-null category and related-ticker observations.
    _publish_snapshot(
        conn, "2024-01-03",
        {"permaticker": "P1", "ticker": "OLD", "category": None,
         "relatedtickers": None},
    )

    meta = L.load_meta(conn)["P1"]
    assert meta.ticker == "OLD"
    assert meta.category == "newer-category"
    assert meta.related_tickers == ("NEWLINK",)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT ticker,category,category_snapshot_date,related_tickers,"
            " related_tickers_snapshot_date,snapshot_date"
            " FROM feed_universe_current WHERE permaticker='P1'"
            " ORDER BY ticker")
        rows = cur.fetchall()
    assert len(rows) == 2
    old, new = rows
    assert old[0] == "NEW" and str(old[2]) == "2024-01-02"
    assert new[0] == "OLD" and str(new[5]) == "2024-01-03"
