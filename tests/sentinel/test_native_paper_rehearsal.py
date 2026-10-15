"""The attended harness may transport only its current durable native intent."""
import asyncio
from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace

import pytest

from sentinel.execution.states import CommandState
from tools.native_paper_rehearsal import NativeRun,Refused
from tools.live_paper_rehearsal import AttendedRun,PAPER


def test_closed_native_campaign_cannot_resume_and_guard_removal_is_detected(tmp_path):
    import inspect
    import tools.native_paper_rehearsal as module
    module.require_open_native_run(tmp_path)
    (tmp_path/'native-run-closed.json').write_text('{"result":"FAIL"}')
    with pytest.raises(Refused,match='closed'):module.require_open_native_run(tmp_path)
    source=inspect.getsource(module.require_open_native_run)
    changed=source.replace("if (output/'native-run-closed.json').exists():",'if False:')
    assert changed!=source
    namespace=dict(vars(module));exec(changed,namespace)
    assert namespace['require_open_native_run'](tmp_path) is None


@pytest.mark.parametrize('damage',['missing','body','method','url','expired'])
def test_http_transport_requires_exact_unused_ticket(monkeypatch,damage):
    import tools.native_paper_rehearsal as module
    run=object.__new__(NativeRun)
    body=dict(symbol='asset',qty='1')
    url=PAPER+'/v2/orders'
    run._issue_transport_ticket('POST',url,body)
    method='POST'
    if damage=='missing':run._transport_ticket=None
    if damage=='body':body={**body,'qty':'2'}
    if damage=='method':method='DELETE'
    if damage=='url':url='https://api.alpaca.markets/v2/orders'
    if damage=='expired':monkeypatch.setattr(module.time,'monotonic',lambda:float('inf'))
    with pytest.raises(Refused,match='single-use'):
        asyncio.run(run.authorize(method,url,body))
    assert run._transport_ticket is None


@pytest.mark.parametrize('refused',[False,True])
def test_native_checks_run_before_inner_submit_and_prove_no_transport(monkeypatch,refused):
    import tools.native_paper_rehearsal as module
    from sentinel.execution.contract import BrokerCapabilities,BrokerInstrument,CommandOutcome,Side
    from sentinel.execution.guarded import PreTransportAuthorityRefused
    instrument=BrokerInstrument('security','SPY','asset')
    command=SimpleNamespace(client_key='owned',state=CommandState.SEND_PENDING,
        instrument=instrument,side=Side.BUY,quantity=Decimal(1))
    run=object.__new__(NativeRun)
    from datetime import datetime,timezone
    instant=datetime(2026,10,15,17,30,tzinfo=timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls,*_):return instant
    monkeypatch.setattr(module,'datetime',Clock)
    run.run_id='isolated-test'
    run._transport_ticket=None
    @contextmanager
    def connect():yield object()
    run.connect=connect
    run.production_fenced=lambda:None
    monkeypatch.setattr(module.binding,'require',lambda _:SimpleNamespace(broker_account_id='paper',identity='bound'))
    monkeypatch.setattr(module.journal,'load_commands',lambda *_a,**_k:[command])
    monkeypatch.setattr(module.journal,'latest_plan',lambda _:SimpleNamespace(plan_id='plan'))
    checked=[];submitted=[]
    async def authorize_command(method,url,body):
        checked.append(body)
        if refused:raise Refused('stale quote before adapter')
    run.authorize_command=authorize_command
    async def submit(**kwargs):
        submitted.append(kwargs)
        await run.authorize('POST',PAPER+'/v2/orders',checked[-1])
        return CommandOutcome(CommandState.ACKNOWLEDGED,'native-id')
    raw=SimpleNamespace(capabilities=BrokerCapabilities(),submit=submit,_now=lambda:instant)
    wrapped=run.guarded(raw,SimpleNamespace(plan_id='plan',effective_session=__import__('datetime').date(2026,10,15)))
    assert wrapped.capabilities is raw.capabilities
    if refused:
        with pytest.raises(PreTransportAuthorityRefused) as error:
            asyncio.run(wrapped.submit(client_key='owned',instrument=instrument,side=Side.BUY,quantity=Decimal(1)))
        assert not submitted
        wrapped.consume_not_transported(error.value,command)
        with pytest.raises(ValueError):wrapped.consume_not_transported(error.value,command)
    else:
        result=asyncio.run(wrapped.submit(client_key='owned',instrument=instrument,side=Side.BUY,quantity=Decimal(1)))
        assert result.state is CommandState.ACKNOWLEDGED and len(submitted)==1
        with pytest.raises(Refused):asyncio.run(run.authorize('POST',PAPER+'/v2/orders',checked[-1]))


@pytest.mark.parametrize('change',[
    {'state':CommandState.PLANNED},{'state':CommandState.FILLED},
    {'key':'foreign'}, {'plan':'obsolete'}, {'asset':'another-asset'},
    {'side':'SELL'}, {'quantity':Decimal(2)}, {'deployment':'foreign'},
])
def test_native_transport_requires_exact_durable_pending_command(monkeypatch,change):
    import tools.native_paper_rehearsal as module
    value=dict(state=CommandState.SEND_PENDING,key='owned',plan='current',asset='asset',
               side='BUY',quantity=Decimal(1),deployment='test-run',**{})
    value.update(change)
    run=object.__new__(NativeRun)
    run.deployment_id='test-run'
    run.keys=set()
    run.quantities={}
    @contextmanager
    def connect():yield object()
    run.connect=connect
    monkeypatch.setattr(module.binding,'require',lambda _:SimpleNamespace(deployment_id=value['deployment'],identity='bound'))
    command=SimpleNamespace(client_key=value['key'],state=value['state'],quantity=value['quantity'],
        identity=SimpleNamespace(plan_id=value['plan']),instrument=SimpleNamespace(broker_id=value['asset']),
        side=SimpleNamespace(value=value['side']))
    monkeypatch.setattr(module.journal,'load_commands',lambda *_:[command])
    monkeypatch.setattr(module.journal,'latest_plan',lambda _:SimpleNamespace(plan_id='current'))
    reached=[]
    async def authorized(*_a,**_k):reached.append(True)
    monkeypatch.setattr(AttendedRun,'authorize',authorized)
    with pytest.raises(Refused):
        asyncio.run(run.authorize_command('POST',PAPER+'/v2/orders',dict(client_order_id='owned',symbol='asset',side='buy',qty='1')))
    assert not reached
