"""#399: positive native-fill authority acceptance; baseline aff4461d.

Only fake provider response fields vary. The imported fixture is retained
verbatim from the F19 evidence. All parsers, SQL, reconciliation, recovery
completion and notification reconstruction are the pinned implementation.
"""
from datetime import timedelta
from decimal import Decimal as D
import asyncio,json
import pytest
from sentinel.execution import reconcile as R
from sentinel.execution.states import RuntimeState
from sentinel.automation import outbox
from tests.audit399_continued import prior_fill_order as prior
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
    independently_coherent=(native_qty==expected_qty and native_gross==expected_gross and at>=prior.SUBMIT)
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
