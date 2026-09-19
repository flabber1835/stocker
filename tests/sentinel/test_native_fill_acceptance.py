"""Native-fill acceptance through the actual parser, journal and reconciler."""
from datetime import timedelta
from decimal import Decimal as D
import asyncio,json
import pytest
from sentinel.execution import reconcile as R
from sentinel.execution.states import RuntimeState
from sentinel.automation import outbox
from tests.support import native_fill_fixture as prior
from tests.sentinel.test_rolling_snapshot_publisher import pg,conn

CASES=[
 ('one-valid-fill',('10',),('100',),0,True),
 ('two-valid-fills',('5','5'),('90','110'),0,True),
 ('three-valid-fractional-fills',('2.5','2.5','5'),('80','120','100'),0,True),
 ('one-valid-at-submission',('10',),('100',),-60,True),
 ('single-oversized-fill',('20',),('100',),0,False),
 ('cumulative-oversized-fills',('6','6'),('100','100'),0,False),
 ('single-gross-notional-conflict',('10',),('101',),0,False),
 ('cumulative-gross-notional-conflict',('5','5'),('100','101'),0,False),
 ('native-fill-before-submission',('10',),('100',),-1800,False),
 ('native-fill-next-session',('10',),('100',),86400,False),
]

@pytest.mark.parametrize('label,quantities,prices,offset,coherent',CASES,ids=[c[0] for c in CASES])
def test_native_fill_authority_requires_order_economic_coherence(conn,label,quantities,prices,offset,coherent):
    at=prior.FILL+timedelta(seconds=offset)
    owner,command,broker,http,events=prior.fixture(conn,native_quantities=quantities,fill_time=at)
    for event,price in zip(events,prices,strict=True):
        event['price']=price;event['net_amount']=str(-D(event['qty'])*D(price))
    http.routes['/v2beta1/events/activities']=prior.Response(text=prior.sse(*events))
    expected_qty=D(10); expected_gross=D(1000)
    native_qty=sum(map(D,quantities),D(0))
    native_gross=sum((D(q)*D(p) for q,p in zip(quantities,prices,strict=True)),D(0))
    independently_coherent=(native_qty==expected_qty and native_gross==expected_gross
        and prior.SUBMIT <= at <= prior.SUBMIT.replace(hour=20, minute=0))
    assert independently_coherent is coherent
    result=asyncio.run(R.reconcile(broker=broker,conn=conn,binding=None,deployment=owner.identity))
    conn.execute('UPDATE sentinel_notification_policy SET web_push_activated_at=%s WHERE id=1',(prior.START,))
    conn.commit();outbox._reconstruct_missing_transition_alerts(conn);conn.commit()
    retained=conn.execute('SELECT COALESCE(SUM(quantity),0),COALESCE(SUM(quantity*price),0),COUNT(*) FROM sentinel_fills').fetchone()
    normal_alerts=conn.execute("SELECT COUNT(*) FROM sentinel_alert_outbox WHERE event_type='BROKER_FILL'").fetchone()[0]
    diagnostic={'case':label,'native_quantity':str(native_qty),'native_gross':str(native_gross),
                'order_quantity':'10','order_gross':'1000','filled_at':at.isoformat(),
                'submitted_at':prior.SUBMIT.isoformat(),'runtime':result.runtime_state.value,
                'journal':list(map(str,retained)),'normal_fill_alerts':normal_alerts}
    print(json.dumps(diagnostic))
    if coherent:
        assert result.runtime_state is RuntimeState.RUNNING and result.clean
        assert retained==(expected_qty,expected_gross,len(quantities))
        assert normal_alerts==len(quantities)
        for _ in range(2):
            again=asyncio.run(R.reconcile(broker=broker,conn=conn,binding=None,deployment=owner.identity))
            assert again.clean and again.expected==again.observed=={'SEC-AAPL':D(10)}
        assert conn.execute('SELECT COUNT(*) FROM sentinel_fills').fetchone()[0]==len(quantities)
    else:
        assert result.runtime_state is not RuntimeState.RUNNING,diagnostic
        assert retained[2]==0 and normal_alerts==0,diagnostic
    assert all(method=='GET' for method,*_ in http.calls)


@pytest.mark.parametrize('initial', [(), ('6',)])
def test_delayed_complete_native_history_converges_without_partial_entitlement(conn, initial):
    from sentinel import paper_performance, trial
    from types import SimpleNamespace
    owner, command, broker, http, events = prior.fixture(conn, native_quantities=initial)
    result = asyncio.run(R.reconcile(broker=broker,conn=conn,binding=None,deployment=owner.identity))
    assert result.runtime_state is RuntimeState.RECONCILING
    assert conn.execute('SELECT count(*) FROM sentinel_fills').fetchone()[0] == 0
    with pytest.raises(trial.TrialEvidenceRefused, match='unresolved commands'):
        paper_performance.scan_entitlements(conn, binding=owner.to_dict(), through=prior.FILL.date(),
            account=SimpleNamespace(cash=D(9000), equity=D(10000)))
    assert paper_performance.load(conn, owner.to_dict()) is None
    if events:
        later = dict(events[0], event_id='01J5R000000000000000099999',
                     ref_id='22222222-2222-2222-2222-000000999999', qty='4', net_amount='-400')
        events.append(later)
    else:
        from tests.sentinel.test_alpaca_boundary_overlay import activity_event
        events = [activity_event(activity_type='TRD', qty='10', price='100', net_amount='-1000',
            at=prior.FILL.isoformat(), executed_at=prior.FILL.isoformat(),
            details={'execution_type':'fill','order_id':'order-1','client_order_id':command.client_key,
                     'asset_id':'asset-aapl','side':'buy'})]
    http.routes['/v2beta1/events/activities'] = prior.Response(text=prior.sse(*events))
    for _ in range(3):
        result = asyncio.run(R.reconcile(broker=broker,conn=conn,binding=None,deployment=owner.identity))
        assert result.runtime_state is RuntimeState.RUNNING and result.clean
    assert conn.execute('SELECT SUM(quantity), SUM(quantity*price) FROM sentinel_fills').fetchone() == (D(10),D(1000))


@pytest.mark.parametrize('field,value', [('asset_id','other-asset'), ('side','sell'),
    ('execution_type','unknown'), ('execution_type',None), ('asset_id',None), ('side',None)])
def test_native_identity_and_execution_type_cannot_be_dropped(conn, field, value):
    owner, _, broker, http, events = prior.fixture(conn, native_quantities=('10',))
    events[0]['details'][field] = value
    http.routes['/v2beta1/events/activities'] = prior.Response(text=prior.sse(*events))
    result = asyncio.run(R.reconcile(broker=broker,conn=conn,binding=None,deployment=owner.identity))
    assert result.runtime_state is not RuntimeState.RUNNING
    assert conn.execute('SELECT count(*) FROM sentinel_fills').fetchone()[0] == 0
    saved = conn.execute("SELECT state FROM sentinel_processed_sessions "
                         "WHERE cursor_name LIKE 'native-fill-refusal:%'").fetchall()
    assert len(saved) == 1
    assert events[0]['ref_id'] in json.dumps(saved[0][0])


@pytest.mark.parametrize('execution_type', ['trade_correct', 'trade_bust'])
def test_unsupported_native_correction_retains_diagnostic_without_publishing(conn, execution_type):
    owner, _, broker, http, events = prior.fixture(conn, native_quantities=('10',))
    events[0]['details']['execution_type'] = execution_type
    http.routes['/v2beta1/events/activities'] = prior.Response(text=prior.sse(*events))
    for _ in range(2):
        result = asyncio.run(R.reconcile(broker=broker,conn=conn,binding=None,deployment=owner.identity))
        assert result.runtime_state is not RuntimeState.RUNNING
    assert conn.execute('SELECT count(*) FROM sentinel_fills').fetchone()[0] == 0
    saved = conn.execute("SELECT state FROM sentinel_processed_sessions "
                         "WHERE cursor_name LIKE 'native-fill-refusal:%'").fetchall()
    assert len(saved) == 1
    assert saved[0][0]['raw_event']['details']['execution_type'] == execution_type

__all__ = ['conn', 'pg']


@pytest.mark.parametrize('field,value', [('qty', 'NaN'), ('qty', '0'),
    ('price', '-1'), ('price', 'bad'), ('executed_at', 'not-a-time')])
def test_malformed_native_economics_retains_raw_diagnostic(conn, field, value):
    owner, _, broker, http, events = prior.fixture(conn, native_quantities=('10',))
    events[0][field] = value
    http.routes['/v2beta1/events/activities'] = prior.Response(text=prior.sse(*events))
    result = asyncio.run(R.reconcile(broker=broker, conn=conn, binding=None, deployment=owner.identity))
    assert result.runtime_state is not RuntimeState.RUNNING
    assert conn.execute('SELECT count(*) FROM sentinel_fills').fetchone()[0] == 0
    saved = conn.execute("SELECT state FROM sentinel_processed_sessions WHERE cursor_name LIKE 'native-fill-refusal:%'").fetchall()
    assert len(saved) == 1
    assert saved[0][0]['raw_event'][field] == value


def test_complete_native_history_cannot_replace_durable_execution_ids(conn):
    from copy import deepcopy
    owner, _, broker, http, events = prior.fixture(conn, native_quantities=('10',))
    result = asyncio.run(R.reconcile(broker=broker, conn=conn, binding=None, deployment=owner.identity))
    assert result.runtime_state is RuntimeState.RUNNING
    original = conn.execute('SELECT fill_key,quantity,price FROM sentinel_fills').fetchall()
    changed = deepcopy(events)
    changed[0]['ref_id'] = '33333333-3333-3333-3333-000000000001'
    changed[0]['event_id'] = '01J5R000000000000000099999'
    http.routes['/v2beta1/events/activities'] = prior.Response(text=prior.sse(*changed))
    for _ in range(2):
        result = asyncio.run(R.reconcile(broker=broker, conn=conn, binding=None, deployment=owner.identity))
        assert result.runtime_state is RuntimeState.RECONCILING
        assert result.observation.terminal_recovery_through is None
        assert conn.execute('SELECT fill_key,quantity,price FROM sentinel_fills').fetchall() == original
    assert conn.execute("SELECT count(*) FROM sentinel_processed_sessions WHERE cursor_name LIKE 'native-fill-refusal:%'").fetchone()[0]


@pytest.mark.parametrize('price,coherent', [('400', True), ('500', False), ('600', False)])
def test_partial_native_notional_leaves_positive_economics_for_missing_shares(conn, monkeypatch, price, coherent):
    from dataclasses import replace
    from fractions import Fraction

    owner, _, broker, http, events = prior.fixture(conn, native_quantities=('2',))
    events[0].update(price=price, net_amount=str(-D(2) * D(price)))
    http.routes['/v2beta1/events/activities'] = prior.Response(text=prior.sse(*events))
    observe = broker._observe_snapshot

    async def partial_history(**kwargs):
        # Model an explicitly incomplete event set; do not certify provider
        # completeness or alter the production adapter's capability flags.
        return replace(await observe(**kwargs), fill_history_complete=False)

    monkeypatch.setattr(broker, '_observe_snapshot', partial_history)
    # Ten shares cost $1,000. The eight missing shares need positive price.
    remaining_price = (Fraction(1000) - 2 * Fraction(price)) / 8
    assert (remaining_price > 0) is coherent
    result = asyncio.run(R.reconcile(broker=broker, conn=conn, binding=None, deployment=owner.identity))
    conn.execute('UPDATE sentinel_notification_policy SET web_push_activated_at=%s WHERE id=1', (prior.START,))
    conn.commit()
    outbox._reconstruct_missing_transition_alerts(conn)
    conn.commit()
    count = conn.execute('SELECT count(*) FROM sentinel_fills').fetchone()[0]
    if coherent:
        assert result.clean and result.runtime_state is RuntimeState.RUNNING, result.to_dict()
        assert count == 1
    else:
        assert result.runtime_state is RuntimeState.RECONCILING, result.to_dict()
        assert result.observation.terminal_recovery_through is None
        assert count == 0
        assert conn.execute('SELECT count(*) FROM sentinel_observations').fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM sentinel_alert_outbox WHERE event_type='BROKER_FILL'").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM sentinel_processed_sessions WHERE cursor_name LIKE 'native-fill-refusal:%'").fetchone()[0] == 1
    assert all(method == 'GET' for method, *_ in http.calls)
