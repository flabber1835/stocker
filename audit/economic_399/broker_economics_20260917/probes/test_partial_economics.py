"""Independent priced-fill ledger versus exact pinned command/cash persistence.

Audit evidence only. Real PostgreSQL + journal/reconciliation; simulated transport.
The oracle uses its own execution ledger and deliberately varies fill prices.
"""
from __future__ import annotations
import asyncio
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal as D
import pytest

from tests.support.postgres import _EphemeralPostgres, drop_public_tables
from sentinel import binding, schema, backup_runtime_authority
from sentinel.feed import store
from sentinel.execution import executor, journal, reconcile, recovery
from sentinel.execution.alpaca import NativeBrokerFill
from sentinel.execution.contract import BrokerInstrument, Side
from sentinel.execution.identity import DeploymentIdentity
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.simulator import SimulatedBroker
from sentinel.execution.states import CommandState as S, RuntimeState
from sentinel.paper.cash import _cash_authority_or_refuse

DEPLOY = DeploymentIdentity('audit399', 'sim', 'SIM-ACCOUNT', 1)
AAA = BrokerInstrument(security_id='SEC-AAA', symbol='AAA', broker_id='sim-AAA')
DAY = date(2026,8,11)
def run(coro): return asyncio.run(coro)

class OracleBroker(SimulatedBroker):
    """Actual ledger cash is independent of production cumulative-average math."""
    def __post_init__(self):
        super().__post_init__()
        self.executions = []
    def fill_at(self, key, qty, price):
        r = self._by_key(key); qty, price = D(qty), D(price)
        assert r is not None and 0 < qty <= r.remaining and price > 0
        r.filled += qty
        instrument, held = self._positions.get(r.instrument.security_id, (r.instrument,D(0)))
        signed = qty if r.side is Side.BUY else -qty
        self._positions[r.instrument.security_id] = (instrument, held + signed)
        self.cash -= signed * price
        f = NativeBrokerFill(client_key=key, broker_order_id=r.broker_order_id,
              quantity=qty, price=price, filled_at=self.now,
              activity_id=f'oracle-{len(self.executions)+1}')
        self.executions.append(f)
        r.state = S.FILLED if r.remaining == 0 else S.PARTIALLY_FILLED
    def _priced(self, o):
        fills = [f for f in self.executions if f.broker_order_id == o.broker_order_id]
        avg = sum((f.quantity*f.price for f in fills),D(0))/o.filled_quantity if o.filled_quantity else None
        return replace(o, filled_average_price=avg)
    def _snapshot_orders(self):
        return [self._priced(o) for o in super()._snapshot_orders()]
    async def find_by_client_key(self,key):
        out=await super().find_by_client_key(key)
        return replace(out, order=self._priced(out.order) if out.order else None)
    async def observe_with_terminal_recovery(self, *, submitted_after, processed_through):
        out=await super().observe_with_terminal_recovery(submitted_after=submitted_after,processed_through=processed_through)
        # Return the full native history each time: exactly-once ingestion must
        # tolerate overlap and preserve equal-timestamp identical partial fills.
        return replace(out, fills=tuple(reversed(self.executions)))

@pytest.fixture(scope='module')
def pg():
    server=_EphemeralPostgres(); server.start()
    yield server
    server.stop()

@pytest.fixture()
def setup(pg,monkeypatch,tmp_path):
    monkeypatch.setattr(backup_runtime_authority,'POLICY_MARKER',tmp_path/'no-production-policy')
    c=store.connect(pg.sync_dsn); drop_public_tables(c); schema.ensure_schema(c)
    store.migrate_schema(c); store.require_feed_schema(c)
    b=OracleBroker(cash=D('10000'),equity=D('10000'))
    binding.bind(c,deployment_id=DEPLOY.deployment_id,broker=DEPLOY.broker,broker_account_id=DEPLOY.broker_account_id)
    with c.cursor() as cur:
        cur.execute('UPDATE sentinel_account_binding SET established_at=%s WHERE id=1',(b.now,))
    c.commit()
    p=ExecutionPlan('audit-partial',DAY,DAY,D(1),{'SEC-AAA':D(10)},data_version=1,
                    deployment_id=DEPLOY.deployment_id,broker='sim',broker_account_id='SIM-ACCOUNT',
                    takeover_epoch=1,account_nav=D('10000'),account_cash=D('10000'))
    executor.adopt_plan(c,p); c.commit()
    yield c,b,p
    if not c.closed: c.close()

def reconcile_and_check(c,b,p,expected_qty,expected_cash):
    result=run(reconcile.reconcile(broker=b,conn=c,binding=None,deployment=DEPLOY))
    assert result.runtime_state is RuntimeState.RUNNING, result.detail
    rows=journal.load_commands(c,DEPLOY)
    expected=reconcile.expected_book_from_commands(rows)
    assert expected.get('SEC-AAA',D(0)) == expected_qty
    assert result.observed.get('SEC-AAA',D(0)) == expected_qty
    assert b.cash == expected_cash
    _cash_authority_or_refuse(c,plan=p,deployment=DEPLOY,
        account=run(b.account_snapshot()),observation=result.observation)
    c.commit()
    return result

@pytest.mark.parametrize('parts',[
    [('2','99.75'),('3','101.10'),('5','102.03')],
    [('2','100'),('2','100'),('6','98.75')],
    [('0.125','99.99'),('0.875','101.01'),('9','100.11')],
])
def test_priced_partial_fills_duplicate_history_and_restart(setup,pg,parts):
    c,b,p=setup
    out=run(executor.execute_session(broker=b,conn=c,deployment=DEPLOY,plan=p,instruments={'SEC-AAA':AAA},today=DAY))
    assert len(out.submitted)==1 and out.submitted[0].state is S.ACKNOWLEDGED
    key=out.submitted[0].client_key
    qty,cash=D(0),D('10000')
    for amount,price in parts:
        b.fill_at(key,amount,price); qty+=D(amount); cash-=D(amount)*D(price)
        reconcile_and_check(c,b,p,qty,cash)
        c.close(); c=store.connect(pg.sync_dsn)
        # Replayed native history and a new SQL session conserve both units.
        reconcile_and_check(c,b,p,qty,cash)
        b.now+=timedelta(seconds=1)
    assert journal.load_commands(c,DEPLOY)[0].state is S.FILLED
    with c.cursor() as cur:
        cur.execute('SELECT COUNT(*),SUM(quantity),SUM(quantity*price) FROM sentinel_fills')
        count,q,n=cur.fetchone()
    assert count==len(parts) and q==D(10) and n==D('10000')-cash
    out=run(executor.execute_session(broker=b,conn=c,deployment=DEPLOY,plan=p,instruments={'SEC-AAA':AAA},today=DAY))
    assert out.submitted==() and len(b._orders)==1
    c.close()

def test_partial_cancel_then_sale_uses_actual_notional(setup,pg):
    c,b,p=setup
    out=run(executor.execute_session(broker=b,conn=c,deployment=DEPLOY,plan=p,instruments={'SEC-AAA':AAA},today=DAY))
    key=out.submitted[0].client_key
    b.fill_at(key,'4','101.25')
    reconcile_and_check(c,b,p,D(4),D('9595'))
    # Genuine terminal broker receipt with four executed shares.
    b._by_key(key).state=S.CANCELLED
    reconcile_and_check(c,b,p,D(4),D('9595'))
    c.close(); c=store.connect(pg.sync_dsn)
    rows=journal.load_commands(c,DEPLOY)
    assert rows[0].state is S.CANCELLED and rows[0].filled_quantity==D(4)
    # New independently authorized decision is a sale, never an old-intent retry.
    p2=replace(p,plan_id='audit-sale',decision_session=date(2026,8,12),effective_session=date(2026,8,12),
               target_basket={'SEC-AAA':D(0)},account_cash=D('9595'))
    executor.adopt_plan(c,p2); c.commit()
    out=run(executor.execute_session(broker=b,conn=c,deployment=DEPLOY,plan=p2,instruments={'SEC-AAA':AAA},today=p2.effective_session))
    assert len(out.submitted)==1
    sell=out.submitted[0]; assert sell.side is Side.SELL and sell.quantity==D(4)
    b.fill_at(sell.client_key,'1.5','103.4')
    reconcile_and_check(c,b,p2,D('2.5'),D('9750.10'))
    b.fill_at(sell.client_key,'2.5','102.8')
    reconcile_and_check(c,b,p2,D(0),D('10007.10'))
    c.close(); c=store.connect(pg.sync_dsn)
    reconcile_and_check(c,b,p2,D(0),D('10007.10'))
    assert len(b._orders)==2
    c.close()
