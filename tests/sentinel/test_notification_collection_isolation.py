"""Provider I/O cannot delay push; bounded critical priority stays fair."""
import ast
import inspect
from threading import Event
from types import SimpleNamespace

import pytest

from sentinel import alert_service, execution_collector as collector
from sentinel.automation import outbox
from tests.sentinel.test_automation_outbox import conn, pg


def claim(conn):
    item=outbox.claim_next(conn,holder_id='isolated-sender')
    if item is not None:
        outbox.mark_delivered(conn,alert_id=item.alert_id,holder_id='isolated-sender',attempt=item.attempt_count)
    return item


def enqueue(conn,key,severity,payload=None):
    return outbox.enqueue(conn,idempotency_key=key,event_type='TEST',severity=severity,payload=payload or {})


def assert_critical_fairness(conn):
    first=enqueue(conn,'oldest-info','INFO')
    critical=[enqueue(conn,'critical-'+str(n),'CRITICAL') for n in range(5)]
    delivered=[claim(conn) for _ in range(4)]
    assert [item.alert_id for item in delivered[:3]]==[item.alert_id for item in critical[:3]]
    assert delivered[3].alert_id==first.alert_id,'critical traffic starved the oldest ordinary alert'


def test_at_most_three_critical_claims_can_bypass_oldest_due_alert(conn):
    assert_critical_fairness(conn)


def test_priority_counter_survives_sender_restart(conn):
    ordinary=enqueue(conn,'ordinary','INFO')
    for n in range(4):enqueue(conn,'critical-'+str(n),'CRITICAL')
    for _ in range(3):assert claim(conn).severity=='CRITICAL'
    from sentinel.feed import store
    replacement=store.connect(conn.info.dsn)
    try:
        assert claim(replacement).alert_id==ordinary.alert_id
    finally:replacement.close()


def test_later_critical_event_cannot_overtake_its_incident_predecessor(conn):
    warning=enqueue(conn,'incident-warning','WARN',{'cycle_id':'same-cycle'})
    successor=enqueue(conn,'incident-critical','CRITICAL',{'cycle_id':'same-cycle'})
    independent=enqueue(conn,'other-critical','CRITICAL',{'cycle_id':'different-cycle'})
    assert claim(conn).alert_id==independent.alert_id
    assert claim(conn).alert_id==warning.alert_id
    assert claim(conn).alert_id==successor.alert_id


def test_recovery_waits_for_original_warning_even_when_warning_retry_is_delayed(conn):
    warning=enqueue(conn,'warning','WARN')
    recovery=enqueue(conn,'recovery','CRITICAL',{'warning_alert_id':warning.alert_id})
    conn.execute("UPDATE sentinel_alert_outbox SET next_attempt_at=clock_timestamp()+interval '1 hour' WHERE alert_id=%s",(warning.alert_id,));conn.commit()
    assert claim(conn) is None
    conn.execute("UPDATE sentinel_alert_outbox SET next_attempt_at=clock_timestamp()-interval '1 second' WHERE alert_id=%s",(warning.alert_id,));conn.commit()
    assert claim(conn).alert_id==warning.alert_id
    assert claim(conn).alert_id==recovery.alert_id


def test_removing_fairness_limit_has_a_real_sql_falsifier(conn,monkeypatch):
    source=inspect.getsource(outbox.claim_next)
    assert source.count('%s<3')==1
    namespace=dict(outbox.__dict__)
    exec(compile(source.replace('%s<3','%s<300'),'unguarded priority','exec'),namespace)
    monkeypatch.setattr(outbox,'claim_next',namespace['claim_next'])
    with pytest.raises(AssertionError,match='starved'):
        assert_critical_fairness(conn)


def test_sender_run_contains_no_broker_collection_or_broker_construction():
    tree=ast.parse(inspect.getsource(alert_service.run))
    names={node.id for node in ast.walk(tree) if isinstance(node,ast.Name)}
    assert not {'account_status','fill_notifications','AlpacaExecutionBroker'} & names
    assert 'dispatch_once' in inspect.getsource(alert_service.run)


def test_collector_uses_separate_bounded_calls_and_never_needs_push_key(monkeypatch,tmp_path):
    from sentinel import local_paper
    from sentinel.execution import fill_notifications
    monkeypatch.setattr(collector,'HEARTBEAT',tmp_path/'collector-heartbeat')
    monkeypatch.setattr(collector.signal,'signal',lambda *args:None)
    monkeypatch.setattr(local_paper,'enabled',lambda:True)
    monkeypatch.setenv(fill_notifications.SINCE_ENV,'2031-04-21T00:00:00+00:00')
    monkeypatch.delenv('SENTINEL_WEB_PUSH_VAPID_PRIVATE_KEY',raising=False)
    stop=Event();calls=[]
    def runner(operation,*args,**kwargs):
        calls.append((operation,args,kwargs))
        if args==('ACCOUNT',):raise TimeoutError('private stalled provider')
        if args==('FILL',):stop.set()
    monkeypatch.setattr(collector.supervisor_io,'report',lambda *args:None)
    assert collector.run(stopped=stop,runner=runner)==0
    assert [args[0] for operation,args,_ in calls if operation is collector.collect_once]==['ACCOUNT','FILL']
    assert all(options['timeout']<=30 and options['start_method']=='spawn' for _,_,options in calls)
    assert any(operation is collector.record_stall for operation,_,_ in calls)


def test_collector_refuses_push_signing_material_before_any_collection(monkeypatch):
    monkeypatch.setenv('SENTINEL_WEB_PUSH_VAPID_PRIVATE_KEY','must-not-be-here')
    with pytest.raises(ValueError,match='push signing'):
        collector.run(runner=lambda *args,**kwargs:pytest.fail('collector started'))
