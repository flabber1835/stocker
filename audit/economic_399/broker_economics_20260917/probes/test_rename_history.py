"""Audit-only F3 adjacent seam: immutable history labels contaminate current units."""
from dataclasses import replace
from datetime import date
from decimal import Decimal as D
import pytest
from test_partial_economics import (pg, setup, run, AAA, DEPLOY, DAY,
    reconcile_and_check)
from sentinel.execution import executor, journal, reconcile
from sentinel.execution.states import RuntimeState
from sentinel.paper.targets import _preopen_active_security_ids, _informational_active_symbols
from sentinel.paper.model import PaperActivationRefused

@pytest.mark.parametrize('flat_before_rename', [False, True])
@pytest.mark.parametrize('historical_orders_visible', [False, True])
def test_settled_historical_symbol_refuses_current_same_asset(
        setup, pg, flat_before_rename, historical_orders_visible):
    c,b,p=setup
    out=run(executor.execute_session(broker=b,conn=c,deployment=DEPLOY,plan=p,
        instruments={'SEC-AAA':AAA},today=DAY))
    b.fill_at(out.submitted[0].client_key,'10','100')
    reconcile_and_check(c,b,p,D(10),D(9000))
    if flat_before_rename:
        sell_plan=replace(p,plan_id='old-sell',target_basket={'SEC-AAA':D(0)},account_cash=D(9000))
        executor.adopt_plan(c,sell_plan);c.commit()
        sell=run(executor.execute_session(broker=b,conn=c,deployment=DEPLOY,plan=sell_plan,
            instruments={'SEC-AAA':AAA},today=DAY)).submitted[0]
        b.fill_at(sell.client_key,'10','100')
        reconcile_and_check(c,b,sell_plan,D(0),D(10000))
    renamed=replace(AAA,symbol='NEW')
    b._positions['SEC-AAA']=(renamed,D(0) if flat_before_rename else D(10))
    current=replace(p,plan_id='new-current',decision_session=date(2026,8,12),
        effective_session=date(2026,8,13),account_cash=b.cash)
    actions=reconcile.CorpusActionLookup(start=DAY,events={})
    # All broker quantities and immutable asset IDs are coherent. Native
    # historical orders retain their old labels; current position uses NEW.
    rec=run(reconcile.reconcile(broker=b,conn=c,binding=None,deployment=DEPLOY,actions=actions))
    assert rec.runtime_state is RuntimeState.RUNNING and rec.clean
    for restart in range(2):
        rows=journal.load_commands(c,DEPLOY)
        ids=_preopen_active_security_ids(plan=current,commands=rows,actions=actions)
        assert ids==('SEC-AAA',)
        current_observation = (rec.observation if historical_orders_visible
                               else replace(rec.observation, orders=()))
        kwargs=dict(active_security_ids=ids,observation=current_observation,
                    sizing_proof={'canonical_symbols':{'SEC-AAA':'NEW'}})
        # Independent oracle: same permanent id + same broker asset + current
        # effective label; older executions do not create another current name.
        assert _informational_active_symbols(commands=(),**{**kwargs, 'observation':replace(rec.observation,orders=())})=={'SEC-AAA':'NEW'}
        with pytest.raises(PaperActivationRefused,match='conflicting canonical symbols'):
            _informational_active_symbols(commands=rows,**kwargs)
        c.close()
        from sentinel.feed import store
        c=store.connect(pg.sync_dsn)
    assert len(b._orders)==(2 if flat_before_rename else 1)
    c.close()
