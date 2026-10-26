"""Real PostgreSQL clock predicates and large-checkpoint MVCC preservation."""
import importlib
import os
from pathlib import Path
import re
import sys

import pytest

ROOT=Path(os.environ.get('SENTINEL_REPO_ROOT') or Path(__file__).resolve().parents[2])
sys.path.insert(0,str(ROOT/'scripts'))
checks=importlib.import_module('sentinel_local_delivery.checks')
from tests.sentinel.test_rolling_snapshot_publisher import conn,pg


def cycle(conn):
    conn.execute("""CREATE TEMP TABLE handoff_cycle AS SELECT
        'SUCCEEDED'::text AS state,
        (clock_timestamp() AT TIME ZONE 'America/New_York')::date AS effective_session,
        NULL::text AS failure_code,NULL::text AS failure_detail,
        clock_timestamp()-interval '5 minutes' AS execute_at,
        clock_timestamp()-interval '1 minute' AS completed_at,
        clock_timestamp()+interval '1 hour' AS execution_close_at,
        false AS historical_state_only""")


def admitted(conn):
    candidate,ready=checks.handoff_filters('POST_TRADE')
    return conn.execute('SELECT ('+candidate+') AND NOT s.historical_state_only AND ('+ready+
        ') FROM handoff_cycle s').fetchone()[0]


@pytest.mark.parametrize('change',[
    "state='RECONCILING'","effective_session=effective_session-1",
    "completed_at=NULL","completed_at=clock_timestamp()+interval '1 minute'",
    "execute_at=clock_timestamp()","execution_close_at=clock_timestamp()+interval '14 minutes'",
    "failure_code='UNKNOWN'","failure_detail='ambiguous outcome'","historical_state_only=true",
])
def test_posttrade_uses_actual_database_clock_and_refuses_unsafe_cycles(conn,change):
    cycle(conn);assert admitted(conn) is True
    conn.execute('UPDATE handoff_cycle SET '+change)
    assert admitted(conn) is not True


def checkpoint_query():
    return re.search(r"'book_cursors_md5',\((SELECT.*?)\),\s*'push_subscriptions'",
        checks.SNAPSHOT_SQL,re.S).group(1)


def assert_checkpoint_update_detected(conn,query):
    from sentinel.schema import ensure_schema
    ensure_schema(conn)
    conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) "
        "VALUES ('rolling-daily-checkpoint:v1','2031-04-21',jsonb_build_object('large',repeat('checkpoint',1000000)))")
    conn.commit();before=conn.execute(query).fetchone()[0];conn.rollback()
    conn.execute("UPDATE sentinel_processed_sessions SET state=state WHERE cursor_name='rolling-daily-checkpoint:v1'")
    conn.commit();changed=conn.execute(query).fetchone()[0];conn.rollback()
    assert before!=changed,'checkpoint update reused its MVCC witness'
    conn.execute("DELETE FROM sentinel_processed_sessions WHERE cursor_name='rolling-daily-checkpoint:v1'")
    conn.commit();assert conn.execute(query).fetchone()[0]!=changed


def test_large_checkpoint_update_and_delete_change_the_preservation_witness(conn):
    query=checkpoint_query()
    assert 'to_jsonb(x)' not in query and 'xmin' in query and 'ctid' in query
    assert_checkpoint_update_detected(conn,query)


def test_removing_mvcc_fields_has_a_real_postgres_falsifier(conn):
    query=checkpoint_query().replace('x.xmin::text,x.ctid::text','NULL,NULL')
    with pytest.raises(AssertionError,match='MVCC witness'):
        assert_checkpoint_update_detected(conn,query)
