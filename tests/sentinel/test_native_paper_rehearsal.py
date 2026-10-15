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
        asyncio.run(run.authorize('POST',PAPER+'/v2/orders',dict(client_order_id='owned',symbol='asset',side='buy',qty='1')))
    assert not reached
