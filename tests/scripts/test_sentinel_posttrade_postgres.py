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
    selected=re.search(r"'book_cursors_md5',\((SELECT.*?)\),\s*'issuer_evidence'",
        checks.SNAPSHOT_SQL,re.S)
    assert selected is not None,'current checkpoint MVCC projection was not found'
    return selected.group(1)


def test_checkpoint_projection_stops_before_the_separate_issuer_preservation_domain():
    query=checkpoint_query()
    assert 'to_jsonb(x)' not in query and 'xmin' in query and 'ctid' in query
    assert "'issuer_evidence'" not in query and checks._ISSUER_EVIDENCE_FILTER not in query
    assert query.count('FROM sentinel_processed_sessions x')==1


def test_obsolete_projection_boundary_has_a_falsifier(monkeypatch):
    obsolete=re.search(r"'book_cursors_md5',\((SELECT.*?)\),\s*'push_subscriptions'",
        checks.SNAPSHOT_SQL,re.S).group(1)
    monkeypatch.setattr(sys.modules[__name__],'checkpoint_query',lambda:obsolete)
    with pytest.raises(AssertionError):
        test_checkpoint_projection_stops_before_the_separate_issuer_preservation_domain()


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


def successor_tables(conn):
    """Minimal real tables for the exact native candidate/join/clock predicate."""
    conn.execute("""CREATE TEMP TABLE sentinel_automation_control AS SELECT 1::int AS id,
        99::bigint AS generation,'current-config'::text AS config_sha256,
        'owned-deployment'::text AS deployment_id,'alpaca'::text AS broker,
        'PAPER-Z'::text AS broker_account_id,7::bigint AS takeover_epoch,
        'CONTROLLER'::text AS rollout_mode,12::bigint AS rollout_version,
        'new-certificate'::text AS certificate_sha256""")
    conn.execute("""CREATE TEMP TABLE sentinel_automation_cycles AS SELECT
        'SUCCEEDED'::text AS state,(clock_timestamp() AT TIME ZONE 'America/New_York')::date AS effective_session,
        (clock_timestamp() AT TIME ZONE 'America/New_York')::date-1 AS decision_session,
        NULL::text AS failure_code,NULL::text AS failure_detail,
        clock_timestamp()-interval '5 minutes' AS execute_at,
        clock_timestamp()-interval '1 minute' AS completed_at,
        clock_timestamp()+interval '1 hour' AS execution_close_at,false AS historical_state_only,
        98::bigint AS control_generation,'old-config'::text AS config_sha256,
        'owned-deployment'::text AS deployment_id,'alpaca'::text AS broker,
        'PAPER-Z'::text AS broker_account_id,7::bigint AS takeover_epoch,
        'completed-plan'::text AS plan_id,'CONTROLLER'::text AS rollout_mode,
        11::bigint AS rollout_version,'old-certificate'::text AS certificate_sha256""")
    conn.execute("""CREATE TEMP TABLE sentinel_execution_plans AS SELECT
        'completed-plan'::text AS plan_id,'successor-plan'::text AS superseded_by,
        'owned-deployment'::text AS deployment_id,'alpaca'::text AS broker,
        'PAPER-Z'::text AS broker_account_id,7::bigint AS takeover_epoch,
        (clock_timestamp() AT TIME ZONE 'America/New_York')::date-1 AS decision_session,
        (clock_timestamp() AT TIME ZONE 'America/New_York')::date AS effective_session,
        '{"fictional-security":"7"}'::jsonb AS target_basket,.55::numeric AS target_exposure,
        'CONTROLLER'::text AS rollout_mode,11::bigint AS rollout_version,
        'old-certificate'::text AS rollout_certificate_sha256""")
    conn.execute("""INSERT INTO sentinel_execution_plans SELECT 'successor-plan',NULL,
        deployment_id,broker,broker_account_id,takeover_epoch,decision_session,effective_session,
        target_basket,target_exposure,rollout_mode,12,'new-certificate'
        FROM sentinel_execution_plans""")
    conn.execute('CREATE TEMP TABLE sentinel_corpus_publications(version bigint)')
    conn.execute('INSERT INTO sentinel_corpus_publications VALUES (1)')


def successor_predicate(conn,statement=None):
    statement=statement or checks.snapshot_sql('POST_TRADE_SUCCESSOR')
    prefix=statement.split('SELECT json_build_object(',1)[0]
    predicate=statement.split("'ready',",1)[1].split("'reconciliation',",1)[0].strip().rstrip(',')
    tail=statement[statement.rindex(' FROM sentinel_automation_control c CROSS JOIN candidates s'):]
    rows=conn.execute(prefix+'SELECT '+predicate+tail).fetchall()
    return len(rows)==1 and rows[0][0] is True


@pytest.mark.parametrize('change',[
    "UPDATE sentinel_automation_cycles SET control_generation=99",
    "UPDATE sentinel_automation_cycles SET completed_at=NULL",
    "UPDATE sentinel_automation_cycles SET execution_close_at=clock_timestamp()+interval '14 minutes'",
    "UPDATE sentinel_automation_cycles SET failure_detail='unresolved'",
    "UPDATE sentinel_execution_plans SET target_basket='{}' WHERE plan_id='successor-plan'",
    "UPDATE sentinel_execution_plans SET rollout_certificate_sha256='foreign' WHERE plan_id='successor-plan'",
    "UPDATE sentinel_execution_plans SET superseded_by='foreign' WHERE plan_id='completed-plan'",
    "UPDATE sentinel_execution_plans SET broker_account_id='foreign' WHERE plan_id='completed-plan'",
])
def test_successor_uses_real_original_current_join_and_database_clock(conn,change):
    successor_tables(conn)
    assert successor_predicate(conn) is True
    conn.execute(change)
    assert successor_predicate(conn) is False


def test_successor_generation_filter_has_an_executed_postgres_falsifier(conn):
    successor_tables(conn)
    conn.execute('UPDATE sentinel_automation_cycles SET control_generation=99')
    assert successor_predicate(conn) is False
    mutant=checks.snapshot_sql('POST_TRADE_SUCCESSOR').replace('s.control_generation<c.generation','TRUE')
    assert successor_predicate(conn,mutant) is True
