"""Ingest progress must be readable WHILE the ingest runs, and after it dies.

This is the correction to bt-engine's `/wealth-core/progress`, which holds its
snapshot in memory. That cost real time this month: after a restart the endpoint
returned empty while the run row still said `running`, so a dead job and a
healthy one that had not yet published were indistinguishable — and a three-hour
rehearsal was waited on for half an hour with nothing behind it.

Every test here uses a SECOND connection to read what the writer published. A
single-connection test would pass on an implementation that never commits, which
is precisely the bug.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import _EphemeralPostgres  # noqa: E402

from sentinel.feed import store as S  # noqa: E402
from sentinel.feed.schema import RESTART_ABORT_MARKER  # noqa: E402
from stock_strategy_shared.wealth_core.feed import VendorBar  # noqa: E402


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
        for t in ("sentinel_action_generation_events",
                  "sentinel_action_observations", "sentinel_action_generations",
                  "sentinel_bars", "sentinel_actions", "sentinel_universe",
                  "feed_ingest_runs"):
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    c.commit()
    S.ensure_schema(c)
    yield c
    c.close()


def bar(sid, session, **kw):
    d = dict(ticker=sid, raw_close=100.0, raw_open=99.0, volume=1e6,
             split_ratio=1.0, dividend_per_share=0.0)
    d.update(kw)
    return VendorBar(session=session, security_id=sid, **d)


class TestProgressIsVisibleToOtherProcesses:
    def test_a_watcher_sees_progress_MID_RUN(self, conn, pg):
        """The whole requirement: a long seed must be trackable while it runs."""
        run = S.IngestRun(conn, "seed", chunks_total=3)
        watcher = S.connect(pg.sync_dsn)
        try:
            with run.chunk("1998"):
                seen = S.run_status(watcher)[0]
                assert seen["status"] == "running"
                assert seen["current_chunk"] == "1998"
                assert seen["chunks_done"] == 0      # in flight, not finished
            after = S.run_status(watcher)[0]
            assert after["chunks_done"] == 1
            assert after["chunks_total"] == 3
        finally:
            watcher.close()

    def test_counters_survive_the_writer_dying(self, conn, pg):
        """`how far did it get` must be answerable AFTER the process is gone."""
        run = S.IngestRun(conn, "seed", chunks_total=10)
        with run.chunk("1998"):
            run.progress.rows_written += 4242
        conn.close()                                  # the writer dies here

        reader = S.connect(pg.sync_dsn)
        try:
            row = S.run_status(reader)[0]
            assert row["rows_written"] == 4242
            assert row["chunks_done"] == 1
            assert row["status"] == "running"         # nothing marked it yet
            assert S.reclaim_orphans(reader) == 1
            row = S.run_status(reader)[0]
            assert row["status"] == "failed"
            assert RESTART_ABORT_MARKER in row["error_message"]
            assert row["rows_written"] == 4242, "reclaim must not discard counters"
        finally:
            reader.close()

    def test_a_failing_chunk_RECORDS_before_it_raises(self, conn, pg):
        run = S.IngestRun(conn, "seed", chunks_total=2)
        with pytest.raises(ValueError):
            with run.chunk("2001"):
                raise ValueError("vendor 500")
        watcher = S.connect(pg.sync_dsn)
        try:
            row = S.run_status(watcher)[0]
            assert row["status"] == "failed"
            assert "2001" in row["error_message"]
            assert "vendor 500" in row["error_message"]
        finally:
            watcher.close()


class TestIdempotentUpserts:
    def test_re_running_a_chunk_does_not_duplicate(self, conn):
        bars = [bar("SEC1", "2024-01-02"), bar("SEC2", "2024-01-02")]
        assert S.write_bars(conn, bars) == 2
        S.write_bars(conn, bars)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM sentinel_bars")
            assert cur.fetchone()[0] == 2

    def test_a_re_fetch_CORRECTS_a_restated_bar(self, conn):
        """Vendors restate. An insert-only loader would keep the stale row."""
        S.write_bars(conn, [bar("SEC1", "2024-01-02", raw_close=100.0)])
        S.write_bars(conn, [bar("SEC1", "2024-01-02", raw_close=101.5)])
        with conn.cursor() as cur:
            cur.execute("SELECT close_unadjusted FROM sentinel_bars")
            assert cur.fetchone()[0] == 101.5

    def test_the_as_traded_price_cannot_be_NULL(self, conn):
        """A schema property, not a convention: a bar with no as-traded close
        cannot be marked or executed, and a direct INSERT must not sneak one in."""
        with pytest.raises(Exception):
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO sentinel_bars (security_id, session, ticker,"
                    " close_unadjusted) VALUES ('X','2024-01-02','X', NULL)")
        conn.rollback()

    def test_latest_session_drives_the_incremental_resume(self, conn):
        assert S.latest_session(conn) is None
        S.write_bars(conn, [bar("SEC1", "2024-01-02"), bar("SEC1", "2024-03-05")])
        assert S.latest_session(conn) == "2024-03-05"
