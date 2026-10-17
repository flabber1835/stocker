"""Database latency must not masquerade as wall-clock drift."""
import asyncio
import json
import math
from datetime import timedelta
from types import SimpleNamespace

import pytest

from sentinel.automation import integrity, store
from sentinel.automation.model import AutomationRefused, TickAction, TransientInfrastructureFailure
from sentinel.automation import service as module
from tests.sentinel.test_automation_service import (
    AFTER_WEDNESDAY_CLOSE, conn, pg, config, enable, service_for, recovery_success)


def sampler(monkeypatch, *, query_seconds=0, database_offset=0, host_jump=0,
            wall_pause=None, close_seconds=0, monotonic_readings=None):
    state = {'seconds': 0, 'monotonic_seconds': 0, 'closed': False,
             'sampling': False, 'wall_reads': 0}
    def advance(seconds):
        state['seconds'] += seconds
        state['monotonic_seconds'] += seconds
    def clock():
        if state['sampling']:
            state['wall_reads'] += 1
            if wall_pause == (state['wall_reads'], 'before'):
                advance(6)
        result = AFTER_WEDNESDAY_CLOSE + timedelta(seconds=state['seconds'])
        if state['sampling'] and wall_pause == (state['wall_reads'], 'after'):
            advance(6)
        return result
    def read(_conn):
        sampled = AFTER_WEDNESDAY_CLOSE + timedelta(
            seconds=state['seconds'] + database_offset)
        state['seconds'] += query_seconds + host_jump
        state['monotonic_seconds'] += query_seconds
        return sampled
    monkeypatch.setattr(integrity, 'database_now', read)
    readings = iter(monotonic_readings) if monotonic_readings is not None else None
    monkeypatch.setattr(module, 'time', SimpleNamespace(
        monotonic=(lambda: next(readings)) if readings is not None else
        lambda: state['monotonic_seconds'], sleep=module.time.sleep))
    def close():
        state['closed'] = True
        advance(close_seconds)
    connection = SimpleNamespace(close=close)
    def factory():
        state['sampling'] = True
        return connection
    service = service_for(config().model_copy(update={'maximum_clock_skew_seconds': 5}))
    return service, state, clock, factory


def sample_diagnostic(exc):
    diagnostic = json.loads(str(exc).split('; clock_sample=', 1)[1])
    assert set(diagnostic) == {
        'schema', 'reason', 'classification', 'limit_seconds', 'host_before', 'host_after',
        'database_now', 'monotonic', 'inner_seconds', 'outer_seconds',
        'wall_seconds', 'jump_lower_seconds', 'jump_upper_seconds',
        'proven_skew_seconds'}
    assert diagnostic['limit_seconds'] == 5
    assert diagnostic['schema'] == 'sentinel.automation-clock-sample/1'
    assert diagnostic['classification'] in {'UNCERTAIN', 'REFUSED'}
    assert len(diagnostic['monotonic']) == 4
    def finite(value):
        if isinstance(value, dict):
            return all(finite(item) for item in value.values())
        if isinstance(value, list):
            return all(finite(item) for item in value)
        return not isinstance(value, float) or math.isfinite(value)
    assert finite(diagnostic)
    return diagnostic


def test_connection_latency_is_excluded_and_sample_returns_fresh_schedule_time(monkeypatch):
    service, state, clock, factory = sampler(monkeypatch)
    initial = clock()
    def delayed_factory():
        state['seconds'] += 7
        state['monotonic_seconds'] += 7
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


@pytest.mark.parametrize('jump', [-0.0016, 0.0016])
def test_millisecond_wall_adjustment_is_uncertain_instead_of_fatal(monkeypatch, jump, caplog):
    service, state, clock, factory = sampler(monkeypatch, host_jump=jump)
    with pytest.raises(TransientInfrastructureFailure) as caught:
        service._assert_clock_skew(now=clock(), conn_factory=factory, clock=clock)
    diagnostic = sample_diagnostic(caught.value)
    assert diagnostic['wall_seconds'] == pytest.approx(jump)
    assert diagnostic['inner_seconds'] == diagnostic['outer_seconds'] == 0
    assert diagnostic['jump_lower_seconds'] == diagnostic['jump_upper_seconds'] == pytest.approx(jump)
    log = next(record for record in caplog.records
               if record.name == module.__name__ and record.message.startswith('automation_clock_sample='))
    assert log.levelname == 'WARNING'
    assert json.loads(log.message.split('=', 1)[1]) == diagnostic
    assert state['closed']


@pytest.mark.parametrize('edge', [(1, 'before'), (1, 'after'), (2, 'before'), (2, 'after')])
def test_wall_read_scheduling_pause_is_precision_uncertainty(monkeypatch, edge):
    service, state, clock, factory = sampler(monkeypatch, wall_pause=edge)
    with pytest.raises(TransientInfrastructureFailure, match='precision budget') as caught:
        service._assert_clock_skew(now=clock(), conn_factory=factory, clock=clock)
    diagnostic = sample_diagnostic(caught.value)
    assert diagnostic['outer_seconds'] == 6
    assert diagnostic['inner_seconds'] == 0
    assert diagnostic['jump_lower_seconds'] <= 0 <= diagnostic['jump_upper_seconds']
    assert state['closed']


def test_connection_cleanup_pause_is_inside_the_uncertainty_bracket(monkeypatch):
    service, state, clock, factory = sampler(monkeypatch, close_seconds=6)
    with pytest.raises(TransientInfrastructureFailure, match='precision budget') as caught:
        service._assert_clock_skew(now=clock(), conn_factory=factory, clock=clock)
    diagnostic = sample_diagnostic(caught.value)
    assert diagnostic['outer_seconds'] == diagnostic['wall_seconds'] == 6
    assert diagnostic['inner_seconds'] == 0
    assert state['closed']


def test_sampling_precision_limit_is_inclusive_without_success_log_noise(monkeypatch, caplog):
    service, state, clock, factory = sampler(monkeypatch, query_seconds=5)
    assert service._assert_clock_skew(now=clock(), conn_factory=factory, clock=clock) == clock()
    assert state['closed']
    assert not [record for record in caplog.records if record.name == module.__name__]


def test_sample_just_beyond_precision_limit_waits(monkeypatch):
    service, state, clock, factory = sampler(monkeypatch, query_seconds=5.000001)
    with pytest.raises(TransientInfrastructureFailure, match='precision budget') as caught:
        service._assert_clock_skew(now=clock(), conn_factory=factory, clock=clock)
    assert sample_diagnostic(caught.value)['outer_seconds'] == pytest.approx(5.000001)
    assert state['closed']


def test_wide_sample_waits_even_when_database_is_between_safe_endpoints(monkeypatch):
    service, state, clock, factory = sampler(monkeypatch, query_seconds=6, database_offset=3)
    with pytest.raises(TransientInfrastructureFailure, match='precision budget'):
        service._assert_clock_skew(now=clock(), conn_factory=factory, clock=clock)
    assert state['closed']


@pytest.mark.parametrize('offset', [-5, 5])
def test_exact_database_skew_limit_is_not_widened_or_rejected(monkeypatch, offset):
    service, state, clock, factory = sampler(monkeypatch, database_offset=offset)
    assert service._assert_clock_skew(now=clock(), conn_factory=factory, clock=clock) == clock()
    assert state['closed']


@pytest.mark.parametrize('offset', [-5.000001, 5.000001])
def test_database_skew_just_beyond_limit_remains_fatal(monkeypatch, offset, caplog):
    service, state, clock, factory = sampler(monkeypatch, database_offset=offset)
    with pytest.raises(AutomationRefused, match='clock skew') as caught:
        service._assert_clock_skew(now=clock(), conn_factory=factory, clock=clock)
    diagnostic = sample_diagnostic(caught.value)
    assert diagnostic['proven_skew_seconds'] == pytest.approx(abs(offset))
    log = next(record for record in caplog.records
               if record.name == module.__name__ and record.message.startswith('automation_clock_sample='))
    assert log.levelname == 'ERROR'
    assert json.loads(log.message.split('=', 1)[1]) == diagnostic
    assert state['closed']


@pytest.mark.parametrize('jump', [-5, 5])
def test_exact_host_jump_limit_is_uncertain_not_proven_excessive(monkeypatch, jump):
    service, state, clock, factory = sampler(monkeypatch, host_jump=jump)
    with pytest.raises(TransientInfrastructureFailure) as caught:
        service._assert_clock_skew(now=clock(), conn_factory=factory, clock=clock)
    diagnostic = sample_diagnostic(caught.value)
    assert diagnostic['jump_lower_seconds'] == diagnostic['jump_upper_seconds'] == jump
    assert state['closed']


@pytest.mark.parametrize('position', range(4))
@pytest.mark.parametrize('invalid', [float('nan'), float('inf'), -float('inf')])
def test_nonfinite_monotonic_reading_is_fatal_with_finite_diagnostics(monkeypatch, position, invalid):
    readings = [0.0] * 4
    readings[position] = invalid
    service, state, clock, factory = sampler(monkeypatch, monotonic_readings=readings)
    with pytest.raises(AutomationRefused, match='monotonic clock invariant') as caught:
        service._assert_clock_skew(now=clock(), conn_factory=factory, clock=clock)
    diagnostic = sample_diagnostic(caught.value)
    assert diagnostic['monotonic'][position] is None
    assert state['closed']


@pytest.mark.parametrize('readings', [(1, 0, 1, 1), (0, 1, 0, 1), (0, 0, 1, 0)])
def test_any_reversed_monotonic_pair_is_fatal(monkeypatch, readings):
    service, state, clock, factory = sampler(monkeypatch, monotonic_readings=readings)
    with pytest.raises(AutomationRefused, match='monotonic clock invariant') as caught:
        service._assert_clock_skew(now=clock(), conn_factory=factory, clock=clock)
    assert sample_diagnostic(caught.value)['monotonic'] == list(readings)
    assert state['closed']


@pytest.mark.parametrize('offset', [-6, -5, 5, 6])
def test_explicit_fixed_clock_callers_keep_strict_database_comparison(monkeypatch, offset):
    service, state, clock, factory = sampler(monkeypatch, database_offset=offset)
    if abs(offset) > 5:
        with pytest.raises(AutomationRefused, match='clock skew'):
            service._assert_clock_skew(now=clock(), conn_factory=factory)
    else:
        assert service._assert_clock_skew(now=clock(), conn_factory=factory) == clock()
    assert state['closed']


@pytest.mark.asyncio
@pytest.mark.parametrize('uncertainty', ['slow_query', 'wall_step', 'wall_pause'])
async def test_run_survives_uncertain_sample_then_recovers_with_no_failed_instance(conn, pg, monkeypatch, uncertainty, tmp_path):
    from sentinel.feed import store as feed_store
    cfg = config().model_copy(update={'maximum_clock_skew_seconds': 5})
    enable(conn, cfg)
    state = {'seconds': 0, 'monotonic_seconds': 0, 'samples': 0,
             'connections': 0, 'wall_pause_pending': False}
    callback_marker = tmp_path / 'callback-phases.txt'
    sleeps = []
    def advance(seconds):
        state['seconds'] += seconds
        state['monotonic_seconds'] += seconds
    def clock():
        value = AFTER_WEDNESDAY_CLOSE + timedelta(seconds=state['seconds'])
        if state['wall_pause_pending']:
            state['wall_pause_pending'] = False
            advance(6)
        return value
    def connect():
        state['connections'] += 1
        if (uncertainty == 'wall_pause' and state['samples'] < 2
                and state['connections'] % 2 == 0):
            state['wall_pause_pending'] = True
        return feed_store.connect(pg.sync_dsn)
    def read(_conn):
        at = AFTER_WEDNESDAY_CLOSE + timedelta(seconds=state['seconds'])
        state['samples'] += 1
        if state['samples'] <= 2:
            if uncertainty == 'slow_query':
                advance(6)
            elif uncertainty == 'wall_step':
                state['seconds'] -= 0.0016
        return at
    monkeypatch.setattr(integrity, 'database_now', read)
    monkeypatch.setattr(module, 'time', SimpleNamespace(
        monotonic=lambda: state['monotonic_seconds'], sleep=module.time.sleep))
    def mark(phase):
        with callback_marker.open('a') as handle:
            handle.write(phase + '\n')
    async def unexpected(context):
        mark('UNEXPECTED')
        raise AssertionError('financial callback ran before a valid clock sample')
    async def recover(context):
        mark('RECOVER')
        return recovery_success(context)
    service = service_for(cfg, recover=recover, refresh=unexpected,
                          prepare=unexpected, execute=unexpected)
    async def sleep(duration):
        sleeps.append(duration)
        with conn.cursor() as cur:
            cur.execute('SELECT state FROM sentinel_automation_service_instances WHERE instance_id=%s',
                        (service.holder_id,))
            assert cur.fetchone()[0] == 'WAITING'
            cur.execute('SELECT count(*) FROM sentinel_automation_cycles')
            assert cur.fetchone()[0] == 0
            cur.execute('SELECT holder_id FROM sentinel_automation_lease WHERE id=1')
            assert cur.fetchone()[0] is None
            cur.execute('SELECT count(*) FROM sentinel_commands')
            assert cur.fetchone()[0] == 0
        conn.rollback()
        assert not callback_marker.exists()
        advance(duration)
    assert await service.run(connect, stop=asyncio.Event(),
        clock=clock, sleep=sleep, max_ticks=3) == 3
    with conn.cursor() as cur:
        cur.execute('SELECT state,last_error FROM sentinel_automation_service_instances WHERE instance_id=%s',
                    (service.holder_id,))
        instance = cur.fetchone()
    assert state['samples'] == 3 and instance == ('RECOVERED', None)
    assert sleeps == [5, 5]
    assert callback_marker.read_text() == 'RECOVER\n'
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
    monkeypatch.setattr(module, 'time', SimpleNamespace(
        monotonic=lambda: state['seconds'], sleep=module.time.sleep))
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
