from pathlib import Path

schema = Path("sentinel/feed/schema.py")
text = schema.read_text(encoding="utf-8")
marker = '''    # ------------------------------------------------------------------\n    # THE CHUNK SORT, moved out of the interpreter. See sentinel/feed/staging.py.\n'''
if text.count(marker) != 1:
    raise SystemExit(f"schema marker count is {text.count(marker)}, expected 1")
block = r'''    # ------------------------------------------------------------------
    # PUBLISHED STRATEGY EVIDENCE IS IMMUTABLE UNDER ITS PUBLISHED IDENTITY.
    #
    # A legitimate restatement must move the row to a distinct durable ingest
    # run that has not published yet.  That makes the candidate invisible to
    # readers until validation publishes a NEW data_version.  Direct SQL that
    # changes bytes while leaving NULL/published ownership in place is exactly
    # the same-version corruption #122 exists to prevent.
    # ------------------------------------------------------------------
    """CREATE OR REPLACE FUNCTION sentinel_guard_strategy_row_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
          old_protected BOOLEAN;
          new_status TEXT;
        BEGIN
          old_protected := OLD.last_written_run_id IS NULL OR EXISTS (
            SELECT 1 FROM sentinel_corpus_publications p
             WHERE p.run_id=OLD.last_written_run_id);
          IF NOT old_protected THEN
            IF TG_OP='DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
          END IF;
          IF TG_OP='DELETE' THEN
            RAISE EXCEPTION USING ERRCODE='23000', MESSAGE=format(
              '%s: legacy/published strategy evidence is append-only; DELETE refused',
              TG_TABLE_NAME);
          END IF;
          IF NEW.last_written_run_id IS NULL
             OR NEW.last_written_run_id IS NOT DISTINCT FROM OLD.last_written_run_id THEN
            RAISE EXCEPTION USING ERRCODE='23000', MESSAGE=format(
              '%s: strategy evidence cannot change under the same published/legacy identity',
              TG_TABLE_NAME);
          END IF;
          IF EXISTS (SELECT 1 FROM sentinel_corpus_publications p
                      WHERE p.run_id=NEW.last_written_run_id) THEN
            RAISE EXCEPTION USING ERRCODE='23000', MESSAGE=format(
              '%s: restatement target run is already published', TG_TABLE_NAME);
          END IF;
          SELECT r.status INTO new_status FROM feed_ingest_runs r
           WHERE r.run_id=NEW.last_written_run_id;
          IF new_status IS NULL OR new_status='failed' THEN
            RAISE EXCEPTION USING ERRCODE='23000', MESSAGE=format(
              '%s: restatement requires a durable non-failed unpublished ingest run',
              TG_TABLE_NAME);
          END IF;
          RETURN NEW;
        END $$""",
    """CREATE OR REPLACE FUNCTION sentinel_refuse_append_only_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION USING ERRCODE='23000', MESSAGE=format(
            '%s is append-only; %s refused', TG_TABLE_NAME, TG_OP);
        END $$""",
'''
for table in (
    "sentinel_bars",
    "sentinel_spy_total_return",
    "sentinel_universe",
    "sentinel_actions",
    "sentinel_bar_split_repairs",
    "sentinel_action_generations",
    "sentinel_action_observations",
    "sentinel_corpus_anomalies",
    "sentinel_ingest_rejections",
):
    block += f'''    """DROP TRIGGER IF EXISTS sentinel_guard_strategy_row_mutation ON {table}""",\n'''
    block += f'''    """CREATE TRIGGER sentinel_guard_strategy_row_mutation\n        BEFORE UPDATE OR DELETE ON {table}\n        FOR EACH ROW EXECUTE FUNCTION sentinel_guard_strategy_row_mutation()""",\n'''
for table in (
    "sentinel_corpus_publications",
    "sentinel_action_generation_events",
    "sentinel_anomaly_observation_events",
):
    block += f'''    """DROP TRIGGER IF EXISTS sentinel_refuse_append_only_mutation ON {table}""",\n'''
    block += f'''    """CREATE TRIGGER sentinel_refuse_append_only_mutation\n        BEFORE UPDATE OR DELETE ON {table}\n        FOR EACH ROW EXECUTE FUNCTION sentinel_refuse_append_only_mutation()""",\n'''
block += "\n"
schema.write_text(text.replace(marker, block + marker, 1), encoding="utf-8")

Path("tests/sentinel/test_issue209_published_immutability.py").write_text(r'''from uuid import uuid4

import pytest

from sentinel.feed import store as feed_store
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
    feed_store.ensure_schema(connection)
    yield connection
    connection.close()


def _run(conn, run_id, status="success"):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO feed_ingest_runs (run_id,kind,status) VALUES (%s,'test',%s)",
            (run_id, status))
    conn.commit()


def _publish(conn, run_id):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_corpus_publications (run_id,evidence) "
            "VALUES (%s,'{}'::jsonb)", (run_id,))
    conn.commit()


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


def test_restatement_requires_new_unpublished_run_and_legacy_is_protected(conn):
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
    _refused(conn,
             "UPDATE sentinel_bars SET close_unadjusted=91 WHERE security_id='SEC-L'")

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
''', encoding="utf-8")
