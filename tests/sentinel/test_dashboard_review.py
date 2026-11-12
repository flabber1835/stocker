"""Actual private PostgreSQL review history, recovery and acknowledgement."""
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect
import json
import textwrap
import uuid

import psycopg
from psycopg import sql
import pytest

from sentinel import schema
from sentinel.panel import model, presentation, review, review_schema, review_store as store
from tests.support.postgres import _EphemeralPostgres


@pytest.fixture(scope='module')
def pg():
    server = _EphemeralPostgres()
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def conn(pg, monkeypatch):
    name = 'review_'+uuid.uuid4().hex
    with psycopg.connect(pg.sync_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    conn = psycopg.connect(pg.sync_dsn.rsplit('/',1)[0]+'/'+name)
    # Exact canonical table definitions, not approximate mock tables.
    names = {'sentinel_account_binding','sentinel_automation_control',
             'sentinel_automation_lease','sentinel_alert_outbox','sentinel_processed_sessions'}
    for statement in schema.DDL:
        if any('CREATE TABLE IF NOT EXISTS '+name+' (' in statement for name in names):
            conn.execute(statement)
    conn.execute("INSERT INTO sentinel_account_binding(deployment_id,broker,broker_account_id,ownership_state) "
                 "VALUES ('private','alpaca','qualification-account','SENTINEL_OWNED')")
    conn.execute('INSERT INTO sentinel_automation_control(id) VALUES (1)')
    conn.execute('INSERT INTO sentinel_automation_lease(id) VALUES (1)')
    conn.commit()
    review_schema.install_quiescent(conn)
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY','qualification-only-'+'x'*40)
    monkeypatch.setenv('ALPACA_BASE_URL','https://paper-api.alpaca.markets')
    try:
        yield conn
    finally:
        conn.close()
        with psycopg.connect(pg.sync_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


def panel(**changes):
    now = datetime.now(timezone.utc)
    keys = ('runtime_identity','automation','automation_leader','authority','feed',
            'broker','alpaca_account','backup_restore','automation_alerts','alert_dispatcher')
    return model.Panel(rows=[model.Row(key,key,'CURRENT',changes.get(key,model.OK),
        as_of=now,freshness=timedelta(seconds=45),required_current=True) for key in keys],now=now)


def clean(recorder, conn):
    page = panel()
    observed = recorder.observe(page,conn.info.dsn)
    assert observed.status == 'REVIEW' and observed.token
    result = recorder.acknowledge(page,conn.info.dsn,observed.token,actor='qualification operator')
    assert result.status == 'CLEAN'
    return result


def test_planned_restart_is_amber_until_explicit_acknowledgement(conn):
    owner = review.Recorder()
    clean(owner,conn)
    assert owner.observe(panel(),conn.info.dsn).status == 'CLEAN'
    successor = review.Recorder().observe(panel(),conn.info.dsn)
    assert successor.status == 'REVIEW' and successor.token


def test_active_failure_stays_red_and_recovery_stays_amber(conn):
    owner = review.Recorder()
    baseline = clean(owner,conn)
    failed = panel(broker=model.FAIL)
    first = owner.observe(failed,conn.info.dsn)
    assert first.status == 'FAILED' and not first.token
    assert presentation.dashboard_health(replace(failed,operator_review=first))['color']=='red'
    assert owner.observe(failed,conn.info.dsn).head == first.head
    with pytest.raises(store.ReviewRefused,match='active'):
        owner.acknowledge(failed,conn.info.dsn,'invalid',actor='operator')
    recovered = owner.observe(panel(),conn.info.dsn)
    assert recovered.status == 'REVIEW' and recovered.reviewed_head == baseline.head
    assert owner.observe(panel(),conn.info.dsn).status == 'REVIEW'
    final = owner.acknowledge(panel(),conn.info.dsn,recovered.token,actor='operator')
    assert final.status == 'CLEAN'
    assert {'FAILED','RECOVERED','ACKNOWLEDGED'} <= {event['kind'] for event in final.events}


def test_removed_recovery_latch_is_detected(conn,monkeypatch):
    original = review._result
    def broken(c,key,state,now,**kwargs):
        state['reviewed_head'] = state['head']
        return original(c,key,state,now,**kwargs)
    monkeypatch.setattr(review,'_result',broken)
    with pytest.raises(AssertionError):
        test_active_failure_stays_red_and_recovery_stays_amber(conn)


def test_signed_failure_and_recovery_retain_original_condition_evidence(conn):
    owner=review.Recorder();clean(owner,conn)
    failed=panel(feed=model.FAIL)
    result=owner.observe(failed,conn.info.dsn)
    event=next(e for e in result.events if e['kind']=='FAILED')
    fact=event['details']['evidence']['feed']
    assert fact['raw_status']=='fail' and fact['effective_status']=='fail'
    assert fact['sampled_at']==failed.now.isoformat() and len(fact['detail_sha256'])==64
    recovered=owner.observe(panel(),conn.info.dsn)
    event=next(e for e in recovered.events if e['kind']=='RECOVERED' and e['details'].get('previous')==['feed'])
    assert event['details']['evidence']['feed']['effective_status']=='ok'
    assert recovered.status=='REVIEW' and recovered.reviewed_head<recovered.head


def test_material_warning_cannot_be_acknowledged_into_green(conn):
    owner=review.Recorder();clean(owner,conn)
    page=panel(backup_restore=model.WARN)
    page=replace(page,rows=[replace(row,required_current=False) if row.key=='backup_restore'
                            else row for row in page.rows])
    observed=owner.observe(page,conn.info.dsn)
    assert observed.status=='REVIEW' and observed.warnings and not observed.token
    with pytest.raises(store.ReviewRefused):
        owner.acknowledge(page,conn.info.dsn,'invalid',actor='operator')


def test_backend_unavailability_is_retained_after_recovery(conn,monkeypatch):
    owner=review.Recorder();clean(owner,conn)
    original=store.transaction
    @contextmanager
    def unavailable(*_args):
        raise OSError('private refusal')
        yield
    monkeypatch.setattr(store,'transaction',unavailable)
    assert owner.observe(panel(),conn.info.dsn).status=='UNAVAILABLE'
    monkeypatch.setattr(store,'transaction',original)
    result=owner.observe(panel(),conn.info.dsn)
    assert result.status=='REVIEW'
    assert any(e['kind']=='FAILED' and e['details'].get('recovered_before_recording') for e in result.events)


def test_uncaught_backend_read_failure_is_latched_without_new_worker(conn):
    owner=review.Recorder();clean(owner,conn)
    owner.read_failed()
    assert owner.observe(panel(),conn.info.dsn).status=='REVIEW'


@pytest.mark.parametrize('change',['restart','new_failure','new_notification','scope','plan'])
def test_stale_view_cannot_acknowledge_changed_state(conn,change):
    owner=review.Recorder();page=panel()
    value=owner.observe(page,conn.info.dsn)
    if change=='restart':
        review.Recorder().observe(page,conn.info.dsn)
    elif change=='new_failure':
        owner.observe(panel(feed=model.FAIL),conn.info.dsn)
    elif change=='new_notification':
        conn.execute("INSERT INTO sentinel_alert_outbox(alert_id,idempotency_key,schema_version,"
            "event_type,severity,payload,state,max_attempts) VALUES (%s,'private',1,'TRIAL_NOT_VERIFIED',"
            "'CRITICAL','{}','DELIVERED',3)",('a'*64,));conn.commit()
    elif change=='scope':
        conn.execute('UPDATE sentinel_account_binding SET takeover_epoch=2');conn.commit()
    else:
        page=replace(page,rows=[replace(row,source_publication_version=2) for row in page.rows])
    with pytest.raises(store.ReviewRefused):
        owner.acknowledge(page,conn.info.dsn,value.token,actor='operator')


@pytest.mark.parametrize('seconds',[-10,31])
def test_view_token_clock_is_finite(conn,seconds):
    owner=review.Recorder();page=panel();value=owner.observe(page,conn.info.dsn)
    now=datetime.now(timezone.utc)+timedelta(seconds=seconds)
    with pytest.raises(store.ReviewRefused):
        review.decode_token(value.token,now)


def test_explicit_ack_updates_only_reviewed_notification_metadata(conn):
    conn.execute("INSERT INTO sentinel_alert_outbox(alert_id,idempotency_key,schema_version,"
        "event_type,severity,payload,state,max_attempts) VALUES (%s,'private',1,'TRIAL_NOT_VERIFIED',"
        "'CRITICAL',%s::jsonb,'DELIVERED',3)",('b'*64,json.dumps({'verdict':'NOT_VERIFIED'})))
    conn.commit()
    owner=review.Recorder();clean(owner,conn)
    state,payload,ack=conn.execute('SELECT state,payload,ack_state FROM sentinel_alert_outbox').fetchone()
    assert (state,payload,ack)==('DELIVERED',{'verdict':'NOT_VERIFIED'},'ACKNOWLEDGED')
    result=owner.observe(panel(),conn.info.dsn)
    assert result.status=='CLEAN'


@pytest.mark.parametrize('sql_text',[
    'UPDATE sentinel_dashboard_review_events SET kind=kind',
    'DELETE FROM sentinel_dashboard_review_events',
    'TRUNCATE sentinel_dashboard_review_events',
])
def test_history_is_append_only_in_actual_postgres(conn,sql_text):
    clean(review.Recorder(),conn)
    with pytest.raises(psycopg.Error,match='append-only'):
        conn.execute(sql_text)
    conn.rollback()


def test_tampered_state_cannot_establish_green(conn):
    owner=review.Recorder();clean(owner,conn)
    conn.execute("UPDATE sentinel_dashboard_review_state SET payload=jsonb_set(payload,'{head}','0')")
    conn.commit()
    assert owner.observe(panel(),conn.info.dsn).status=='UNAVAILABLE'


def test_lost_review_store_cannot_establish_green(conn):
    clean(review.Recorder(),conn)
    conn.execute('DROP TABLE sentinel_dashboard_review_events')
    conn.commit()
    assert review.Recorder().observe(panel(),conn.info.dsn).status=='UNAVAILABLE'


def test_installer_refuses_a_live_or_unfenced_database(conn):
    conn.execute('UPDATE sentinel_automation_control SET kill_switch_engaged=false');conn.commit()
    with pytest.raises(Exception,match='fence|kill'):
        review_schema.install_quiescent(conn)


def test_normal_scheduled_work_is_green_after_acknowledgement(conn):
    from tests.sentinel.test_panel_historical_mirror_schedule import healthy_history_panel
    owner=review.Recorder();page=healthy_history_panel()
    value=owner.observe(page,conn.info.dsn)
    assert value.status=='REVIEW' and not value.warnings
    result=owner.acknowledge(page,conn.info.dsn,value.token,actor='operator')
    assert presentation.dashboard_health(replace(page,operator_review=result))['color']=='green'


def test_missing_required_current_fact_refuses_clean_state(conn):
    owner=review.Recorder();page=panel()
    value=owner.observe(replace(page,rows=page.rows[:-1]),conn.info.dsn)
    assert value.status=='FAILED' and 'missing:alert_dispatcher' in value.active


def test_heartbeat_and_market_values_do_not_invalidate_same_health_review(conn):
    owner=review.Recorder();page=panel();value=owner.observe(page,conn.info.dsn)
    changed=replace(page,rows=[replace(row,value='advancing') if row.key=='alpaca_account' else row
                              for row in page.rows])
    assert owner.acknowledge(changed,conn.info.dsn,value.token,actor='operator').status=='CLEAN'


def test_only_pending_capabilities_cannot_be_acknowledged_into_a_clean_interval(conn):
    owner=review.Recorder();clean(owner,conn)
    page=panel()
    page=replace(page,rows=[replace(row,status=model.PENDING,required_current=False) for row in page.rows])
    result=owner.observe(page,conn.info.dsn)
    assert result.status=='REVIEW' and result.warnings==['no_current_operation'] and not result.token
    recovered=owner.observe(panel(),conn.info.dsn)
    assert recovered.status=='REVIEW' and recovered.token


def test_removed_current_operation_guard_is_detected(conn,monkeypatch):
    source=inspect.getsource(presentation._health_facts)
    guard="warnings.append('no_current_operation')"
    assert source.count(guard)==1
    namespace=dict(vars(presentation))
    exec(compile(source.replace(guard,'pass'),'removed-current-operation','exec'),namespace)
    monkeypatch.setattr(presentation,'_health_facts',namespace['_health_facts'])
    with pytest.raises(AssertionError):
        test_only_pending_capabilities_cannot_be_acknowledged_into_a_clean_interval(conn)


def test_additive_review_catalog_preserves_installed_financial_marker(pg,monkeypatch):
    from sentinel import operational_schema
    from sentinel.feed import store as feed_store
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY','qualification-only-'+'x'*40)
    name='catalog_'+uuid.uuid4().hex
    with psycopg.connect(pg.sync_dsn,autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    c=psycopg.connect(pg.sync_dsn.rsplit('/',1)[0]+'/'+name)
    try:
        schema.ensure_schema(c);feed_store.migrate_schema(c)
        c.execute('INSERT INTO sentinel_automation_control(id) VALUES (1) ON CONFLICT DO NOTHING')
        c.execute('INSERT INTO sentinel_automation_lease(id) VALUES (1) ON CONFLICT DO NOTHING');c.commit()
        before=operational_schema.install_quiescent(c)
        assert 'sentinel.panel.review_schema' not in before['contracts']
        c.commit();review_schema.install_quiescent(c)
        assert operational_schema.installation(c,required=True)==before
        schema.require_runtime_schema(c)
        assert review_schema.require_schema(c)
        c.execute('ALTER TABLE sentinel_dashboard_review_events DISABLE TRIGGER sentinel_dashboard_review_history_guard');c.commit()
        with pytest.raises(Exception,match='CATALOG_CHANGED'):
            review_schema.require_schema(c)
        c.rollback()
    finally:
        c.close()
        with psycopg.connect(pg.sync_dsn,autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
