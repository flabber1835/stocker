"""Provider I/O cannot delay push; bounded critical priority stays fair."""
import ast
import inspect
from threading import Event

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
    from sentinel.feed.issuer_refresh import CONTACT_ENV
    monkeypatch.setattr(collector,'HEARTBEAT',tmp_path/'collector-heartbeat')
    monkeypatch.setattr(collector.signal,'signal',lambda *args:None)
    monkeypatch.setattr(local_paper,'enabled',lambda:True)
    monkeypatch.setenv(fill_notifications.SINCE_ENV,'2031-04-21T00:00:00+00:00')
    monkeypatch.delenv(CONTACT_ENV, raising=False)
    monkeypatch.delenv('SENTINEL_WEB_PUSH_VAPID_PRIVATE_KEY',raising=False)
    stop = Event()
    monkeypatch.setattr(stop, "wait", lambda _seconds: stop.set())
    calls = []

    def runner(operation,*args,**kwargs):
        calls.append((operation,args,kwargs))
        if operation is collector.collect_once and args == ('ACCOUNT',):
            raise TimeoutError('private stalled provider')

    monkeypatch.setattr(collector.supervisor_io,'report',lambda *args:None)
    assert collector.run(stopped=stop,runner=runner)==0
    assert [(operation, args) for operation, args, _ in calls] == [
        (collector.collect_once, ('ACCOUNT',)),
        (collector.record_stall, ('ACCOUNT', 'TimeoutError')),
        (collector.collect_once, ('FILL', 0)),
    ]
    assert [options for _, _, options in calls] == [
        {'timeout': 48, 'start_method': 'spawn'},
        {'timeout': 5, 'start_method': 'spawn'},
        {'timeout': 30, 'start_method': 'spawn'},
    ]


def _account_job_near_publication_deadline(progress):
    """Exercise the spawned collector with deterministic dependency durations."""
    from types import SimpleNamespace
    from unittest.mock import Mock, patch
    from sentinel.execution import account_status, opening_display
    from sentinel.trading_environment import TradingEnvironment

    elapsed = 8  # Child imports, connection and binding checks.

    async def optional(*args, **kwargs):
        nonlocal elapsed
        elapsed += opening_display.TIMEOUT_SECONDS
        return None

    async def read(*args, **kwargs):
        nonlocal elapsed
        elapsed += account_status.DEADLINE_SECONDS - .5
        return object()

    async def publish(*args, **kwargs):
        progress.send(elapsed + account_status.PUBLICATION_SECONDS - .5)
        if not progress.poll(20):
            raise RuntimeError('test supervisor failed to release publication')
        progress.recv()
        return True

    config = SimpleNamespace(environment=TradingEnvironment.PAPER, database_url='fixture',
                             trading_endpoint='PAPER', assert_paper=lambda: None)
    with (patch.object(account_status, '_bound', return_value=('deployment', 'broker', 'account', 1)),
          patch.object(account_status, '_commands', return_value=[]),
          patch.object(opening_display, 'collect', optional),
          patch.object(account_status, '_collect', read),
          patch.object(account_status, '_publish', publish)):
        return collector.collect_once('ACCOUNT', reader=Mock(), config=config, connection_factory=Mock())


@pytest.mark.parametrize('legacy_limit,expected', [(False, 'COLLECTED'), (True, 'TimeoutError')])
def test_supervised_opening_account_can_publish_near_its_deadlines(monkeypatch, tmp_path, legacy_limit, expected):
    import multiprocessing
    import time
    from types import SimpleNamespace
    from sentinel import local_paper, supervisor_io
    from sentinel.execution import fill_notifications
    from sentinel.feed.issuer_refresh import CONTACT_ENV

    monkeypatch.setattr(collector, 'HEARTBEAT', tmp_path/'heartbeat')
    monkeypatch.setattr(collector.signal, 'signal', lambda *_: None)
    monkeypatch.setattr(local_paper, 'enabled', lambda: True)
    monkeypatch.setenv('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')
    for name in (CONTACT_ENV, fill_notifications.SINCE_ENV, 'SENTINEL_WEB_PUSH_VAPID_PRIVATE_KEY'):
        monkeypatch.delenv(name, raising=False)
    stop = Event()
    monkeypatch.setattr(stop, 'wait', lambda _: stop.set())
    monkeypatch.setattr(supervisor_io, 'report', lambda _: None)
    results = []

    def runner(operation, *args, timeout, start_method):
        if operation is collector.record_stall:
            assert timeout == 5 and args == ('ACCOUNT', 'TimeoutError')
            results.append(args[1])
            return
        assert operation is collector.collect_once and args == ('ACCOUNT',) and start_method == 'spawn'
        parent, child = multiprocessing.get_context(start_method).Pipe()
        with parent, child:
            # The real supervisor starts the child and sets its deadline. Move its
            # clock to the child's publication boundary, then allow a surviving
            # child to finish on the next iteration. No wall-clock race decides
            # whether the simulated opening read plus publication exceeds budget.
            def timestamps():
                yield 0.0
                assert parent.poll(20), 'spawned collector did not reach publication'
                elapsed = parent.recv()
                yield elapsed
                parent.send(True)
                resumed = time.monotonic()
                while True:
                    yield elapsed + time.monotonic() - resumed

            monkeypatch.setattr(supervisor_io, 'time', SimpleNamespace(monotonic=timestamps().__next__))
            results.append(supervisor_io.run(_account_job_near_publication_deadline, child,
                timeout=min(timeout, 30) if legacy_limit else timeout,
                start_method=start_method, cancelled=lambda: False))

    assert collector.run(stopped=stop, runner=runner) == 0
    assert results == [expected]


def test_collector_refuses_push_signing_material_before_any_collection(monkeypatch):
    monkeypatch.setenv('SENTINEL_WEB_PUSH_VAPID_PRIVATE_KEY','must-not-be-here')
    with pytest.raises(ValueError,match='push signing'):
        collector.run(runner=lambda *args,**kwargs:pytest.fail('collector started'))
