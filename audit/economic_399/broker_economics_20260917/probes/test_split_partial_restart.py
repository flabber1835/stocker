"""Compound audit: partially filled/cancelled DAY order + scalar action + restart."""
from dataclasses import replace
from datetime import date
from decimal import Decimal as D
import pytest
from test_partial_economics import pg, setup, run, AAA, DEPLOY, DAY, reconcile_and_check
from sentinel.execution import executor, journal, reconcile
from sentinel.execution.states import CommandState as S, RuntimeState
from sentinel.paper.cash import _cash_authority_or_refuse
from sentinel.feed import store

@pytest.mark.parametrize('factor',['2','0.25'])
def test_partial_cancel_known_split_lag_and_reconnect(setup, pg, factor):
    c,b,p=setup
    out=run(executor.execute_session(broker=b,conn=c,deployment=DEPLOY,plan=p,
         instruments={'SEC-AAA':AAA},today=DAY))
    key=out.submitted[0].client_key
    b.fill_at(key,'1','99');b.fill_at(key,'3','101')
    reconcile_and_check(c,b,p,D(4),D(9598))
    b._by_key(key).state=S.CANCELLED
    reconcile_and_check(c,b,p,D(4),D(9598))
    # Pin the historical creation coordinate in this synthetic broker timeline.
    # The standard production tests use the same fixture timestamp arrangement.
    c.execute('UPDATE sentinel_commands SET created_at=%s WHERE client_key=%s',(b.now,key));c.commit()
    f=D(factor); event=date(2026,8,12)
    actions=reconcile.CorpusActionLookup(start=DAY,events={'SEC-AAA':((event,f),)})
    original=journal.load_commands(c,DEPLOY)[0]
    before=run(reconcile.reconcile(broker=b,conn=c,binding=None,deployment=DEPLOY,actions=actions))
    assert before.runtime_state is RuntimeState.RUNNING and not before.clean
    assert before.transport_ready
    assert before.expected=={'SEC-AAA':D(4)*f}
    assert before.observed=={'SEC-AAA':D(4)}
    # Broker delivers only the split entitlement, with no cash movement or fill.
    b._positions['SEC-AAA']=(AAA,D(4)*f)
    for _ in range(3):
        c.close();c=store.connect(pg.sync_dsn)
        rec=run(reconcile.reconcile(broker=b,conn=c,binding=None,deployment=DEPLOY,actions=actions))
        assert rec.clean and rec.expected==rec.observed=={'SEC-AAA':D(4)*f}
        cmd=journal.load_commands(c,DEPLOY)[0]
        assert cmd.quantity==original.quantity==D(10)
        assert cmd.filled_quantity==D(4) and cmd.state is S.CANCELLED
        _cash_authority_or_refuse(c,plan=p,deployment=DEPLOY,account=run(b.account_snapshot()),observation=rec.observation)
        assert b.cash==D(9598)
        assert c.execute('SELECT COUNT(*),SUM(quantity),SUM(quantity*price) FROM sentinel_fills').fetchone()==(2,D(4),D(402))
    assert len(b._orders)==1
    c.close()
