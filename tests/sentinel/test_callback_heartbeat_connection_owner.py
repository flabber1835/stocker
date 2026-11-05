"""Lease renewal owns one connection, independently of callback work."""
import asyncio
import inspect
import os
import re
import sys
import threading
import time
from textwrap import dedent

import pytest

from sentinel.automation import service as module
from sentinel.automation.model import StaleLeaderRefused
from tests.sentinel.test_automation_process_contracts import _service, _CallbackContext

pytestmark = [pytest.mark.asyncio,
              pytest.mark.skipif(sys.platform != 'linux', reason='requires fork supervision')]


async def test_renewals_do_not_reopen_an_owned_connection(monkeypatch):
    connections=[];renewals=[];parent=os.getpid()
    class Connection:
        def __init__(self):
            self.closed=0;self.pid=os.getpid();self.thread=threading.current_thread().name
        def close(self):self.closed+=1
    def factory():
        if len(connections)>=2:raise TimeoutError('synthetic repeated connection startup timeout')
        c=Connection();connections.append(c);return c
    def renew(c,**kwargs):
        assert c is connections[1] and c.closed==0 and c.pid==parent
        assert kwargs['callback'] is True;renewals.append(c)
    monkeypatch.setattr(module.store,'register_instance',lambda *a,**k:None)
    monkeypatch.setattr(module.store,'heartbeat_lease',renew)
    async def callback(context):
        assert os.getpid()!=parent and len(connections)==1 and connections[0].closed==1
        time.sleep(3.2);context.require_active();return {'completed':True}
    assert await _service()._invoke(callback,_CallbackContext(),permit=object(),phase='PREPARE',
        heartbeat_conn_factory=factory)=={'completed':True}
    assert len(connections)==2 and len(renewals)>=2
    assert connections[1].thread.startswith('sentinel-heartbeat-')
    assert all(c.closed==1 for c in connections)


@pytest.mark.parametrize('boundary',['connect','renew','close'])
async def test_owned_connection_failures_still_refuse_success(monkeypatch,boundary):
    connections=[];calls=[]
    class Connection:
        def __init__(self):self.closed=0
        def close(self):
            self.closed+=1
            if boundary=='close' and self is connections[-1] and len(connections)==2:
                raise RuntimeError('synthetic owned connection cleanup failure')
    def factory():
        if boundary=='connect' and connections:raise TimeoutError('synthetic first connection failure')
        c=Connection();connections.append(c);return c
    def renew(c,**kwargs):
        calls.append(c)
        if boundary=='renew':raise StaleLeaderRefused('synthetic fence lost')
    monkeypatch.setattr(module.store,'register_instance',lambda *a,**k:None)
    monkeypatch.setattr(module.store,'heartbeat_lease',renew)
    context=_CallbackContext()
    async def callback(context):time.sleep(1.4 if boundary=='close' else 3);return {'completed':True}
    with pytest.raises(StaleLeaderRefused):
        await _service()._invoke(callback,context,permit=object(),phase='PREPARE',heartbeat_conn_factory=factory)
    assert context.cancellation.cancelled and all(c.closed==1 for c in connections)
    assert len(calls)<=1


async def test_callback_cancellation_closes_the_owned_connection(monkeypatch):
    connections=[]
    class Connection:
        def __init__(self):self.closed=0;connections.append(self)
        def close(self):self.closed+=1
    monkeypatch.setattr(module.store,'register_instance',lambda *a,**k:None)
    monkeypatch.setattr(module.store,'heartbeat_lease',lambda *a,**k:None)
    async def callback(context):time.sleep(4);return {'completed':True}
    task=asyncio.create_task(_service()._invoke(callback,_CallbackContext(),permit=object(),phase='PREPARE',heartbeat_conn_factory=Connection))
    await asyncio.sleep(1.3);task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    assert len(connections)==2 and all(c.closed==1 for c in connections)


async def test_removed_connection_reuse_has_executed_falsifier(monkeypatch):
    text=dedent(inspect.getsource(module.AutomationService._invoke))
    guard=re.search(r'if heartbeat_conn is None:\n\s+heartbeat_conn = heartbeat_conn_factory\(\)',text).group()
    assert text.count(guard)==1
    namespace=dict(vars(module));exec(compile(text.replace(guard,guard.replace('if heartbeat_conn is None:','if True:')),'<removed heartbeat reuse>','exec'),namespace)
    monkeypatch.setattr(module.AutomationService,'_invoke',namespace['_invoke'])
    with pytest.raises((StaleLeaderRefused,AssertionError)):
        await test_renewals_do_not_reopen_an_owned_connection(monkeypatch)
