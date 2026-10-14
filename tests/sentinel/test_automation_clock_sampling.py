"""Database latency must not masquerade as wall-clock drift."""
import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest

from sentinel.automation import integrity, store
from sentinel.automation.model import AutomationRefused, TickAction, TransientInfrastructureFailure
from sentinel.automation import service as module
from tests.sentinel.test_automation_service import (
    AFTER_WEDNESDAY_CLOSE, conn, pg, config, enable, service_for, recovery_success)


def sampler(monkeypatch, *, query_seconds=0, database_offset=0, host_jump=0):
    state = {'seconds': 0, 'closed': False}
    def clock():
        return AFTER_WEDNESDAY_CLOSE + timedelta(seconds=state['seconds'])
    def read(_conn):
        sampled = clock() + timedelta(seconds=database_offset)
        state['seconds'] += query_seconds + host_jump
        return sampled
    monkeypatch.setattr(integrity, 'database_now', read)
    monkeypatch.setattr(module, 'time', SimpleNamespace(monotonic=lambda: state['seconds'] - host_jump
        if state['seconds'] else 0, sleep=module.time.sleep))
    connection = SimpleNamespace(close=lambda: state.update(closed=True))
    service = service_for(config().model_copy(update={'maximum_clock_skew_seconds': 5}))
    return service, state, clock, lambda: connection


def test_connection_latency_is_excluded_and_sample_returns_fresh_schedule_time(monkeypatch):
    service, state, clock, factory = sampler(monkeypatch)
    initial = clock()
    def delayed_factory():
        state['seconds'] += 7
        return factory()
    assert service._assert_clock_skew(now=initial, conn_factory=delayed_factory, clock=clock) == clock()
    assert state['closed'] and clock() == initial + timedelta(seconds=7)


@pytest.mark.parametrize('offset', [-6, 6])
def test_fresh_sampler_still_refuses_real_drift(monkeypatch, offset):
    service, state, clock, factory = sampler(monkeypatch, database_offset=offset)
    with pytest.raises(AutomationRefused, match='clock skew'):
        service._assert_clock_skew(now=clock(), conn_factory=factory, clock=clock)
    assert state['closed']


def test_slow_query_requires_new_sample_instead_of_claiming_clock_drift(monkeypatch):
    service, state, clock, factory = sampler(monkeypatch, query_seconds=6)
    with pytest.raises(TransientInfrastructureFailure, match='precision budget'):
        service._assert_clock_skew(now=clock(), conn_factory=factory, clock=clock)
    assert state['closed']


@pytest.mark.parametrize('offset', [-4, 6])
def test_ambiguous_interval_waits_without_widening_the_skew_limit(monkeypatch, offset):
    service, state, clock, factory = sampler(monkeypatch, query_seconds=2, database_offset=offset)
    with pytest.raises(TransientInfrastructureFailure, match='cannot prove'):
        service._assert_clock_skew(now=clock(), conn_factory=factory, clock=clock)
    assert state['closed']


@pytest.mark.parametrize('jump', [-6, 6])
def test_host_clock_jump_is_refused(monkeypatch, jump):
    service, state, clock, factory = sampler(monkeypatch, host_jump=jump)
    with pytest.raises(AutomationRefused, match='clock changed'):
        service._assert_clock_skew(now=clock(), conn_factory=factory, clock=clock)
    assert state['closed']


@pytest.mark.asyncio
async def test_run_survives_uncertain_sample_then_recovers_with_no_failed_instance(conn, pg, monkeypatch):
    from sentinel.feed import store as feed_store
    cfg = config().model_copy(update={'maximum_clock_skew_seconds': 5})
    enable(conn, cfg)
    state = {'seconds': 0, 'samples': 0}
    calls = []
    clock = lambda: AFTER_WEDNESDAY_CLOSE + timedelta(seconds=state['seconds'])
    def read(_conn):
        at = clock()
        state['samples'] += 1
        if state['samples'] == 1:
            module.time.sleep(6)
            state['seconds'] += 6
        return at
    monkeypatch.setattr(integrity, 'database_now', read)
    async def recover(context):
        calls.append(context)
        return recovery_success(context)
    service = service_for(cfg, recover=recover)
    async def sleep(_duration):
        with conn.cursor() as cur:
            cur.execute('SELECT state FROM sentinel_automation_service_instances WHERE instance_id=%s',
                        (service.holder_id,))
            assert cur.fetchone()[0] == 'WAITING'
            cur.execute('SELECT count(*) FROM sentinel_automation_cycles')
            assert cur.fetchone()[0] == 0
            cur.execute('SELECT holder_id FROM sentinel_automation_lease WHERE id=1')
            assert cur.fetchone()[0] is None
        conn.rollback()
        assert not calls
    assert await service.run(lambda: feed_store.connect(pg.sync_dsn), stop=asyncio.Event(),
        clock=clock, sleep=sleep, max_ticks=2) == 2
    with conn.cursor() as cur:
        cur.execute('SELECT state,last_error FROM sentinel_automation_service_instances WHERE instance_id=%s',
                    (service.holder_id,))
        instance = cur.fetchone()
    assert state['samples'] == 2 and instance == ('RECOVERED', None)
    with conn.cursor() as cur:
        cur.execute('SELECT state FROM sentinel_automation_cycles')
        assert cur.fetchall() == [('REFRESHING_DATA',)]
        cur.execute('SELECT count(*) FROM sentinel_commands')
        assert cur.fetchone()[0] == 0
    with conn.cursor() as cur:
        cur.execute('SELECT state,last_error FROM sentinel_automation_service_instances WHERE instance_id=%s',
                    (service.holder_id,))
        assert cur.fetchone() == ('RECOVERED', None)


@pytest.mark.asyncio
async def test_control_read_delay_uses_fresh_host_sample_before_leadership(conn, pg, monkeypatch):
    from sentinel.feed import store as feed_store
    cfg = config().model_copy(update={'maximum_clock_skew_seconds': 5})
    enable(conn, cfg)
    state = {'seconds': 0}
    clock = lambda: AFTER_WEDNESDAY_CLOSE + timedelta(seconds=state['seconds'])
    original = store.load_control
    def delayed(connection, **kwargs):
        result = original(connection, **kwargs)
        state['seconds'] += 7
        return result
    monkeypatch.setattr(store, 'load_control', delayed)
    monkeypatch.setattr(integrity, 'database_now', lambda _conn: clock())
    async def recover(context):
        return recovery_success(context)
    result = await service_for(cfg, recover=recover).tick(conn, now=clock(), clock=clock,
        heartbeat_conn_factory=lambda: feed_store.connect(pg.sync_dsn))
    assert result.action is TickAction.RECOVERED


@pytest.mark.asyncio
async def test_slow_tick_keeps_a_bounded_poll_gap_instead_of_a_busy_burst(monkeypatch):
    from sentinel.automation.model import TickResult
    service=service_for(config())
    state={'seconds':0}
    sleeps=[];wakes=[]
    def clock():return AFTER_WEDNESDAY_CLOSE+timedelta(seconds=state['seconds'])
    async def tick(_conn, **kwargs):
        assert kwargs['clock'] is clock
        state['seconds']+=7
        return TickResult(action=TickAction.WAITING)
    async def sleep(seconds):sleeps.append(seconds)
    monkeypatch.setattr(service,'tick',tick)
    monkeypatch.setattr(store,'register_instance',lambda _conn,**kwargs:wakes.append(kwargs['next_wake_at']))
    await service.run(lambda:SimpleNamespace(close=lambda:None),stop=asyncio.Event(),
        clock=clock,sleep=sleep,max_ticks=2)
    assert sleeps==[5]
    assert wakes==[AFTER_WEDNESDAY_CLOSE+timedelta(seconds=x) for x in (12,19)]
