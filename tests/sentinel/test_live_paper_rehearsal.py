"""Falsifiers for the attended real-paper test boundary; no provider calls."""
import asyncio
from decimal import Decimal

import pytest

from tools.live_paper_rehearsal import AttendedRun, Refused


@pytest.fixture(autouse=True)
def dummy_credentials(monkeypatch):
    monkeypatch.setenv('ALPACA_API_KEY','test-only-key')
    monkeypatch.setenv('ALPACA_SECRET_KEY','test-only-secret')


def test_rehearsal_cannot_exceed_owner_limit(tmp_path):
    for limit in ('0','-1','5000.01'):
        with pytest.raises(Refused, match='maximum'):
            AttendedRun(output=tmp_path/limit,account_sha256='a'*64,maximum=Decimal(limit))


@pytest.mark.parametrize('change', [
    {'qty':'2'}, {'symbol':'QQQ'}, {'side':'sell'}, {'side':'short'},
    {'client_order_id':'not-this-run'}, {'time_in_force':'gtc'},
    {'extended_hours':True}, {'qty':'NaN'},
    {'type':'stop'}, {'order_class':'bracket'}, {'notional':'50000'},
    {'type':'limit','limit_price':'5001'},
])
def test_mutation_guard_refuses_outside_test_envelope(tmp_path, monkeypatch, change):
    run=AttendedRun(output=tmp_path/'run',account_sha256='a'*64,maximum=Decimal(5000))
    run.buy_window_open=True
    monkeypatch.setattr(run,'production_fenced',lambda:None)
    async def snapshot():
        return {'cash':'50000'},[],[],Decimal(0)
    async def quote():
        return Decimal(99),Decimal(100)
    monkeypatch.setattr(run,'snapshot',snapshot)
    monkeypatch.setattr(run,'quote',quote)
    run.keys.add('owned')
    body={'symbol':'SPY','qty':'1','side':'buy','type':'market',
          'time_in_force':'day','client_order_id':'owned','extended_hours':False,**change}
    with pytest.raises(Refused):
        asyncio.run(run.authorize('POST','https://paper-api.alpaca.markets/v2/orders',body))


def test_rehearsal_rejects_live_host_and_foreign_cancel(tmp_path,monkeypatch):
    run=AttendedRun(output=tmp_path/'run',account_sha256='a'*64,maximum=Decimal(5000))
    with pytest.raises(Refused,match='PAPER'):
        asyncio.run(run.authorize('POST','https://api.alpaca.markets/v2/orders',{}))
    monkeypatch.setattr(run,'production_fenced',lambda:None)
    with pytest.raises(Refused,match='this run'):
        asyncio.run(run.authorize('DELETE','https://paper-api.alpaca.markets/v2/orders/foreign',{}))


def test_authorized_bounded_buy_can_reach_adapter(tmp_path,monkeypatch):
    run=AttendedRun(output=tmp_path/'run',account_sha256='a'*64,maximum=Decimal(5000))
    run.buy_window_open=True
    monkeypatch.setattr(run,'production_fenced',lambda:None)
    async def snapshot():
        return {'cash':'50000'},[],[],Decimal(0)
    async def quote():
        return Decimal(99),Decimal(100)
    monkeypatch.setattr(run,'snapshot',snapshot)
    monkeypatch.setattr(run,'quote',quote)
    run.keys.add('owned')
    asyncio.run(run.authorize('POST','https://paper-api.alpaca.markets/v2/orders',
        {'symbol':'SPY','qty':'1','side':'buy','type':'market','time_in_force':'day',
         'client_order_id':'owned','extended_hours':False}))


def test_production_fence_is_checked_before_mutation(tmp_path,monkeypatch):
    run=AttendedRun(output=tmp_path/'run',account_sha256='a'*64,maximum=Decimal(5000))
    def refuse():
        raise Refused('production is active')
    monkeypatch.setattr(run,'production_fenced',refuse)
    with pytest.raises(Refused,match='production is active'):
        asyncio.run(run.authorize('DELETE','https://paper-api.alpaca.markets/v2/orders/foreign',{}))


def test_removed_exposure_guard_is_detected(tmp_path,monkeypatch):
    import inspect
    import textwrap
    from types import MethodType
    import tools.live_paper_rehearsal as module
    run=AttendedRun(output=tmp_path/'run',account_sha256='a'*64,maximum=Decimal(5000))
    run.buy_window_open=True
    monkeypatch.setattr(run,'production_fenced',lambda:None)
    async def snapshot():return {'cash':'50000'},[],[],Decimal(4900)
    async def quote():return Decimal(99),Decimal(100)
    monkeypatch.setattr(run,'snapshot',snapshot)
    monkeypatch.setattr(run,'quote',quote)
    run.keys.add('owned')
    body=dict(symbol='SPY',qty='1',side='buy',type='market',time_in_force='day',
              client_order_id='owned',extended_hours=False)
    with pytest.raises(Refused,match='envelope'):
        asyncio.run(run.authorize('POST',module.PAPER+'/v2/orders',body))
    code=textwrap.dedent(inspect.getsource(AttendedRun.authorize))
    changed=code.replace('exposure+working+reserve>self.maximum','False')
    assert changed!=code
    namespace=dict(vars(module))
    exec(changed,namespace)
    # The same over-budget request would reach transport if this guard vanished.
    asyncio.run(MethodType(namespace['authorize'],run)('POST',module.PAPER+'/v2/orders',body))
