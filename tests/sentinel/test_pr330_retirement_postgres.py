from __future__ import annotations

import pytest

from tests.support.postgres import _EphemeralPostgres

from sentinel.feed import publication
from sentinel.feed import sep_negative_space_guarded as guarded
from sentinel.feed import store


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
    c = store.connect(pg.sync_dsn)
    with c.cursor() as cur:
        for table in (
            "sentinel_bar_split_repairs",
            "sentinel_anomaly_observation_events",
            "sentinel_action_generation_events",
            "sentinel_action_observations",
            "sentinel_action_generations",
            "sentinel_bars",
            "sentinel_actions",
            "sentinel_universe",
            "sentinel_publication_validation_receipts",
            "sentinel_publication_validation_policy",
            "sentinel_corpus_publications",
            "feed_ingest_runs",
            "sentinel_corpus_anomalies",
            "sentinel_ingest_rejections",
        ):
            cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    c.commit()
    store.require_feed_schema(c)
    yield c
    c.close()


def _published_bar(conn):
    run = store.IngestRun(conn, "daily")
    run_id = str(run.progress.run_id)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_bars (security_id,session,ticker,"
            " close_signal,close_unadjusted,volume,last_written_run_id)"
            " VALUES ('P:1','2026-04-02','AAA',10,10,1000,%s)",
            (run_id,))
        cur.execute(
            "INSERT INTO sentinel_bar_split_repairs"
            " (security_id,session,split_ratio,prior_split_ratio,last_written_run_id)"
            " VALUES ('P:1','2026-04-02',1,1,%s)",
            (run_id,))
    conn.commit()
    run.finish("success")
    publication.publish(conn, run_id=run_id)
    return run


def test_retirement_uses_governed_restatement_before_delete(conn):
    _published_bar(conn)

    with pytest.raises(Exception, match="published strategy evidence is append-only"):
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM sentinel_bars"
                " WHERE security_id='P:1' AND session='2026-04-02'")
    conn.rollback()

    retirement = store.IngestRun(
        conn, guarded.KIND,
        date_from="2026-04-02", date_to="2026-04-02", chunks_total=1)
    plan = {
        "interval": ["2026-04-02", "2026-04-02"],
        "keys": [{
            "security_id": "P:1",
            "session": "2026-04-02",
            "ticker": "AAA",
        }],
    }

    with store.corpus_write_lock(conn):
        result = guarded._retire_and_publish_authorized(
            conn, run=retirement, plan=plan)

    assert result.version == 2
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM sentinel_bars"
            " WHERE security_id='P:1' AND session='2026-04-02'")
        assert cur.fetchone()[0] == 0
        cur.execute(
            "SELECT COUNT(*) FROM sentinel_bar_split_repairs"
            " WHERE security_id='P:1' AND session='2026-04-02'")
        assert cur.fetchone()[0] == 0
        cur.execute(
            "SELECT status FROM feed_ingest_runs WHERE run_id=%s",
            (str(retirement.progress.run_id),))
        assert cur.fetchone()[0] == "success"
