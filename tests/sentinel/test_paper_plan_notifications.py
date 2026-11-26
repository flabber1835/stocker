"""Current-plan SELECT projection and durable notification on real PostgreSQL."""
from datetime import datetime, timedelta, timezone
import json

import pytest
from psycopg.types.json import Jsonb

from sentinel import paper_plan_preview as preview, web_push
from sentinel.automation import outbox
from sentinel.feed import store
from tests.sentinel.test_automation_outbox import conn, pg


def saved_plan(conn, *, shares='12'):
    store.migrate_schema(conn)
    now=conn.execute('SELECT clock_timestamp()').fetchone()[0]
    execute=now+timedelta(days=1)
    decision=now.date();effective=execute.date()
    conn.execute("UPDATE sentinel_automation_control SET enabled=true,kill_switch_engaged=false,"
        "deployment_id='fixture',broker='alpaca',broker_account_id='PAPER',takeover_epoch=1,"
        "certificate_sha256=%s,rollout_mode='PINNED_1_00',rollout_version=1,config_sha256=%s",
        ('a'*64,'b'*64))
    conn.execute("INSERT INTO sentinel_execution_plans "
        "(plan_id,decision_session,effective_session,target_exposure,rollout_mode,rollout_version,"
        "deployment_id,broker,broker_account_id,takeover_epoch,target_basket) "
        "VALUES ('saved-plan',%s,%s,1,'PINNED_1_00',1,'fixture','alpaca','PAPER',1,%s)",
        (decision,effective,Jsonb({'one':shares})))
    conn.execute("INSERT INTO sentinel_automation_cycles "
        "(cycle_id,state,decision_session,effective_session,deployment_id,broker,broker_account_id,"
        "takeover_epoch,control_generation,certificate_sha256,rollout_mode,rollout_version,config_sha256,"
        "decision_close_at,prepare_at,execution_open_at,execute_at,execution_close_at,plan_id) "
        "VALUES (%s,'PLAN_READY',%s,%s,'fixture','alpaca','PAPER',1,1,%s,'PINNED_1_00',1,%s,"
        "%s,%s,%s,%s,%s,'saved-plan')",('c'*64,decision,effective,'a'*64,'b'*64,
        now,now,execute,execute,execute+timedelta(hours=6)))
    observation=conn.execute("INSERT INTO sentinel_observations(observed_at,completeness,positions,orders,runtime_state) "
        "VALUES (%s,'COMPLETE','{}','[]','RUNNING') RETURNING seq",(now,)).fetchone()[0]
    conn.execute("INSERT INTO sentinel_observation_provenance "
        "(observation_seq,broker,broker_account_id,observed_at) VALUES (%s,'alpaca','PAPER',%s)",
        (observation,now))
    conn.commit()
    return now,execute


def test_current_ready_plan_is_read_only_and_notification_survives_restart_once(conn):
    saved_plan(conn)
    conn.execute('BEGIN READ ONLY')
    value=preview.read(conn)
    assert value.trades==1 and value.legs[0].change_quantity==12
    assert conn.execute('SHOW transaction_read_only').fetchone()[0]=='on'
    conn.rollback()
    # The dispatcher discovers the durable ready plan; worker enqueue is not required.
    outbox._reconstruct_missing_transition_alerts(conn);conn.commit()
    outbox._reconstruct_missing_transition_alerts(conn);conn.commit()
    rows=conn.execute("SELECT event_type,severity,payload FROM sentinel_alert_outbox").fetchall()
    assert len(rows)==1 and rows[0][:2]==('PAPER_PLAN_READY','INFO')
    assert rows[0][2]['buys']==1 and rows[0][2]['proposed_only'] is True
    assert preview.read(conn,unnotified=True) is None
    assert conn.execute('SELECT count(*) FROM sentinel_commands').fetchone()[0]==0


def idle_hold_case(conn, monkeypatch, *, completion=False, removed=False):
    from sentinel import dual_plan_authority as authority
    from sentinel.panel import intent_memo
    from tests.sentinel.test_dashboard_intent_memo import value, insert
    now, _ = saved_plan(conn)
    conn.execute("UPDATE sentinel_automation_cycles SET plan_fingerprint=%s", ('b'*64,))
    conn.commit()
    raw = value('saved-plan')
    raw['decision_session'] = now.date().isoformat()
    raw['broker_observation']['account_identity']['account_id'] = 'PAPER'
    raw['broker_observation']['observed_at'] = now.isoformat()
    raw['broker_observation']['positions'][0]['quantity'] = '12'
    raw.pop('authority_sha256')
    raw['authority_sha256'] = authority._sha256(raw)
    insert(conn, raw)
    if completion:
        from sentinel.automation import notification_completion
        notification_completion.install(conn)
        conn.commit()
    memo = intent_memo.IntentMemo()
    calls = []
    original = authority.load_authority
    def counted(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(authority, 'load_authority', counted)
    monkeypatch.setattr(intent_memo, 'read', counted if removed else memo.read)
    for _ in range(3):
        outbox._reconstruct_missing_transition_alerts(conn, completion=completion)
        conn.commit()
    assert len(calls) == 1, 'unchanged HOLD authority decoded again'
    assert conn.execute('SELECT count(*) FROM sentinel_alert_outbox').fetchone()[0] == 0
    assert conn.execute('SELECT count(*) FROM sentinel_commands').fetchone()[0] == 0
    conn.rollback()
    conn.execute("UPDATE sentinel_processed_sessions SET state=jsonb_set(state,'{tickers,one}','\"FORGED\"') "
                 "WHERE cursor_name=%s", (authority._cursor('saved-plan'),))
    conn.commit()
    # Optional preview corruption cannot withhold an already committed critical alert.
    alert = outbox.enqueue(conn, idempotency_key='preserved-critical',event_type='CRITICAL_INCIDENT',
                           severity='CRITICAL',payload={'reason':'preserved'})
    assert outbox.claim_next(conn, holder_id='private').alert_id == alert.alert_id
    assert len(calls) == 1
    outbox.recover_notifications(conn)
    assert len(calls) == 2


@pytest.mark.parametrize('completion', [False, True])
def test_idle_hold_recovery_reuses_small_intent_and_detects_changed_authority(conn, monkeypatch, completion):
    idle_hold_case(conn, monkeypatch, completion=completion)


def test_removed_intent_reuse_has_an_executed_idle_work_falsifier(conn, monkeypatch):
    with pytest.raises(AssertionError, match='unchanged HOLD authority decoded again'):
        idle_hold_case(conn, monkeypatch, removed=True)


@pytest.mark.parametrize('quantity', ['NaN','not-a-number'])
def test_unreadable_optional_plan_cannot_block_critical_alert_delivery(conn, quantity):
    saved_plan(conn, shares=quantity)
    alert=outbox.enqueue(conn, idempotency_key='critical-incident', event_type='CRITICAL_INCIDENT',
        severity='CRITICAL', payload={'reason':'preserved incident'})
    claimed=outbox.claim_next(conn,holder_id='independent-dispatcher')
    assert claimed.alert_id==alert.alert_id and claimed.event_type=='CRITICAL_INCIDENT'
    assert conn.execute("SELECT count(*) FROM sentinel_alert_outbox WHERE event_type='PAPER_PLAN_READY'").fetchone()[0]==0


@pytest.mark.parametrize('fault',['no-trades','foreign','generation','superseded','expired','stale','incomplete','historical','killed'])
def test_no_false_next_open_trade_notification(conn,fault):
    saved_plan(conn,shares='0' if fault=='no-trades' else '12')
    statements={
        'foreign':"UPDATE sentinel_observation_provenance SET broker_account_id='FOREIGN'",
        'generation':"UPDATE sentinel_automation_control SET generation=2",
        'superseded':"UPDATE sentinel_execution_plans SET superseded_by='newer-plan'",
        'expired':"UPDATE sentinel_automation_cycles SET decision_close_at=clock_timestamp()-interval '4h',prepare_at=clock_timestamp()-interval '3h',execution_open_at=clock_timestamp()-interval '2h',execute_at=clock_timestamp()-interval '1h'",
        'stale':"UPDATE sentinel_observations SET observed_at=clock_timestamp()-interval '27h'",
        'incomplete':"UPDATE sentinel_observations SET completeness='INCOMPLETE'",
        'historical':"UPDATE sentinel_automation_cycles SET historical_state_only=true",
        'killed':"UPDATE sentinel_automation_control SET kill_switch_engaged=true"}
    if fault in statements:
        conn.execute(statements[fault]);conn.commit()
    outbox._reconstruct_missing_transition_alerts(conn);conn.commit()
    assert conn.execute('SELECT count(*) FROM sentinel_alert_outbox').fetchone()[0]==0


def test_ordinary_info_stays_quiet_and_plan_info_reaches_existing_push_pipeline(monkeypatch):
    from types import SimpleNamespace
    from sentinel import notification_policy
    class Connection:
        def close(self):pass
        def rollback(self):pass
    adapter=object.__new__(web_push.WebPushAlertAdapter)
    adapter._connection_factory=Connection
    monkeypatch.setattr(notification_policy,'removed_by_device',lambda *_:False)
    monkeypatch.setattr(preview, 'still_current', lambda *_args, **_kwargs: True)
    called=[]
    adapter._initialize_fanout=lambda alert:(called.append(alert.event_type) or (0,True))
    alert=SimpleNamespace(event_type='ORDINARY_INFO',severity='INFO',payload={})
    adapter.deliver(alert,'key')
    assert called==[]
    alert.event_type='PAPER_PLAN_READY'
    alert.payload={'execute_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}
    with pytest.raises(web_push.WebPushDeliveryFailure,match='no active Web Push subscriptions'):
        adapter.deliver(alert,'key')
    assert called==['PAPER_PLAN_READY']
    called.clear()
    alert.payload={'execute_at':(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()}
    adapter.deliver(alert,'key')
    assert called==[]


@pytest.mark.parametrize('fault', [None,'generation','foreign','superseded','killed'])
def test_queued_plan_is_revalidated_before_push_fanout(conn, pg, monkeypatch, fault):
    from types import SimpleNamespace
    from sentinel import notification_policy
    from sentinel.feed import store as feed_store
    now,execute=saved_plan(conn)
    statements={
        'generation':"UPDATE sentinel_automation_control SET generation=2",
        'foreign':"UPDATE sentinel_execution_plans SET broker_account_id='FOREIGN'",
        'superseded':"UPDATE sentinel_execution_plans SET superseded_by='newer-plan'",
        'killed':"UPDATE sentinel_automation_control SET kill_switch_engaged=true"}
    if fault:
        conn.execute(statements[fault]);conn.commit()
    monkeypatch.setattr(notification_policy,'removed_by_device',lambda *_:False)
    adapter=object.__new__(web_push.WebPushAlertAdapter)
    adapter._connection_factory=lambda:feed_store.connect(pg.sync_dsn)
    called=[]
    adapter._initialize_fanout=lambda alert:(called.append(alert.event_type) or (0,False))
    alert=SimpleNamespace(event_type='PAPER_PLAN_READY',severity='INFO',
        payload=dict(execute_at=execute.isoformat(),cycle_id='c'*64,plan_id='saved-plan'))
    adapter.deliver(alert,'key')
    assert called == ([] if fault else ['PAPER_PLAN_READY'])


def test_live_preview_does_not_publish_a_paper_notification(conn, monkeypatch):
    from sentinel.panel import sources

    saved_plan(conn)
    for table in ('sentinel_automation_control', 'sentinel_execution_plans',
                  'sentinel_automation_cycles', 'sentinel_observation_provenance'):
        conn.execute(f"UPDATE {table} SET broker='alpaca-live'")
    conn.commit()
    monkeypatch.setenv('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')
    outbox.recover_notifications(conn)
    assert conn.execute('SELECT count(*) FROM sentinel_alert_outbox').fetchone() == (0,)
    conn.rollback()
    monkeypatch.setenv('ALPACA_BASE_URL', 'https://api.alpaca.markets')
    monkeypatch.delenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE', raising=False)
    outbox.recover_notifications(conn)
    alert = outbox.claim_next(conn, holder_id='live-plan-observer')
    assert alert.event_type == 'LIVE_PLAN_READY'
    assert web_push.notification_payload(alert)['title'].startswith('Live trading plan')
    display, _ = sources._runtime_rows(conn.info.dsn)
    row = next(row for row in display if row.key == 'paper_plan')
    assert row.label == 'Next live plan' and row.paper_plan.trades == 1


def test_supersession_between_devices_retires_only_unsent_plan_receipts(conn, pg):
    from sentinel.automation.outbox import dispatch_once
    from tests.sentinel.test_notification_recovery import push_adapter
    from tests.sentinel.test_worker_notification_push import _add_subscription
    import asyncio

    saved_plan(conn)
    _add_subscription(conn, 'first-device')
    _add_subscription(conn, 'second-device', material=19)
    outbox.recover_notifications(conn)
    calls = []

    def send(endpoint, body, headers, timeout):
        calls.append(endpoint)
        with store.connect(pg.sync_dsn) as other:
            other.execute("UPDATE sentinel_execution_plans SET superseded_by='newer-plan'")
        return 201

    result = asyncio.run(dispatch_once(conn, adapter=push_adapter(pg, send), holder_id='first'))
    assert result.delivered and len(calls) == 1
    assert conn.execute('SELECT state,COUNT(*) FROM sentinel_web_push_deliveries GROUP BY state '
                        'ORDER BY state').fetchall() == [('DELIVERED', 1), ('RETIRED', 1)]
    assert conn.execute('SELECT count(*) FROM sentinel_web_push_subscriptions '
                        'WHERE retired_at IS NOT NULL').fetchone() == (0,)
