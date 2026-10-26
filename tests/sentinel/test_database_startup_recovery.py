"""Real exception classes and public loops at the two incident boundaries."""
import asyncio
import errno
import inspect
from types import SimpleNamespace

import psycopg
import pytest

from sentinel import automation_supervisor as supervisor
from sentinel.dependency_availability import database_unavailable
from sentinel.automation.model import TickAction, TickResult, TransientInfrastructureFailure
from tests.sentinel.test_automation_clock_sampling import sampler
from tests.sentinel.test_automation_service import config, service_for, AFTER_WEDNESDAY_CLOSE


@pytest.mark.parametrize('error', [psycopg.errors.ConnectionTimeout, psycopg.OperationalError,
    psycopg.InterfaceError, psycopg.errors.QueryCanceled, psycopg.errors.AdminShutdown])
def test_real_database_availability_classes(error):
    assert database_unavailable(error('injected database outage'))


@pytest.mark.parametrize('error', [psycopg.ProgrammingError, psycopg.IntegrityError,
                                 ValueError, PermissionError])
def test_unknown_or_integrity_failures_are_not_retries(error):
    assert not database_unavailable(error('permanent failure'))


def test_connection_failure_cannot_invent_a_clock_sample(monkeypatch):
    service, state, clock, factory = sampler(monkeypatch)
    def failed(): raise psycopg.errors.ConnectionTimeout('injected connection timeout')
    with pytest.raises(TransientInfrastructureFailure, match='fresh database clock unavailable'):
        service._assert_clock_skew(now=clock(), conn_factory=failed, clock=clock)
    assert not state['closed'] and not state['sampling']


def test_clock_programming_error_still_escapes(monkeypatch):
    service, state, clock, factory = sampler(monkeypatch)
    def failed(): raise psycopg.ProgrammingError('bad query')
    with pytest.raises(psycopg.ProgrammingError):
        service._assert_clock_skew(now=clock(), conn_factory=failed, clock=clock)


@pytest.mark.asyncio
async def test_main_connection_outage_waits_then_uses_a_fresh_connection(monkeypatch):
    service = service_for(config())
    attempts=[]; sleeps=[]; ticks=[]
    connection=SimpleNamespace(close=lambda:None)
    def connect():
        attempts.append(True)
        if len(attempts)<=3: raise psycopg.errors.ConnectionTimeout('injected main connection outage')
        return connection
    async def tick(conn, **kwargs):
        assert conn is connection
        ticks.append(True)
        return TickResult(action=TickAction.WAITING)
    async def sleep(seconds):
        assert not ticks
        sleeps.append(seconds)
    monkeypatch.setattr(service,'tick',tick)
    monkeypatch.setattr(service,'_record_main_progress',lambda *a,**k:None)
    from sentinel.automation import store
    monkeypatch.setattr(store,'register_instance',lambda *a,**k:None)
    assert await service.run(connect,stop=asyncio.Event(),clock=lambda:AFTER_WEDNESDAY_CLOSE,
        sleep=sleep,max_ticks=1)==1
    assert len(attempts)==4 and len(ticks)==1 and sleeps==[5,5,5]


@pytest.mark.asyncio
async def test_main_connection_programming_error_is_fatal():
    def connect(): raise psycopg.ProgrammingError('invalid DSN usage')
    with pytest.raises(psycopg.ProgrammingError):
        await service_for(config()).run(connect,stop=asyncio.Event(),
            clock=lambda:AFTER_WEDNESDAY_CLOSE,max_ticks=1)


class Launched(Exception): pass


@pytest.mark.parametrize('error',[TimeoutError('bounded holder timeout'),
    OSError(errno.EAGAIN,'resource unavailable'),OSError(errno.ENOMEM,'resource unavailable')])
def test_public_supervisor_retries_failed_launch_then_recovers(monkeypatch,error):
    monkeypatch.setattr(supervisor.SentinelConfig,'from_env',lambda:SimpleNamespace(database_url='private'))
    monkeypatch.setattr(supervisor,'config_from_env',lambda:object())
    monkeypatch.setattr(supervisor.signal,'signal',lambda *a:None)
    monkeypatch.setattr(supervisor.supervisor_io,'report',lambda *a,**k:None)
    monkeypatch.delenv('SENTINEL_AUTOMATION_SUPERVISOR_POLL_SECONDS',raising=False)
    calls=[]; pauses=[]
    def spawn(holder):
        calls.append(holder)
        if len(calls)<=3:raise error
        raise Launched
    monkeypatch.setattr(supervisor,'_spawn',spawn)
    monkeypatch.setattr(supervisor.time,'sleep',pauses.append)
    with pytest.raises(Launched):supervisor.main()
    assert len(set(calls))==4 and pauses==[1,1,1]


@pytest.mark.parametrize('error',[PermissionError('denied'),ValueError('bad launch'),
                                 FileNotFoundError('missing runtime')])
def test_supervisor_does_not_hide_permanent_launch_failures(monkeypatch,error):
    monkeypatch.setattr(supervisor.SentinelConfig,'from_env',lambda:SimpleNamespace(database_url='private'))
    monkeypatch.setattr(supervisor,'config_from_env',lambda:object())
    monkeypatch.setattr(supervisor.signal,'signal',lambda *a:None)
    monkeypatch.setattr(supervisor,'_spawn',lambda *a:(_ for _ in ()).throw(error))
    monkeypatch.setattr(supervisor.time,'sleep',lambda *a:pytest.fail('permanent failure retried'))
    with pytest.raises(type(error)):supervisor.main()


def test_removing_database_classifier_is_detected(monkeypatch):
    import sentinel.dependency_availability as module
    monkeypatch.setattr(module,'database_unavailable',lambda exc:False)
    with pytest.raises(psycopg.errors.ConnectionTimeout):
        test_connection_failure_cannot_invent_a_clock_sample(monkeypatch)


def test_stop_during_failed_replacement_cannot_target_a_reaped_session(monkeypatch):
    handlers={}; attempts=[]; killed=[]; pauses=[]
    old=SimpleNamespace(pid=12345,poll=lambda:0)
    monkeypatch.setattr(supervisor.SentinelConfig,'from_env',lambda:SimpleNamespace(database_url='private'))
    monkeypatch.setattr(supervisor,'config_from_env',lambda:object())
    monkeypatch.setattr(supervisor.signal,'signal',lambda n,handler:handlers.setdefault(n,handler))
    monkeypatch.setattr(supervisor.supervisor_io,'report',lambda *a,**k:None)
    monkeypatch.setattr(supervisor.supervisor_io,'run',lambda *a,**k:None)
    monkeypatch.setattr(supervisor,'_terminate',lambda child:killed.append(child.pid))
    def spawn(holder):
        attempts.append(holder)
        if len(attempts)==1:return old
        raise TimeoutError('replacement holder unavailable')
    def pause(seconds):
        pauses.append(seconds)
        if len(pauses)==2:handlers[supervisor.signal.SIGTERM](None,None)
    monkeypatch.setattr(supervisor,'_spawn',spawn)
    monkeypatch.setattr(supervisor.time,'sleep',pause)
    assert supervisor.main()==0
    assert len(attempts)==2 and killed==[12345]


def test_stale_process_identity_guard_has_a_falsifier(monkeypatch):
    raw=inspect.getsource(supervisor.main)
    needle='        child = None\n'
    assert raw.count(needle)==1
    namespace={}
    exec(compile(raw.replace(needle,''),'<removed stale session guard>','exec'),
        supervisor.main.__globals__,namespace)
    monkeypatch.setattr(supervisor,'main',namespace['main'])
    with pytest.raises(AssertionError):
        test_stop_during_failed_replacement_cannot_target_a_reaped_session(monkeypatch)
