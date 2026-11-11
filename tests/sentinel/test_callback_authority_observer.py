"""Long callback authority is checked, never inferred from its heartbeat."""
import asyncio
import inspect
import os
import sys
import threading
import time
from textwrap import dedent
from types import SimpleNamespace

import pytest

from sentinel.automation import service as module
from sentinel import automation_runtime
from sentinel.automation.model import NonRetryableCallbackRefused, TransientInfrastructureFailure
from tests.sentinel.test_automation_process_contracts import _service, _CallbackContext

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(sys.platform!='linux', reason='fork supervision')]


def setup(monkeypatch):
    monkeypatch.setattr(module, 'CALLBACK_AUTHORITY_SECONDS', .05)
    monkeypatch.setattr(module.store, 'register_instance', lambda *a, **k: None)
    monkeypatch.setattr(module.store, 'heartbeat_lease', lambda *a, **k: None)
    class Connection:
        def close(self): pass
    return Connection


async def test_complete_observations_continue_during_a_long_callback(monkeypatch):
    connection = setup(monkeypatch); checks=[]; owner=os.getpid()
    service=_service()
    def authority(context, stopped):
        assert os.getpid()==owner and not stopped.is_set()
        assert threading.current_thread().name.startswith('sentinel-callback-authority-')
        checks.append(time.monotonic())
    service.callback_authority=authority
    async def callback(context): time.sleep(.3);return {'finished': True}
    assert await service._invoke(callback, _CallbackContext(), permit=object(),
        phase='PREPARE', heartbeat_conn_factory=connection)=={'finished':True}
    assert len(checks)>=2
    assert not any(t.name.startswith('sentinel-callback-authority-') for t in threading.enumerate())


async def test_revocation_cancels_the_running_callback(monkeypatch):
    connection=setup(monkeypatch);service=_service();checks=[];context=_CallbackContext()
    def authority(context, stopped):
        checks.append(True)
        raise NonRetryableCallbackRefused('synthetic revoked certificate')
    service.callback_authority=authority
    async def callback(context):time.sleep(2);return {'unsafe success':True}
    started=time.monotonic()
    with pytest.raises(NonRetryableCallbackRefused, match='revoked'):
        await service._invoke(callback,context,permit=object(),phase='PREPARE',heartbeat_conn_factory=connection)
    assert checks==[True] and context.cancellation.cancelled
    assert time.monotonic()-started<1.5


async def test_callback_completion_cancels_its_owned_observer(monkeypatch):
    connection=setup(monkeypatch);service=_service();stopped_observer=threading.Event()
    def authority(context, stopped):
        assert stopped.wait(2)
        stopped_observer.set()
    service.callback_authority=authority
    async def callback(context):time.sleep(.2);return {'finished':True}
    await service._invoke(callback,_CallbackContext(),permit=object(),phase='PREPARE',heartbeat_conn_factory=connection)
    assert stopped_observer.is_set()


async def test_removed_authority_observer_has_executed_falsifier(monkeypatch):
    text=dedent(inspect.getsource(module.AutomationService._invoke))
    guard='if self.callback_authority is not None:'
    assert text.count(guard)==1
    namespace=dict(vars(module))
    exec(compile(text.replace(guard,'if False:'),'<removed callback authority>','exec'),namespace)
    monkeypatch.setattr(module.AutomationService,'_invoke',namespace['_invoke'])
    with pytest.raises((AssertionError, pytest.fail.Exception)):
        await test_revocation_cancels_the_running_callback(monkeypatch)


async def test_native_authority_observer_owns_connection_and_runs_the_complete_gate(monkeypatch):
    calls=[];permit=object()
    conn=SimpleNamespace(close=lambda:calls.append('closed'))
    runtime=SimpleNamespace(connect=lambda:conn,
        _assert_control_authority=lambda connection,current,**kwargs:calls.append((connection,current,kwargs)))
    monkeypatch.setattr(automation_runtime,'ProductionAutomation',lambda **kwargs:runtime)
    assert automation_runtime._observe_callback_authority('settings','policy','holder',permit)=='PASS'
    assert calls==[(conn,permit,{'require_publication':True}),'closed']


async def test_removed_complete_authority_validation_has_executed_falsifier(monkeypatch):
    text=dedent(inspect.getsource(automation_runtime._observe_callback_authority))
    guard='runtime._assert_control_authority(conn, permit, require_publication=True)'
    assert text.count(guard)==1
    namespace=dict(vars(automation_runtime));exec(compile(text.replace(guard,'pass'),'<removed complete authority check>','exec'),namespace)
    monkeypatch.setattr(automation_runtime,'_observe_callback_authority',namespace['_observe_callback_authority'])
    # The constructed function owns its globals; inject the test factory there.
    calls=[];conn=SimpleNamespace(close=lambda:calls.append('closed'))
    namespace['ProductionAutomation']=lambda **kwargs:SimpleNamespace(connect=lambda:conn,
        _assert_control_authority=lambda *args:calls.append('validated'))
    assert automation_runtime._observe_callback_authority('settings','policy','holder',object())=='PASS'
    assert calls==['closed']
    with pytest.raises(AssertionError):assert 'validated' in calls


async def test_failed_verdict_publication_cannot_report_observer_success(monkeypatch):
    from tests.sentinel.test_automation_runtime import config, context, production, control, FakeConnection, CERTIFICATE
    from sentinel.authority import RolloutMode, RolloutState
    cfg=config();ctx=context(cfg);runtime=production(cfg);conn=FakeConnection();calls=[]
    monkeypatch.setattr(automation_runtime.store,'require_leader',lambda c,p:p)
    monkeypatch.setattr(automation_runtime.store,'load_control',lambda c:control(cfg))
    monkeypatch.setattr(automation_runtime,'load_rollout_state',lambda c:RolloutState(RolloutMode.PINNED_1_00,1,None))
    monkeypatch.setattr(automation_runtime.feed_inputs,'require_current',lambda c:SimpleNamespace(version=81))
    monkeypatch.setattr(automation_runtime,'production_strategy',lambda:(object(),{'strategy':'fixture'}))
    monkeypatch.setattr(automation_runtime.system_identity,'rehearsal_identity',lambda:{'runtime':'fixture'})
    def validate(*a,**k):calls.append('validated');return SimpleNamespace(certificate_sha256=CERTIFICATE)
    def refused(*a,**k):raise ConnectionError('synthetic verdict publication failed')
    monkeypatch.setattr(automation_runtime,'require_current_authority',validate)
    monkeypatch.setattr(automation_runtime.store,'record_authority_verdict',refused)
    with pytest.raises(TransientInfrastructureFailure,match='persisted'):
        runtime._assert_control_authority(conn,ctx.permit,require_publication=True)
    assert calls==['validated']


async def test_removed_publication_requirement_has_executed_falsifier(monkeypatch):
    text=dedent(inspect.getsource(automation_runtime.ProductionAutomation._assert_control_authority))
    guard='if require_publication and not published:'
    assert text.count(guard)==1
    namespace=dict(vars(automation_runtime));exec(compile(text.replace(guard,'if False:'),'<removed verdict publication>','exec'),namespace)
    altered=namespace['_assert_control_authority']
    def invoke(self,*args,**kwargs):
        namespace.update(vars(automation_runtime))
        return altered(self,*args,**kwargs)
    monkeypatch.setattr(automation_runtime.ProductionAutomation,'_assert_control_authority',invoke)
    with pytest.raises((AssertionError,pytest.fail.Exception)):
        await test_failed_verdict_publication_cannot_report_observer_success(monkeypatch)
