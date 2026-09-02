from uuid import uuid4

import pytest

from sentinel.feed import publication, store as feed_store
from sentinel.identity import require_feed_producer_identity
from tests.support.postgres import _EphemeralPostgres, drop_public_tables


@pytest.fixture(scope="module")
def pg():
    server = _EphemeralPostgres()
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def conn(pg):
    connection = feed_store.connect(pg.sync_dsn)
    drop_public_tables(connection)
    feed_store.require_feed_schema(connection)
    yield connection
    connection.close()


def _run(conn, run_id, status="success"):
    producer = require_feed_producer_identity()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO feed_ingest_runs"
            " (run_id,kind,status,source_git_commit,runtime_image_digest)"
            " VALUES (%s,'test',%s,%s,%s)",
            (run_id, status, producer["git_commit"],
             producer["runtime_image_digest"]))
    conn.commit()


def _publish(conn, run_id):
    publication.publish(conn, run_id=run_id)


def _refused(conn, sql, params=()):
    with pytest.raises(Exception, match="published|append-only|same published"):
        with conn.cursor() as cur:
            cur.execute(sql, params)
    conn.rollback()


def test_published_strategy_families_refuse_in_place_mutation(conn):
    published = uuid4()
    _run(conn, published)
    _publish(conn, published)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_bars "
            "(security_id,session,ticker,close_unadjusted,last_written_run_id) "
            "VALUES ('SEC-A','2026-08-20','AAA',100,%s)", (published,))
        cur.execute(
            "INSERT INTO sentinel_spy_total_return "
            "(session,closeadj,last_written_run_id) VALUES ('2026-08-20',500,%s)",
            (published,))
        cur.execute(
            "INSERT INTO sentinel_universe "
            "(permaticker,ticker,snapshot_date,category,last_written_run_id) "
            "VALUES ('SEC-A','AAA','2026-08-20','Domestic Common Stock',%s)",
            (published,))
        cur.execute(
            "INSERT INTO sentinel_actions "
            "(ticker,session,action,value,last_written_run_id) "
            "VALUES ('AAA','2026-08-20','split',2,%s)", (published,))
        cur.execute(
            "INSERT INTO sentinel_bar_split_repairs "
            "(security_id,session,split_ratio,prior_split_ratio,last_written_run_id) "
            "VALUES ('SEC-A','2026-08-20',2,1,%s)", (published,))
        cur.execute(
            "INSERT INTO sentinel_action_generations "
            "(last_written_run_id,window_start,window_end,source_rows) "
            "VALUES (%s,'2026-08-20','2026-08-20',1)", (published,))
        cur.execute(
            "INSERT INTO sentinel_action_observations "
            "(source_row_id,source_payload,ticker,session,action,value,disposition,last_written_run_id) "
            "VALUES ('row-1','{}'::jsonb,'AAA','2026-08-20','split',2,'PRESENT',%s)",
            (published,))
        cur.execute(
            "INSERT INTO sentinel_corpus_anomalies "
            "(kind,ticker,session,detail,last_written_run_id) "
            "VALUES ('TEST','AAA','2026-08-20','original',%s)", (published,))
        cur.execute(
            "INSERT INTO sentinel_ingest_rejections "
            "(ticker,session,reason,close_unadjusted,last_written_run_id) "
            "VALUES ('ZZZ','2026-08-20','TEST',10,%s)", (published,))
    conn.commit()

    cases = [
        ("UPDATE sentinel_bars SET close_unadjusted=101 WHERE security_id='SEC-A'", ()),
        ("UPDATE sentinel_spy_total_return SET closeadj=501 WHERE session='2026-08-20'", ()),
        ("UPDATE sentinel_universe SET category='Changed' WHERE permaticker='SEC-A'", ()),
        ("UPDATE sentinel_actions SET value=3 WHERE ticker='AAA'", ()),
        ("UPDATE sentinel_bar_split_repairs SET split_ratio=3 WHERE security_id='SEC-A'", ()),
        ("UPDATE sentinel_action_generations SET source_rows=2 WHERE last_written_run_id=%s", (published,)),
        ("UPDATE sentinel_action_observations SET value=3 WHERE source_row_id='row-1'", ()),
        ("UPDATE sentinel_corpus_anomalies SET detail='changed' WHERE ticker='AAA'", ()),
        ("UPDATE sentinel_ingest_rejections SET close_unadjusted=11 WHERE ticker='ZZZ'", ()),
    ]
    for sql, params in cases:
        _refused(conn, sql, params)

    _refused(conn, "DELETE FROM sentinel_bars WHERE security_id='SEC-A'")
    _refused(conn, "UPDATE sentinel_corpus_publications SET evidence='{\"x\":1}'::jsonb")
    _refused(conn, "DELETE FROM sentinel_corpus_publications")


def test_restatement_requires_new_unpublished_run_and_legacy_stays_mutable(conn):
    published = uuid4()
    candidate = uuid4()
    _run(conn, published)
    _publish(conn, published)
    _run(conn, candidate, status="running")
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_bars "
            "(security_id,session,ticker,close_unadjusted,last_written_run_id) "
            "VALUES ('SEC-P','2026-08-20','PPP',100,%s)", (published,))
        cur.execute(
            "INSERT INTO sentinel_bars "
            "(security_id,session,ticker,close_unadjusted,last_written_run_id) "
            "VALUES ('SEC-L','2026-08-19','LLL',90,NULL)")
    conn.commit()

    _refused(conn,
             "UPDATE sentinel_bars SET close_unadjusted=101 WHERE security_id='SEC-P'")
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_bars SET close_unadjusted=91 WHERE security_id='SEC-L'")
    conn.commit()

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_bars SET close_unadjusted=101,last_written_run_id=%s "
            "WHERE security_id='SEC-P'", (candidate,))
        cur.execute(
            "UPDATE sentinel_bars SET close_unadjusted=91,last_written_run_id=%s "
            "WHERE security_id='SEC-L'", (candidate,))
    conn.commit()

    with conn.cursor() as cur:
        cur.execute(
            "SELECT security_id,last_written_run_id FROM sentinel_bars "
            "WHERE security_id IN ('SEC-P','SEC-L') ORDER BY security_id")
        rows = cur.fetchall()
    assert rows == [('SEC-L', candidate), ('SEC-P', candidate)]
