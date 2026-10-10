"""Callback protocol and cleanup outcomes, including failures before OS ownership.

OS doubles here prohibit any real signal or process-group change. The existing
real-process suites independently verify killing, deadlines and heartbeat loss.
"""
import asyncio
import errno
import json
import multiprocessing
import signal
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from sentinel.automation import service as module
from sentinel.automation.model import (
    AutomationConfig, CancellationAuthority, ControlBinding, PermanentOperationalRefusal,
    SoftwareDefect, TransientInfrastructureFailure,
)


class Context:
    def __init__(self):
        self.cancellation = CancellationAuthority()

    def require_active(self):
        self.cancellation.require_active()


class Channel:
    def __init__(self, *, failures=0):
        self.failures = failures
        self.attempts = 0
        self.payloads = []
        self.closed = False

    def send_bytes(self, value):
        self.attempts += 1
        if self.attempts <= self.failures:
            raise OSError('injected channel failure')
        self.payloads.append(value)

    def close(self):
        self.closed = True


class Ready:
    def __init__(self, value=False):
        self.value = value

    def set(self):
        self.value = True

    def is_set(self):
        return self.value


def child(monkeypatch, callback, *, channel=None):
    calls = []
    ready = Ready()
    monkeypatch.setattr(module.os, 'setpgid',
                        lambda pid, group: calls.append(('group', pid, group)))
    monkeypatch.setattr(module, '_arm_parent_death_sigkill',
                        lambda pid: calls.append(('parent', pid)))
    channel = channel or Channel()
    module._callback_child(callback, Context(), channel, 123, ready)
    assert calls == [('group', 0, 0), ('parent', 123)]
    assert ready.is_set() and channel.closed
    return channel


class Tag(Enum):
    OBSERVED = 'observed'


class Observation(BaseModel):
    status: str


def test_child_serializes_model_and_nested_protocol_values(monkeypatch):
    async def callback(_context):
        return {'when': datetime(2026, 1, 1, tzinfo=timezone.utc),
                'tag': Tag.OBSERVED, 'observation': Observation(status='clean')}

    channel = child(monkeypatch, callback)
    assert module._decode_child_callback(channel.payloads[0]) == {
        'when': '2026-01-01T00:00:00+00:00', 'tag': 'observed',
        'observation': {'status': 'clean'}}
    assert channel.attempts == 1


def test_child_serializes_top_level_model(monkeypatch):
    async def callback(_context):
        return Observation(status='clean')

    channel = child(monkeypatch, callback)
    assert module._decode_child_callback(channel.payloads[0]) == {'status': 'clean'}


@pytest.mark.parametrize('exception', [
    PermanentOperationalRefusal('explicit refusal'),
    RuntimeError('unknown programming failure'), SystemExit('stop'),
    KeyboardInterrupt('interrupted'),
    TransientInfrastructureFailure('temporary', retry_after_seconds=17),
])
def test_child_error_protocol_preserves_failure_not_success(monkeypatch, exception):
    async def callback(_context):
        raise exception

    channel = child(monkeypatch, callback)
    expected = SoftwareDefect if type(exception) is RuntimeError else type(exception)
    with pytest.raises(expected) as failure:
        module._decode_child_callback(channel.payloads[0])
    assert str(exception) in str(failure.value)
    assert json.loads(channel.payloads[0])['kind'] == 'error'
    if isinstance(exception, TransientInfrastructureFailure):
        assert failure.value.retry_after_seconds == 17


def test_unserializable_result_is_a_software_defect_not_authority(monkeypatch):
    async def callback(_context):
        return {'not_json': object()}

    channel = child(monkeypatch, callback)
    with pytest.raises(SoftwareDefect, match='IPC serialization failed: TypeError'):
        module._decode_child_callback(channel.payloads[0])


@pytest.mark.parametrize('failures', [1, 2])
def test_channel_failure_attempts_one_typed_fallback_and_always_closes(
        monkeypatch, failures):
    callback_calls = []

    async def callback(_context):
        callback_calls.append('one attempt')
        return {'ok': True}

    channel = child(monkeypatch, callback, channel=Channel(failures=failures))
    assert callback_calls == ['one attempt']
    assert channel.attempts == 2
    if failures == 1:
        with pytest.raises(SoftwareDefect, match='injected channel failure'):
            module._decode_child_callback(channel.payloads[0])
    else:
        assert channel.payloads == []


@pytest.mark.parametrize('delay', [True, '1', None, -1, float('nan'), float('inf')])
def test_child_cannot_inject_invalid_retry_delay(delay):
    error = TransientInfrastructureFailure
    envelope = {'kind': 'error', 'reviewed': True, 'module': error.__module__,
                'qualname': error.__qualname__, 'retry_after_seconds': delay}
    with pytest.raises(SoftwareDefect, match='invalid retry delay'):
        module._decode_child_callback(json.dumps(envelope).encode())


@pytest.mark.parametrize('platform', ['win32', 'darwin'])
def test_parent_death_non_linux_does_not_call_linux_or_signal(monkeypatch, platform):
    monkeypatch.setattr(module.sys, 'platform', platform)
    monkeypatch.setattr(module.ctypes, 'CDLL', lambda *a, **k: pytest.fail('Linux API'))
    monkeypatch.setattr(module.os, 'kill', lambda *a: pytest.fail('unexpected signal'))
    module._arm_parent_death_sigkill(123)


@pytest.mark.parametrize('outcome', ['owned', 'parent_lost', 'prctl_failed'])
def test_parent_death_arms_exact_parent_and_refuses_kernel_failure(monkeypatch, outcome):
    calls = []
    monkeypatch.setattr(module.sys, 'platform', 'linux')

    def prctl(*args):
        calls.append(('prctl', args))
        return -1 if outcome == 'prctl_failed' else 0

    monkeypatch.setattr(module.ctypes, 'CDLL',
                        lambda *a, **k: SimpleNamespace(prctl=prctl))
    monkeypatch.setattr(module.ctypes, 'get_errno', lambda: errno.EPERM)
    monkeypatch.setattr(module.os, 'getppid',
                        lambda: 124 if outcome == 'parent_lost' else 123)
    monkeypatch.setattr(module.os, 'getpid', lambda: 456)
    monkeypatch.setattr(module.os, 'kill', lambda *args: calls.append(('kill', args)))
    if outcome == 'prctl_failed':
        with pytest.raises(OSError, match='PR_SET_PDEATHSIG failed') as failure:
            module._arm_parent_death_sigkill(123)
        assert failure.value.errno == errno.EPERM
    else:
        module._arm_parent_death_sigkill(123)
    assert calls[0] == ('prctl', (1, signal.SIGKILL, 0, 0, 0))
    assert calls[1:] == ([('kill', (456, signal.SIGKILL))]
                         if outcome == 'parent_lost' else [])


def test_constructed_unstarted_callback_owns_no_pid_and_needs_no_join():
    process = multiprocessing.Process(target=lambda: None)
    assert process.pid is None
    module._kill_callback_process(process)
    assert process.pid is None and process.exitcode is None
    process.close()


def test_failed_callback_start_preserves_original_failure_and_closes_both_pipes(
        monkeypatch):
    """Fork failure owns no process, but it still owns both IPC endpoints."""
    failure = OSError(errno.EAGAIN, 'injected fork resource refusal')
    process = multiprocessing.Process(target=lambda: None)
    parent_channel, child_channel = Channel(), Channel()
    heartbeat_connection = SimpleNamespace(close=lambda: closed.append('heartbeat'))
    closed = []
    callbacks = []

    def failed_start():
        raise failure

    async def callback(_context):
        callbacks.append('must not run')

    monkeypatch.setattr(process, 'start', failed_start)
    process_context = SimpleNamespace(
        Event=Ready, Pipe=lambda **kwargs: (parent_channel, child_channel),
        Process=lambda **kwargs: process)
    monkeypatch.setattr(module.multiprocessing, 'get_context',
                        lambda method: process_context)
    monkeypatch.setattr(module.store, 'register_instance', lambda *a, **k: None)
    monkeypatch.setattr(module.os, 'killpg', lambda *a: pytest.fail('unowned group'))
    service = module.AutomationService(
        config=AutomationConfig(), holder_id='failed-fork-test',
        refresh=callback, prepare=callback, recover=callback, execute=callback)
    with pytest.raises(OSError) as actual:
        asyncio.run(service._invoke(
            callback, Context(), permit=None, phase='PREPARE',
            heartbeat_conn_factory=lambda: heartbeat_connection))
    assert actual.value is failure
    assert closed == ['heartbeat']
    assert parent_channel.closed and child_channel.closed
    assert not callbacks and process.pid is None
    process.close()


class Process:
    pid = 12345

    def __init__(self, *, ready=False, alive=True, survives=False):
        self._sentinel_process_group_ready = Ready(ready)
        self.alive = alive
        self.survives = survives
        self.kills = 0
        self.joins = []

    def kill(self):
        self.kills += 1
        if not self.survives:
            self.alive = False

    def join(self, *, timeout):
        self.joins.append(timeout)

    def is_alive(self):
        return self.alive


@pytest.mark.parametrize('alive', [False, True])
def test_unready_group_cleanup_kills_only_its_actual_process(monkeypatch, alive):
    process = Process(alive=alive)
    monkeypatch.setattr(module.os, 'killpg', lambda *args: pytest.fail('unowned group'))
    module._kill_callback_process(process, join_seconds=.02)
    assert process.kills == int(alive)
    assert process.joins == [.02]
    assert not process.is_alive()


def test_surviving_callback_is_refused_after_bounded_join(monkeypatch):
    process = Process(survives=True)
    monkeypatch.setattr(module.os, 'killpg', lambda *args: pytest.fail('unowned group'))
    with pytest.raises(SoftwareDefect, match='could not be killed'):
        module._kill_callback_process(process, join_seconds=.02)
    assert process.kills == 1 and process.joins == [.02]


def test_ready_group_cleanup_cannot_signal_another_group(monkeypatch):
    process = Process(ready=True, alive=False)
    calls = []

    def killpg(pid, sig):
        calls.append((pid, sig))
        raise ProcessLookupError('group is already absent')

    monkeypatch.setattr(module.os, 'killpg', killpg)
    module._kill_callback_process(process, join_seconds=.02)
    assert calls == [(12345, signal.SIGKILL), (12345, 0)]
    assert process.joins == [.02]


def test_group_reaping_poll_is_bounded_even_when_group_persists(monkeypatch):
    process = Process(ready=True, alive=False)
    instants = iter([0., .01, .03])
    calls = []
    monkeypatch.setattr(module.time, 'monotonic', lambda: next(instants))
    monkeypatch.setattr(module.time, 'sleep', lambda seconds: calls.append(('sleep', seconds)))
    monkeypatch.setattr(module.os, 'killpg', lambda *args: calls.append(('signal', args)))
    module._kill_callback_process(process, join_seconds=.02)
    assert calls == [('signal', (12345, signal.SIGKILL)), ('signal', (12345, 0)),
                     ('sleep', .01)]
    assert process.joins == [.02]


def test_late_background_task_observer_failure_cannot_escape_cleanup():
    task = SimpleNamespace(cancelled=lambda: False,
                           exception=lambda: (_ for _ in ()).throw(RuntimeError('observer failed')))
    assert module._consume_background_result(task) is None


def test_naive_clock_and_empty_holder_are_refused_before_callbacks():
    with pytest.raises(ValueError, match='timezone-aware'):
        module._utc(datetime(2026, 1, 1))
    with pytest.raises(ValueError, match='holder_id'):
        module.AutomationService(config=AutomationConfig(), holder_id='',
                                 refresh=None, prepare=None, recover=None, execute=None)


@pytest.mark.parametrize('exception,category', [
    (module.DataIntegrityFailure('data invalid'), 'DATA_INTEGRITY'),
    (module.HumanInterventionRequired('manual boundary'), 'HUMAN_INTERVENTION_REQUIRED'),
    (SoftwareDefect('contract broken'), 'SOFTWARE_DEFECT'),
    (module.NonRetryableCallbackRefused('unsupported callback'), 'PERMANENT_OPERATIONAL_REFUSAL'),
    (PermanentOperationalRefusal('explicit refusal'), 'PERMANENT_OPERATIONAL_REFUSAL'),
    (OSError(errno.EIO, 'unreviewed failure'), 'SOFTWARE_DEFECT'),
])
def test_failure_classification_never_retries_unreviewed_or_permanent_failure(
        exception, category):
    service = module.AutomationService(config=AutomationConfig(), holder_id='failure-contract',
                                      refresh=None, prepare=None, recover=None, execute=None)
    now = datetime(2026, 10, 9, tzinfo=timezone.utc)
    terminal, diagnostic = service._failure_diagnostic(
        cycle=SimpleNamespace(diagnostic={}), phase='PREPARE', exc=exception, now=now)
    assert terminal is True
    assert diagnostic['callback_failure'] == category
    assert diagnostic['phase_attempt_count'] == 1
    assert diagnostic['first_failure_at'] == diagnostic['latest_failure_at'] == now.isoformat()
    assert diagnostic['exception_fingerprint'] == service._exception_fingerprint(exception)


@pytest.mark.parametrize('phase,source_pending,terminal,category', [
    ('REFRESH', True, False, 'SOURCE_DATA_PENDING'),
    ('PREPARE', True, True, 'TRANSIENT_RETRY_EXHAUSTED'),
    ('REFRESH', False, True, 'TRANSIENT_RETRY_EXHAUSTED'),
])
def test_source_wait_and_infrastructure_exhaustion_keep_separate_authority(
        phase, source_pending, terminal, category):
    service = module.AutomationService(config=AutomationConfig(), holder_id='retry-contract',
                                      refresh=None, prepare=None, recover=None, execute=None)
    exception = (module.SourceDataPending('source pending') if source_pending
                 else TransientInfrastructureFailure('infrastructure unavailable'))
    cycle = SimpleNamespace(diagnostic={'retry_phase': phase, 'phase_attempt_count': 999,
                                       'first_failure_at': '2026-10-08T00:00:00+00:00'})
    actual_terminal, diagnostic = service._failure_diagnostic(
        cycle=cycle, phase=phase, exc=exception,
        now=datetime(2026, 10, 9, tzinfo=timezone.utc))
    assert actual_terminal is terminal
    assert diagnostic['callback_failure'] == category
    assert diagnostic['phase_attempt_count'] == 1000
    assert diagnostic['first_failure_at'] == cycle.diagnostic['first_failure_at']


@pytest.mark.parametrize('domain,expected', [('backup', 'BACKUP'), (' BROKER ', None), ('', None)])
def test_failure_domain_cannot_inject_unreviewed_notifier_authority(domain, expected):
    exception = TransientInfrastructureFailure('bounded failure')
    exception.failure_domain = domain
    assert module._failure_domain(exception) == expected


def scheduled_record(config, state, *, decision_session=date(2026, 10, 8)):
    from sentinel.automation.model import CycleRecord, CycleSpec, LeaderPermit
    timing = module.schedule.for_decision_session(decision_session, config)
    spec = CycleSpec(**timing.model_dump(), deployment_id='fault-lab',
        broker='alpaca-paper', broker_account_id='synthetic-account', takeover_epoch=1,
        control_generation=1, certificate_sha256='d' * 64, rollout_mode='PINNED_1_00',
        rollout_version=1, config_sha256=config.fingerprint)
    record = CycleRecord(**spec.model_dump(), cycle_id=spec.cycle_id, state=state,
        attempt_count=1, last_fence_token=1, diagnostic={},
        created_at=timing.prepare_at, updated_at=timing.prepare_at)
    permit = LeaderPermit(holder_id='phase-fault-lab', fence_token=1,
        control_generation=1, acquired_at=timing.execute_at,
        expires_at=timing.execute_at + timedelta(seconds=config.lease_seconds))
    return record, permit


@pytest.mark.parametrize('phase,state', [
    ('REFRESH', module.CycleState.REFRESHING_DATA),
    ('PREFLIGHT_RECOVER', module.CycleState.DISCOVERED),
    ('PREPARE', module.CycleState.PREPARING),
    ('RECOVER', module.CycleState.RECONCILING),
    ('EXECUTE', module.CycleState.EXECUTING),
])
@pytest.mark.parametrize('kind', ['stale_leader', 'supervisor_integrity', 'unknown_failure'])
def test_every_callback_phase_preserves_leadership_failure_and_unknown_transport(
        monkeypatch, phase, state, kind):
    failure = {'stale_leader': module.StaleLeaderRefused('authority lost'),
               'supervisor_integrity': module.SupervisorIntegrityFailure('supervisor lost'),
               'unknown_failure': OSError(errno.EIO, 'unknown callback outcome')}[kind]
    config = AutomationConfig()
    cycle, permit = scheduled_record(config, state)
    calls, transitions = [], []

    async def failed(context):
        context.require_active()
        assert context.cycle.cycle_id == cycle.cycle_id
        calls.append(phase)
        raise failure

    service = module.AutomationService(config=config, holder_id='phase-fault-lab',
        refresh=failed, prepare=failed, recover=failed, execute=failed)
    conn = SimpleNamespace(rollback=lambda: None)
    monkeypatch.setattr(module.store, 'require_leader', lambda conn, actual: actual)
    monkeypatch.setattr(module.integrity, 'validate_cycle_lineage', lambda *a: None)

    def transition(conn, *, cycle_id, to_state, **changes):
        assert cycle_id == cycle.cycle_id and changes.pop('permit') == permit
        transitions.append(to_state)
        return cycle.model_copy(update={'state': to_state, **changes})

    monkeypatch.setattr(module.store, 'transition_cycle', transition)
    operation = getattr(service, '_run_' + phase.lower())
    coroutine = operation(conn, now=cycle.execute_at, cycle=cycle, permit=permit)
    if kind != 'unknown_failure':
        with pytest.raises(type(failure)) as observed:
            asyncio.run(coroutine)
        assert observed.value is failure
        assert transitions == [], 'authority loss cannot publish a retry or success'
    else:
        result = asyncio.run(coroutine)
        target = module.CycleState.RECONCILING if phase == 'EXECUTE' else module.CycleState.BLOCKED
        assert result.cycle.state is target and transitions == [target]
        assert result.cycle.diagnostic['callback_failure'] == 'SOFTWARE_DEFECT'
        assert result.cycle.failure_code == 'OSError'
        if phase == 'EXECUTE':
            assert result.cycle.next_wake_at is not None
        else:
            assert result.cycle.next_wake_at is None
    assert calls == [phase]


@pytest.mark.parametrize('asynchronous', [False, True])
@pytest.mark.parametrize('action,state,reason,notify_expected,terminal_expected', [
    ('BLOCKED', 'BLOCKED', None, True, True),
    ('RETRY_SCHEDULED', 'RETRY_WAIT', None, True, False),
    ('SUPERSEDED', 'SUPERSEDED', None, True, True),
    ('WAITING', 'RECONCILING', None, True, False),
    ('WAITING', 'DISCOVERED', 'MISSED_STATE_ONLY audit recorded', True, False),
    ('INERT', None, 'automation emergency kill was explicitly engaged', True, False),
    ('WAITING', 'DISCOVERED', None, False, False),
    ('EXECUTED', 'SUCCEEDED', None, False, True),
    ('WAITING', 'MISSED_STATE_ONLY', None, False, True),
])
def test_process_loop_delivers_only_actionable_notifications_and_terminal_records(
        monkeypatch, asynchronous, action, state, reason, notify_expected,
        terminal_expected):
    """Alert delivery remains available while trading is inert or fenced."""
    observed = []

    def notify(conn, result):
        observed.append(('notify', conn, result))

    def terminal(conn, result):
        observed.append(('terminal', conn, result))

    async def async_notify(conn, result):
        notify(conn, result)

    async def async_terminal(conn, result):
        terminal(conn, result)

    service = module.AutomationService(config=AutomationConfig(), holder_id='loop-contract',
        refresh=None, prepare=None, recover=None, execute=None,
        notify=async_notify if asynchronous else notify,
        terminal=async_terminal if asynchronous else terminal)
    cycle, permit = scheduled_record(service.config,
        module.CycleState[state] if state else module.CycleState.DISCOVERED)
    result = module.TickResult(action=module.TickAction[action], cycle=cycle if state else None,
                               permit=permit, reason=reason)
    connection = SimpleNamespace(close=lambda: observed.append(('close',)))

    async def tick(conn, **kwargs):
        assert conn is connection and kwargs['heartbeat_conn_factory']() is connection
        return result

    monkeypatch.setattr(service, 'tick', tick)
    monkeypatch.setattr(module.store, 'register_instance',
        lambda conn, **kwargs: observed.append(('instance', kwargs)))
    assert asyncio.run(service.run(lambda: connection, stop=Ready(),
        clock=lambda: cycle.execute_at, max_ticks=1)) == 1
    notifications = [entry for entry in observed if entry[0] == 'notify']
    terminals = [entry for entry in observed if entry[0] == 'terminal']
    assert notifications == ([('notify', connection, result)] if notify_expected else [])
    assert terminals == ([('terminal', connection, result)] if terminal_expected else [])
    registration = next(entry[1] for entry in observed if entry[0] == 'instance')
    assert registration['state'] == action
    assert registration['next_wake_at'] > cycle.execute_at
    assert observed[-1] == ('close',)


@pytest.mark.parametrize('notify_present', [False, True])
def test_loop_failure_preserves_original_exception_and_closes_connection(
        monkeypatch, notify_present):
    failure = OSError(errno.EIO, 'dependency failed before a tick result')
    events = []

    def notify(conn, error):
        assert error is failure
        events.append('notified')

    service = module.AutomationService(config=AutomationConfig(), holder_id='loop-failure',
        refresh=None, prepare=None, recover=None, execute=None,
        notify=notify if notify_present else None)
    connection = SimpleNamespace(close=lambda: events.append('closed'))

    async def tick(*args, **kwargs):
        raise failure

    def register(conn, **kwargs):
        assert conn is connection and kwargs['state'] == 'FAILED'
        assert kwargs['next_wake_at'] is None
        assert kwargs['last_error'] == f'OSError: {failure}'
        events.append('failure recorded')

    monkeypatch.setattr(service, 'tick', tick)
    monkeypatch.setattr(module.store, 'register_instance', register)
    with pytest.raises(OSError) as actual:
        asyncio.run(service.run(lambda: connection, stop=Ready(),
            clock=lambda: datetime(2026, 10, 9, tzinfo=timezone.utc), max_ticks=1))
    assert actual.value is failure
    assert events == (['notified'] if notify_present else []) + ['failure recorded', 'closed']


@pytest.mark.parametrize('asynchronous', [False, True])
@pytest.mark.parametrize('hook_available', [False, True])
def test_loop_wakes_for_earliest_control_or_alert_without_extra_trading_tick(
        monkeypatch, asynchronous, hook_available):
    service = module.AutomationService(config=AutomationConfig(), holder_id='wake-contract',
        refresh=None, prepare=None, recover=None, execute=None)
    cycle, permit = scheduled_record(service.config, module.CycleState.RETRY_WAIT)
    now = cycle.execute_at
    cycle = cycle.model_copy(update={'next_wake_at': now + timedelta(seconds=2)})
    result = module.TickResult(action=module.TickAction.WAITING, cycle=cycle, permit=permit)
    sleeps, registrations, connections, ticks = [], [], [], []

    def connect():
        conn = SimpleNamespace(close=lambda: closed.append(conn))
        connections.append(conn)
        return conn

    closed = []

    async def tick(conn, **kwargs):
        ticks.append(conn)
        return result

    def alert(conn):
        return now + timedelta(seconds=.75) if hook_available else None

    async def async_alert(conn):
        return alert(conn)

    def control(conn):
        return now + timedelta(seconds=.5) if hook_available else None

    async def async_control(conn):
        return control(conn)

    async def sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(service, 'tick', tick)
    monkeypatch.setattr(module.store, 'register_instance',
        lambda conn, **kwargs: registrations.append(kwargs))
    assert asyncio.run(service.run(connect, stop=Ready(), clock=lambda: now,
        sleep=sleep, alert_wake=async_alert if asynchronous else alert,
        control_wake=async_control if asynchronous else control, max_ticks=2)) == 2
    expected_delay = .5 if hook_available else 2
    assert sleeps == [expected_delay]
    assert all(row['next_wake_at'] == now + timedelta(seconds=expected_delay)
               for row in registrations)
    assert ticks == connections == closed and len(ticks) == 2


@pytest.mark.parametrize('stopped,max_ticks', [(True, None), (False, 0)])
def test_stopped_or_zero_tick_loop_opens_no_dependencies(stopped, max_ticks):
    service = module.AutomationService(config=AutomationConfig(), holder_id='stopped-loop',
        refresh=None, prepare=None, recover=None, execute=None)
    assert asyncio.run(service.run(
        lambda: pytest.fail('unneeded dependency opened'), stop=Ready(stopped),
        clock=lambda: pytest.fail('unneeded clock observed'), max_ticks=max_ticks)) == 0


def test_missing_activation_binding_cannot_construct_an_executable_cycle():
    service = module.AutomationService(config=AutomationConfig(), holder_id='missing-binding',
        refresh=None, prepare=None, recover=None, execute=None)
    with pytest.raises(module.AutomationRefused, match='incomplete identity'):
        service._spec(SimpleNamespace(binding=None), object())


@pytest.mark.parametrize('raw_mapping', [False, True])
@pytest.mark.parametrize('disposition,initial,expired,new_generation,expected,states', [
    ('READY_TO_EXECUTE', 'RECONCILING', False, False, 'RECOVERED', ['RETRY_WAIT']),
    ('READY_TO_EXECUTE', 'EXECUTING', True, False, 'SUPERSEDED', ['RECONCILING', 'SUPERSEDED']),
    ('READY_TO_EXECUTE', 'RECONCILING', True, False, 'SUPERSEDED', ['SUPERSEDED']),
    ('READY_TO_EXECUTE', 'RECONCILING', False, True, 'BLOCKED', ['BLOCKED']),
    ('SUPERSEDED', 'EXECUTING', False, False, 'SUPERSEDED', ['RECONCILING', 'SUPERSEDED']),
    ('SUPERSEDED', 'EXECUTING', False, True, 'SUPERSEDED', ['SUPERSEDED']),
    ('SUCCEEDED', 'RETRY_WAIT', False, False, 'RECOVERED', ['RECONCILING', 'SUCCEEDED']),
    ('RETRY', 'RETRY_WAIT', False, False, 'RETRY_SCHEDULED', ['RECONCILING', 'RETRY_WAIT']),
    ('BLOCKED', 'RECONCILING', False, False, 'BLOCKED', ['BLOCKED']),
])
def test_clean_recovery_never_executes_an_old_or_expired_plan(
        monkeypatch, raw_mapping, disposition, initial, expired, new_generation,
        expected, states):
    config = AutomationConfig()
    cycle, permit = scheduled_record(config, module.CycleState[initial])
    now = (cycle.execution_close_at if expired else cycle.execute_at)
    permit = permit.model_copy(update={'acquired_at': now,
        'expires_at': now + timedelta(seconds=config.lease_seconds),
        'control_generation': 2 if new_generation else 1})
    original_identity = cycle.cycle_id
    calls, changes = [], []
    observation = module.ExecuteResult(disposition=module.ExecuteDisposition[disposition],
        last_clean_reconciliation_id='synthetic-clean-reconciliation',
        failure_code='RECOVERY_DETAIL', diagnostic={'retained': 'read-only recovery'})

    async def recover(context):
        context.require_active()
        assert context.cycle.cycle_id == original_identity
        calls.append('recover')
        return observation.model_dump() if raw_mapping else observation

    async def execute(context):
        pytest.fail('read-only recovery crossed the execution membrane')

    service = module.AutomationService(config=config, holder_id='clean-recovery-lab',
        refresh=None, prepare=None, recover=recover, execute=execute)
    connection = SimpleNamespace(rollback=lambda: None)
    monkeypatch.setattr(module.store, 'require_leader', lambda conn, actual: actual)
    current = cycle

    def persist(kind, conn, *, cycle_id, permit, to_state, **fields):
        nonlocal current
        assert conn is connection and cycle_id == original_identity
        changes.append((kind, to_state))
        current = current.model_copy(update={'state': to_state, **fields})
        return current

    monkeypatch.setattr(module.store, 'transition_cycle',
        lambda conn, **fields: persist('transition', conn, **fields))
    monkeypatch.setattr(module.store, 'adopt_cycle',
        lambda conn, **fields: persist('adopt', conn, **fields))
    result = asyncio.run(service._run_recover(connection, now=now, cycle=cycle, permit=permit))
    assert result.action is module.TickAction[expected]
    assert [state.value for _, state in changes] == states
    assert all(kind == ('adopt' if new_generation else 'transition') for kind, _ in changes)
    assert calls == ['recover'] and result.cycle.cycle_id == original_identity
    if new_generation and disposition == 'READY_TO_EXECUTE':
        assert result.cycle.failure_code == 'OLD_GENERATION_EXECUTION_REFUSED'
    elif expired:
        assert result.cycle.failure_code == 'MAX_EXECUTION_LATENESS_EXCEEDED'
    elif disposition == 'READY_TO_EXECUTE':
        assert result.cycle.next_wake_at == now
        assert result.cycle.diagnostic['retry_phase'] == 'EXECUTE'
    if result.cycle.state.terminal:
        assert result.cycle.next_wake_at is None


@pytest.mark.parametrize('offset', [0, 1])
def test_prepare_cannot_label_current_or_future_sessions_as_historical(
        monkeypatch, offset):
    config = AutomationConfig()
    cycle, permit = scheduled_record(config, module.CycleState.PREPARING)
    calls = []

    async def prepare(context):
        context.require_active()
        return module.PrepareResult(plan_id='unadmitted-plan',
            missed_sessions=(cycle.decision_session + timedelta(days=offset),))

    service = module.AutomationService(config=config, holder_id='history-boundary-lab',
        refresh=None, prepare=prepare, recover=None, execute=None)
    connection = SimpleNamespace(rollback=lambda: None)
    monkeypatch.setattr(module.store, 'require_leader', lambda conn, actual: actual)
    monkeypatch.setattr(module.store, 'ensure_historical_cycles',
        lambda *a, **k: pytest.fail('invalid historical session persisted'))
    monkeypatch.setattr(module.store, 'mark_historical_missed',
        lambda *a, **k: pytest.fail('invalid historical session terminalized'))

    def transition(conn, *, cycle_id, permit, to_state, **fields):
        assert conn is connection and cycle_id == cycle.cycle_id
        calls.append(to_state)
        return cycle.model_copy(update={'state': to_state, **fields})

    monkeypatch.setattr(module.store, 'transition_cycle', transition)
    result = asyncio.run(service._run_prepare(connection,
        now=cycle.execute_at, cycle=cycle, permit=permit))
    assert result.action is module.TickAction.BLOCKED
    assert calls == [module.CycleState.BLOCKED]
    assert result.cycle.plan_id is None
    assert 'not older than the current executable decision' in result.cycle.failure_detail


@pytest.mark.parametrize('raw_mapping', [False, True])
@pytest.mark.parametrize('disposition,state,action', [
    ('SUCCEEDED', 'SUCCEEDED', 'EXECUTED'),
    ('RECONCILE', 'RECONCILING', 'EXECUTED'),
    ('RETRY', 'RETRY_WAIT', 'RETRY_SCHEDULED'),
    ('BLOCKED', 'BLOCKED', 'BLOCKED'),
    ('SUPERSEDED', 'BLOCKED', 'BLOCKED'),
    ('READY_TO_EXECUTE', 'BLOCKED', 'BLOCKED'),
])
def test_executor_outcome_requires_its_own_conclusive_reconciliation(
        monkeypatch, raw_mapping, disposition, state, action):
    """An admission/recovery result cannot stand in for successful execution."""
    config = AutomationConfig()
    cycle, permit = scheduled_record(config, module.CycleState.EXECUTING)
    events, transitions = [], []
    observation = module.ExecuteResult(disposition=module.ExecuteDisposition[disposition],
        last_clean_reconciliation_id='synthetic-execution-reconciliation',
        failure_code='EXECUTION_DETAIL', diagnostic={'observed': disposition})

    async def execute(context):
        context.require_active()
        assert context.cycle == cycle and context.permit == permit
        events.append('execute')
        return observation.model_dump() if raw_mapping else observation

    service = module.AutomationService(config=config, holder_id='execution-outcome-lab',
        refresh=None, prepare=None, recover=None, execute=execute)
    connection = SimpleNamespace(rollback=lambda: None)
    monkeypatch.setattr(module.store, 'require_leader', lambda conn, actual: actual)
    monkeypatch.setattr(module.integrity, 'validate_cycle_lineage',
        lambda conn, actual: events.append('validated lineage'))

    def transition(conn, *, cycle_id, permit, to_state, **fields):
        assert conn is connection and cycle_id == cycle.cycle_id
        transitions.append(to_state)
        return cycle.model_copy(update={'state': to_state, **fields})

    monkeypatch.setattr(module.store, 'transition_cycle', transition)
    result = asyncio.run(service._run_execute(connection, now=cycle.execute_at,
        cycle=cycle, permit=permit))
    assert result.action is module.TickAction[action]
    assert result.cycle.state is module.CycleState[state]
    assert transitions == [module.CycleState[state]]
    assert events == ['validated lineage', 'execute']
    assert result.cycle.last_clean_reconciliation_id == observation.last_clean_reconciliation_id
    assert (result.cycle.next_wake_at is None) is result.cycle.state.terminal
    if disposition == 'RETRY':
        assert result.cycle.diagnostic['retry_phase'] == 'EXECUTE'


@pytest.mark.parametrize('boundary', ['before_open', 'expired'])
def test_executor_time_boundary_refuses_or_recovers_without_new_transport(
        monkeypatch, boundary):
    config = AutomationConfig()
    cycle, permit = scheduled_record(config, module.CycleState.EXECUTING)
    events = []

    async def execute(context):
        pytest.fail('fresh transport outside the immutable execution boundary')

    async def recover(conn, *, now, cycle, permit, **kwargs):
        events.append(('recover', cycle.cycle_id))
        return module.TickResult(action=module.TickAction.RECOVERED, cycle=cycle, permit=permit)

    service = module.AutomationService(config=config, holder_id='execution-time-lab',
        refresh=None, prepare=None, recover=None, execute=execute)
    monkeypatch.setattr(module.integrity, 'validate_cycle_lineage',
        lambda conn, actual: events.append(('lineage', actual.cycle_id)))
    monkeypatch.setattr(service, '_run_recover', recover)
    now = (cycle.execute_at - timedelta(microseconds=1)
           if boundary == 'before_open' else cycle.execution_close_at)
    if boundary == 'before_open':
        with pytest.raises(module.AutomationRefused, match='before immutable execute_at'):
            asyncio.run(service._run_execute(object(), now=now, cycle=cycle, permit=permit))
        assert events == [('lineage', cycle.cycle_id)]
    else:
        result = asyncio.run(service._run_execute(object(), now=now, cycle=cycle, permit=permit))
        assert result.action is module.TickAction.RECOVERED
        assert events == [('lineage', cycle.cycle_id), ('recover', cycle.cycle_id)]


@pytest.mark.parametrize('initial', ['DISCOVERED', 'RETRY_WAIT', 'RECONCILING'])
@pytest.mark.parametrize('clock', ['before_open', 'at_open', 'after_open'])
@pytest.mark.parametrize('supersede', [False, True])
@pytest.mark.parametrize('disposition', ['SUCCEEDED', 'SUPERSEDED', 'RETRY', 'BLOCKED'])
def test_preflight_recovery_must_finish_before_publication_and_never_executes(
        monkeypatch, initial, clock, supersede, disposition):
    config = AutomationConfig()
    cycle, permit = scheduled_record(config, module.CycleState[initial])
    now = {'before_open': cycle.execution_open_at - timedelta(microseconds=1),
           'at_open': cycle.execution_open_at,
           'after_open': cycle.execution_open_at + timedelta(minutes=90)}[clock]
    permit = permit.model_copy(update={'acquired_at': now,
        'expires_at': now + timedelta(seconds=config.lease_seconds)})
    if initial == 'RECONCILING':
        cycle = cycle.model_copy(update={'diagnostic': {'retry_phase': 'PREFLIGHT_RECOVER'}})
    observation = module.ExecuteResult(disposition=module.ExecuteDisposition[disposition],
        last_clean_reconciliation_id='synthetic-preflight-reconciliation',
        failure_code='PREFLIGHT_DETAIL', diagnostic={'observed': disposition})
    events, transitions = [], []

    async def recover(context):
        context.require_active()
        assert context.cycle.cycle_id == cycle.cycle_id
        events.append('read-only recovery')
        return observation

    async def forbidden(context):
        pytest.fail('preflight advanced source or initiated transport')

    service = module.AutomationService(config=config, holder_id='preflight-outcome-lab',
        refresh=forbidden, prepare=forbidden, recover=recover, execute=forbidden)
    connection = SimpleNamespace(rollback=lambda: None)
    monkeypatch.setattr(module.store, 'require_leader', lambda conn, actual: actual)
    current = cycle

    def transition(conn, *, cycle_id, permit, to_state, **fields):
        nonlocal current
        assert conn is connection and cycle_id == cycle.cycle_id
        transitions.append(to_state)
        if fields.pop('increment_attempt', False):
            fields['attempt_count'] = current.attempt_count + 1
        current = current.model_copy(update={'state': to_state, **fields})
        return current

    monkeypatch.setattr(module.store, 'transition_cycle', transition)
    result = asyncio.run(service._run_preflight_recover(connection, now=now,
        cycle=cycle, permit=permit, supersede_on_success=supersede))
    clean_cutover = (supersede or clock != 'before_open') and disposition in {
        'SUCCEEDED', 'SUPERSEDED'}
    expected = ('SUPERSEDED' if clean_cutover else 'REFRESHING_DATA' if disposition == 'SUCCEEDED'
                else 'BLOCKED' if disposition == 'BLOCKED' else 'RETRY_WAIT')
    assert result.cycle.state is module.CycleState[expected]
    assert events == ['read-only recovery']
    assert transitions[-1] is module.CycleState[expected]
    assert result.cycle.last_clean_reconciliation_id == observation.last_clean_reconciliation_id
    if clean_cutover:
        assert result.action is module.TickAction.SUPERSEDED
        assert result.cycle.failure_code == ('STALE_PREFLIGHT_RECOVERED' if supersede
                                            else 'DISCOVERED_AFTER_SESSION_OPEN')
        assert result.cycle.diagnostic['preflight_recovery_complete'] is True
        assert result.cycle.next_wake_at is None
    elif disposition == 'SUCCEEDED':
        assert result.action is module.TickAction.RECOVERED
        assert result.cycle.diagnostic['preflight_recovery_complete'] is True
    elif disposition == 'BLOCKED':
        assert result.action is module.TickAction.BLOCKED
    else:
        assert result.action is module.TickAction.RETRY_SCHEDULED
        assert result.cycle.diagnostic['retry_phase'] == 'PREFLIGHT_RECOVER'
        assert result.cycle.next_wake_at > now


def test_inherited_process_object_cannot_signal_or_join_foreign_parent(monkeypatch):
    process = Process()
    monkeypatch.setattr(process, 'is_alive',
        lambda: (_ for _ in ()).throw(AssertionError('not the owning parent')))
    monkeypatch.setattr(module.os, 'killpg', lambda *a: pytest.fail('foreign process group'))
    module._kill_callback_process(process)
    assert process.kills == 0 and process.joins == []


@pytest.mark.parametrize('as_result', [False, True])
@pytest.mark.parametrize('new_generation', [False, True])
def test_recovery_retry_restores_legal_state_without_resetting_the_book(
        monkeypatch, as_result, new_generation):
    config = AutomationConfig()
    cycle, permit = scheduled_record(config, module.CycleState.RETRY_WAIT)
    cycle = cycle.model_copy(update={'plan_id': 'retained-plan',
        'state_fingerprint': 's' * 64, 'plan_fingerprint': 'p' * 64})
    permit = permit.model_copy(update={'control_generation': 2 if new_generation else 1})
    changes = []
    current = cycle
    connection = object()

    def persist(kind, conn, *, cycle_id, permit, to_state, **fields):
        nonlocal current
        assert conn is connection and cycle_id == cycle.cycle_id
        changes.append((kind, to_state))
        current = current.model_copy(update={'state': to_state, **fields})
        return current

    monkeypatch.setattr(module.store, 'transition_cycle',
        lambda conn, **fields: persist('transition', conn, **fields))
    monkeypatch.setattr(module.store, 'adopt_cycle',
        lambda conn, **fields: persist('adopt', conn, **fields))
    service = module.AutomationService(config=config, holder_id='recovery-retry-lab',
        refresh=None, prepare=None, recover=None, execute=None)
    if as_result:
        result = service._handle_retry_result(connection, now=cycle.execute_at,
            cycle=cycle, permit=permit, phase='RECOVER', failure_code='JOURNAL_PENDING',
            failure_detail='read-only journal still unresolved',
            result_diagnostic={'retained_obligation': cycle.cycle_id},
            last_clean_reconciliation_id='retained-proof', recovery_transition=True)
        assert result.cycle.last_clean_reconciliation_id == 'retained-proof'
        assert result.cycle.diagnostic['retained_obligation'] == cycle.cycle_id
    else:
        exception = TransientInfrastructureFailure('restore proof pending',
            retry_after_seconds=config.retry_max_seconds + 17)
        exception.failure_domain = 'BACKUP'
        result = service._handle_callback_failure(connection, now=cycle.execute_at,
            cycle=cycle, permit=permit, phase='RECOVER', exc=exception,
            recovery_transition=True)
        assert result.cycle.next_wake_at == cycle.execute_at + timedelta(
            seconds=config.retry_max_seconds + 17)
        assert result.cycle.diagnostic['failure_domain'] == 'BACKUP'
    assert result.action is module.TickAction.RETRY_SCHEDULED
    assert result.cycle.cycle_id == cycle.cycle_id and result.cycle.plan_id == cycle.plan_id
    assert changes == ([('adopt', module.CycleState.RETRY_WAIT)] if new_generation else
        [('transition', module.CycleState.RECONCILING),
         ('transition', module.CycleState.RETRY_WAIT)])
    assert result.cycle.diagnostic['notifier_action'] == 'RETRY_SCHEDULED'


@pytest.mark.parametrize('mode', [
    'factory_failure', 'factory_none', 'lease_failure', 'close_failure',
    'lease_and_close_failure', 'cancel_before_factory',
    'cancel_after_factory', 'cancel_before_renewal', 'cancel_after_renewal',
    'one_successful_renewal',
])
def test_heartbeat_failure_and_revocation_never_accept_completed_child_authority(
        monkeypatch, mode):
    """Drive the independent heartbeat at each connection/renewal boundary.

    The doubles own no OS process or database. Real-process deadline/reaping
    suites separately prove those boundaries; this checks the parent protocol.
    """
    context, events = Context(), []
    failure = OSError(errno.EIO, 'injected heartbeat ' + mode)
    ready = Ready()
    ready.wait = lambda **kwargs: ready.is_set()
    process = Process(ready=True)
    process.start = ready.set
    parent, child_channel = Channel(), Channel()
    parent.poll = lambda: mode not in {'factory_failure', 'factory_none', 'lease_failure',
                                     'lease_and_close_failure'}
    parent.recv_bytes = lambda: b'{"kind":"result","value":"child completed"}'
    factory_calls = []

    class Stop:
        def __init__(self):
            self.value = False
            self.checks = 0
            self.waits = 0

        def wait(self, seconds):
            self.waits += 1
            if mode == 'one_successful_renewal' and self.waits > 1:
                return True
            return self.value

        def is_set(self):
            self.checks += 1
            boundary = {'cancel_after_factory': 2, 'cancel_before_renewal': 3,
                        'cancel_after_renewal': 4}.get(mode)
            if self.checks == boundary:
                context.cancellation.cancel('revoked at heartbeat boundary')
                self.value = True
            return self.value

        def set(self):
            self.value = True

    class Worker:
        def __init__(self, *, target, **kwargs):
            self.target = target

        def start(self):
            if mode == 'cancel_before_factory':
                context.cancellation.cancel('revoked before heartbeat connection')
            self.target()

        def join(self, *, timeout):
            assert timeout == 1
            events.append('heartbeat joined')

        def is_alive(self):
            return False

    def close_heartbeat():
        events.append('heartbeat closed')
        if mode == 'close_failure':
            raise failure
        if mode == 'lease_and_close_failure':
            raise OSError('secondary close failure must not replace lease refusal')

    def connect():
        factory_calls.append('connected')
        if len(factory_calls) == 1:
            return SimpleNamespace(close=lambda: events.append('startup closed'))
        if mode == 'factory_failure':
            raise failure
        if mode == 'factory_none':
            return None
        return SimpleNamespace(close=close_heartbeat)

    def heartbeat_lease(conn, **kwargs):
        assert kwargs == {'permit': None, 'lease_seconds': 30, 'callback': True}
        events.append('lease renewed')
        if mode in {'lease_failure', 'lease_and_close_failure'}:
            raise failure

    def killpg(pid, sig):
        assert pid == process.pid
        process.alive = False
        raise ProcessLookupError('owned simulated child was reaped')

    async def callback(_context):
        pytest.fail('parent executed a child-owned callback')

    process_context = SimpleNamespace(Event=lambda: ready if process_context.ready_used else
        use_first_event(), Pipe=lambda **kwargs: (parent, child_channel),
        Process=lambda **kwargs: process, ready_used=False)

    def use_first_event():
        process_context.ready_used = True
        return Ready()

    monkeypatch.setattr(module, 'threading', SimpleNamespace(Event=Stop, Thread=Worker))
    monkeypatch.setattr(module.multiprocessing, 'get_context', lambda _: process_context)
    monkeypatch.setattr(module.store, 'register_instance', lambda *a, **k: None)
    monkeypatch.setattr(module.store, 'heartbeat_lease', heartbeat_lease)
    monkeypatch.setattr(module.os, 'killpg', killpg)
    service = module.AutomationService(config=AutomationConfig(lease_seconds=30, heartbeat_seconds=5), holder_id='heartbeat-fault-lab',
        refresh=callback, prepare=callback, recover=callback, execute=callback)
    invocation = service._invoke(callback, context, permit=None,
        phase='PREPARE', heartbeat_conn_factory=connect)
    if mode == 'one_successful_renewal':
        assert asyncio.run(invocation) == 'child completed'
        assert not context.cancellation.cancelled
    else:
        with pytest.raises(module.StaleLeaderRefused) as refusal:
            asyncio.run(invocation)
        expected_reason = ('no owned connection' if mode == 'factory_none' else
                           'injected heartbeat' if mode.endswith('failure') else 'revoked')
        assert expected_reason in str(refusal.value)
        assert context.cancellation.cancelled
    assert parent.closed and child_channel.closed
    assert process.joins and not process.is_alive()
    assert events[0] == 'startup closed' and events[-1] == 'heartbeat joined'
    assert factory_calls == ['connected'] * (1 if mode == 'cancel_before_factory' else 2)
    expected_renewal = mode in {'lease_failure', 'close_failure', 'cancel_after_renewal',
                              'one_successful_renewal', 'lease_and_close_failure'}
    assert events.count('lease renewed') == int(expected_renewal)
    expected_close = mode not in {'factory_failure', 'factory_none', 'cancel_before_factory'}
    assert events.count('heartbeat closed') == int(expected_close)


@pytest.mark.parametrize('mode', ['factory', 'register', 'close', 'fork'])
def test_supervised_startup_failure_owns_no_callback_or_process(monkeypatch, mode):
    events = []
    failure = OSError(errno.EIO, 'injected startup ' + mode)

    def connect():
        events.append('connect')
        if mode == 'factory':
            raise failure
        return SimpleNamespace(close=close)

    def close():
        events.append('close')
        if mode == 'close':
            raise failure

    def register(*args, **kwargs):
        events.append('register')
        if mode == 'register':
            raise failure

    def fork_context(method):
        assert mode == 'fork' and method == 'fork'
        events.append('fork')
        raise ValueError('platform has no fork support')

    async def callback(_context):
        pytest.fail('failed startup acquired callback authority')

    monkeypatch.setattr(module.store, 'register_instance', register)
    monkeypatch.setattr(module.multiprocessing, 'get_context', fork_context)
    monkeypatch.setattr(module.os, 'killpg', lambda *a: pytest.fail('unowned process signaled'))
    service = module.AutomationService(config=AutomationConfig(), holder_id='startup-fault-lab',
        refresh=callback, prepare=callback, recover=callback, execute=callback)
    with pytest.raises(SoftwareDefect if mode == 'fork' else module.StaleLeaderRefused) as observed:
        asyncio.run(service._invoke(callback, Context(), permit=None,
            phase='PREPARE', heartbeat_conn_factory=connect))
    assert str(observed.value.__cause__) == (str(failure) if mode != 'fork' else
                                           'platform has no fork support')
    assert events == (['connect'] if mode == 'factory' else
        ['connect', 'register', 'close'] + (['fork'] if mode == 'fork' else []))


def tick_route(monkeypatch, cycle, permit, now, *, prior=None, unresolved=None):
    """Observe only the orchestration boundary against an immutable snapshot.

    PostgreSQL transition guards and callback effects are independently tested.
    Any unselected callback or additional cycle creation is a test failure.
    """
    config = AutomationConfig()
    routes, transitions, creates = [], [], []
    connection = SimpleNamespace(rollback=lambda: None)
    binding = ControlBinding(**{name: getattr(cycle, name) for name in
        ('deployment_id', 'broker', 'broker_account_id', 'takeover_epoch',
         'certificate_sha256', 'rollout_mode', 'rollout_version', 'config_sha256')})
    control = SimpleNamespace(enabled=True, kill_switch_engaged=False,
        config_sha256=config.fingerprint, generation=1, binding=binding)
    service = module.AutomationService(config=config, holder_id='tick-route-lab',
        refresh=None, prepare=None, recover=None, execute=None)
    monkeypatch.setattr(module.store, 'load_control', lambda conn: control)
    monkeypatch.setattr(module.store, 'acquire_lease', lambda conn, **kwargs: permit)
    monkeypatch.setattr(module.store, 'oldest_nonterminal_other_generation_cycle',
        lambda *a, **k: None)
    monkeypatch.setattr(module.store, 'blocked_cycle_for_generation', lambda *a, **k: None)
    monkeypatch.setattr(module.store, 'latest_cycle', lambda conn: prior)
    monkeypatch.setattr(module.store, 'oldest_unresolved_transport_cycle',
        lambda *a, **k: unresolved)
    monkeypatch.setattr(module.integrity, 'validate_cycle_lineage', lambda *a: None)
    current = cycle

    def create(conn, *, spec, **kwargs):
        assert conn is connection and spec.cycle_id == cycle.cycle_id
        creates.append(spec.cycle_id)
        return current

    def transition(conn, *, cycle_id, permit, to_state, **fields):
        nonlocal current
        assert conn is connection and cycle_id == cycle.cycle_id
        transitions.append(to_state)
        if fields.pop('increment_attempt', False):
            fields['attempt_count'] = current.attempt_count + 1
        current = current.model_copy(update={'state': to_state, **fields})
        return current

    monkeypatch.setattr(module.store, 'create_cycle', create)
    monkeypatch.setattr(module.store, 'transition_cycle', transition)
    for phase, action in [('preflight_recover', 'RECOVERED'), ('recover', 'RECOVERED'),
                          ('refresh', 'REFRESHED'), ('prepare', 'PREPARED'),
                          ('execute', 'EXECUTED')]:
        async def selected(conn, *, cycle, permit, phase=phase, action=action, **kwargs):
            assert conn is connection
            routes.append((phase, cycle.cycle_id, kwargs))
            return module.TickResult(action=module.TickAction[action], cycle=cycle, permit=permit)
        monkeypatch.setattr(service, '_run_' + phase, selected)
    return service, connection, routes, transitions, creates


@pytest.mark.parametrize('state,phase,fence,clock,wake,expected', [
    ('RETRY_WAIT', 'PREFLIGHT_RECOVER', 1, 'open', False, 'preflight_recover'),
    ('RETRY_WAIT', 'PREFLIGHT_RECOVER', 0, 'open', False, 'preflight_recover'),
    ('RETRY_WAIT', 'RECOVER', 0, 'open', False, 'recover'),
    ('RETRY_WAIT', 'EXECUTE', 1, 'before_open', False, None),
    ('RETRY_WAIT', 'EXECUTE', 1, 'open', False, 'execute'),
    ('RETRY_WAIT', 'EXECUTE', 1, 'closed', False, 'recover'),
    ('RETRY_WAIT', 'PREPARE', 1, 'open', False, 'prepare'),
    ('RETRY_WAIT', 'REFRESH', 1, 'open', False, 'refresh'),
    ('RETRY_WAIT', 'PREPARE', 1, 'open', True, None),
    ('DISCOVERED', '', 1, 'open', False, 'preflight_recover'),
    ('WAITING_OPEN', '', 1, 'late', False, None),
    ('EXECUTING', '', 0, 'open', False, 'recover'),
    ('EXECUTING', '', 1, 'closed', False, 'recover'),
    ('EXECUTING', '', 1, 'late', False, 'recover'),
    ('EXECUTING', '', 1, 'before_open', False, 'refused'),
    ('RECONCILING', 'RECOVER', 1, 'open', False, 'recover'),
    ('SUCCEEDED', '', 1, 'open', False, None),
])
def test_tick_routes_recovery_and_wakes_before_any_fresh_transport(
        monkeypatch, state, phase, fence, clock, wake, expected):
    config = AutomationConfig()
    cycle, permit = scheduled_record(config, module.CycleState[state])
    times = {'open': cycle.execute_at,
        'before_open': cycle.execute_at - timedelta(microseconds=1),
        'closed': cycle.execution_close_at,
        'late': cycle.execute_at + timedelta(seconds=config.maximum_execution_lateness_seconds,
                                             microseconds=1)}
    now = times[clock]
    cycle = cycle.model_copy(update={'last_fence_token': fence,
        'diagnostic': {'retry_phase': phase} if phase else {},
        'next_wake_at': now + timedelta(seconds=17) if wake else None})
    older_obligation = now >= cycle.execution_close_at
    service, connection, routes, transitions, creates = tick_route(
        monkeypatch, cycle, permit, now, prior=cycle if older_obligation else None)
    if expected == 'refused':
        with pytest.raises(module.AutomationRefused, match='before immutable execute_at'):
            asyncio.run(service.tick(connection, now=now))
        assert not routes
    else:
        result = asyncio.run(service.tick(connection, now=now))
        assert [entry[0] for entry in routes] == ([expected] if expected else [])
        assert all(entry[1] == cycle.cycle_id for entry in routes)
        assert result.cycle.cycle_id == cycle.cycle_id
        if clock == 'late' and state == 'WAITING_OPEN':
            assert result.action is module.TickAction.SUPERSEDED
            assert result.cycle.failure_code == 'MAX_EXECUTION_LATENESS_EXCEEDED'
            assert result.cycle.next_wake_at is None
        elif expected is None:
            assert result.action is module.TickAction.WAITING
    assert creates == ([] if older_obligation else [cycle.cycle_id])
    if state == 'RETRY_WAIT' and expected in {'prepare', 'refresh'}:
        assert transitions == [module.CycleState.PREPARING if expected == 'prepare'
                               else module.CycleState.REFRESHING_DATA]
    elif state == 'RETRY_WAIT' and expected == 'execute':
        assert transitions == [module.CycleState.EXECUTING]
        assert result.cycle.attempt_count == cycle.attempt_count + 1
    elif clock == 'late' and state == 'WAITING_OPEN':
        assert transitions == [module.CycleState.SUPERSEDED]
    else:
        assert transitions == []


@pytest.mark.parametrize('initial', ['RETRY_WAIT', 'RECONCILING'])
@pytest.mark.parametrize('disposition', ['SUCCEEDED', 'RETRY', 'BLOCKED'])
def test_new_generation_preflight_adopts_the_fence_without_rewriting_its_book(
        monkeypatch, initial, disposition):
    """A replacement worker may reconcile an old preflight, never trade it."""
    config = AutomationConfig()
    cycle, permit = scheduled_record(config, module.CycleState[initial])
    cycle = cycle.model_copy(update={'last_fence_token': 0,
        'state_fingerprint': 'retained-shadow-state',
        'diagnostic': {'retry_phase': 'PREFLIGHT_RECOVER'}})
    permit = permit.model_copy(update={'control_generation': 2})
    current = cycle
    events = []
    connection = object()

    def adopt(conn, *, cycle_id, permit, to_state=None, **changes):
        nonlocal current
        assert conn is connection and cycle_id == cycle.cycle_id
        events.append(('adopt', to_state))
        current = current.model_copy(update={
            'last_fence_token': permit.fence_token,
            'state': current.state if to_state is None else to_state, **changes})
        return current

    async def recover(context):
        context.require_active()
        assert context.cycle.last_fence_token == permit.fence_token
        assert context.cycle.control_generation == cycle.control_generation
        events.append(('read-only recovery', None))
        return module.ExecuteResult(disposition=module.ExecuteDisposition[disposition],
            last_clean_reconciliation_id='replacement-preflight-proof',
            failure_code='JOURNAL_PENDING' if disposition != 'SUCCEEDED' else None)

    async def forbidden(context):
        pytest.fail('replacement preflight attempted publication or new transport')

    monkeypatch.setattr(module.store, 'adopt_cycle', adopt)
    monkeypatch.setattr(module.store, 'transition_cycle',
        lambda *a, **k: pytest.fail('old generation used a same-generation transition'))
    monkeypatch.setattr(module.store, 'require_leader', lambda conn, actual: actual)
    service = module.AutomationService(config=config, holder_id='replacement-preflight-lab',
        refresh=forbidden, prepare=forbidden, recover=recover, execute=forbidden)
    result = asyncio.run(service._run_preflight_recover(connection,
        now=cycle.execute_at, cycle=cycle, permit=permit, supersede_on_success=True))
    expected = {'SUCCEEDED': module.CycleState.SUPERSEDED,
        'RETRY': module.CycleState.RETRY_WAIT, 'BLOCKED': module.CycleState.BLOCKED}[disposition]
    assert events[0] == ('adopt', None)
    assert ('read-only recovery', None) in events
    assert events[-1] == ('adopt', expected)
    assert result.cycle.state is expected
    assert result.cycle.cycle_id == cycle.cycle_id
    assert result.cycle.control_generation == cycle.control_generation
    assert result.cycle.state_fingerprint == cycle.state_fingerprint
    assert result.cycle.last_clean_reconciliation_id == 'replacement-preflight-proof'
    assert result.cycle.plan_id is None
    assert (result.cycle.next_wake_at is None) is expected.terminal


@pytest.mark.parametrize('query,phase', [
    ('prior', 'PREFLIGHT_RECOVER'), ('prior', 'RECOVER'),
    ('unresolved', 'PREFLIGHT_RECOVER'), ('unresolved', 'RECOVER'),
])
def test_old_obligation_is_recovered_before_creating_a_new_session(
        monkeypatch, query, phase):
    config = AutomationConfig()
    cycle, permit = scheduled_record(config, module.CycleState.RECONCILING)
    cycle = cycle.model_copy(update={'diagnostic': {'retry_phase': phase}})
    now = cycle.execution_close_at + timedelta(hours=12)
    service, connection, routes, transitions, creates = tick_route(
        monkeypatch, cycle, permit, now, **{query: cycle})
    result = asyncio.run(service.tick(connection, now=now))
    expected = 'preflight_recover' if phase == 'PREFLIGHT_RECOVER' else 'recover'
    assert [entry[0] for entry in routes] == [expected]
    assert routes[0][1] == cycle.cycle_id and result.cycle == cycle
    assert not creates and not transitions
    if expected == 'preflight_recover':
        assert routes[0][2]['supersede_on_success'] is True


def test_configuration_race_cannot_kill_a_new_generation_or_acquire_a_lease(monkeypatch):
    config = AutomationConfig()
    control = SimpleNamespace(enabled=True, kill_switch_engaged=False,
        config_sha256='a' * 64, generation=17)
    attempts = []
    monkeypatch.setattr(module.store, 'load_control', lambda conn: control)
    monkeypatch.setattr(module.store, 'acquire_lease',
        lambda *a, **k: pytest.fail('mismatched configuration acquired trading authority'))

    def changed(conn, **kwargs):
        attempts.append(kwargs)
        raise module.StaleLeaderRefused('new generation won the fence')

    monkeypatch.setattr(module.store, 'engage_config_mismatch_kill', changed)
    service = module.AutomationService(config=config, holder_id='config-race-lab',
        refresh=None, prepare=None, recover=None, execute=None)
    result = asyncio.run(service.tick(object(), now=datetime(2026, 10, 9, tzinfo=timezone.utc)))
    assert result.action is module.TickAction.INERT and result.permit is None
    assert 'control changed during config fencing' in result.reason
    assert attempts == [{'expected_generation': 17,
        'expected_config_sha256': 'a' * 64, 'actual_config_sha256': config.fingerprint}]


def test_before_source_finality_reuses_the_prior_obligation_without_a_future_plan(monkeypatch):
    config = AutomationConfig()
    future, _ = scheduled_record(config, module.CycleState.DISCOVERED)
    now = future.prepare_at - timedelta(microseconds=1)
    prior, permit = scheduled_record(config, module.CycleState.SUCCEEDED,
        decision_session=date(2026, 10, 7))
    service, connection, routes, transitions, creates = tick_route(
        monkeypatch, prior, permit, now, prior=prior)
    result = asyncio.run(service.tick(connection, now=now))
    assert result.action is module.TickAction.WAITING and result.cycle == prior
    assert creates == [prior.cycle_id] and future.cycle_id not in creates
    assert not routes and not transitions


def test_exhausted_recovery_result_cannot_publish_another_retry_wake(monkeypatch):
    config = AutomationConfig()
    cycle, permit = scheduled_record(config, module.CycleState.RETRY_WAIT)
    cycle = cycle.model_copy(update={'plan_id': 'retained-plan',
        'state_fingerprint': 'retained-book',
        'diagnostic': {'retry_phase': 'RECOVER', 'phase_attempt_count': 999,
                       'first_failure_at': '2026-10-08T00:00:00+00:00'}})
    writes = []
    def transition(conn, *, cycle_id, permit, to_state, **changes):
        assert cycle_id == cycle.cycle_id
        writes.append(to_state)
        return cycle.model_copy(update={'state': to_state, **changes})
    monkeypatch.setattr(module.store, 'transition_cycle', transition)
    service = module.AutomationService(config=config, holder_id='exhausted-recovery',
        refresh=None, prepare=None, recover=None, execute=None)
    result = service._handle_retry_result(object(), now=cycle.execute_at,
        cycle=cycle, permit=permit, phase='RECOVER', failure_code='STILL_PENDING',
        failure_detail='independent recovery remains unresolved',
        result_diagnostic={'retained_obligation': cycle.cycle_id}, recovery_transition=True)
    assert result.action is module.TickAction.BLOCKED
    assert writes == [module.CycleState.BLOCKED]
    assert result.cycle.next_wake_at is None
    assert result.cycle.diagnostic['terminal_reason'] == 'TRANSIENT_RETRY_EXHAUSTED'
    assert 'notifier_action' not in result.cycle.diagnostic
    assert result.cycle.plan_id == cycle.plan_id
    assert result.cycle.state_fingerprint == cycle.state_fingerprint


def test_future_obligation_cannot_displace_a_still_open_prior_cycle(monkeypatch):
    config = AutomationConfig()
    cycle, _ = scheduled_record(config, module.CycleState.DISCOVERED)
    prior, permit = scheduled_record(config, module.CycleState.PLAN_READY,
                                    decision_session=date(2026, 10, 7))
    now = prior.execute_at
    service, connection, routes, transitions, creates = tick_route(
        monkeypatch, cycle, permit, now, prior=prior)
    # Explicit fault observation: the calendar supplied a future obligation.
    # It must not cause a second book/plan while the old immutable window lives.
    monkeypatch.setattr(module.schedule, 'for_clock',
        lambda *a: module.schedule.for_decision_session(cycle.decision_session, config))
    result = asyncio.run(service.tick(connection, now=now))
    assert result.action is module.TickAction.BLOCKED and result.cycle == prior
    assert not routes and not transitions and not creates


def test_nontransport_query_row_cannot_grant_old_executor_authority(monkeypatch):
    config = AutomationConfig()
    cycle, permit = scheduled_record(config, module.CycleState.DISCOVERED)
    unrelated, _ = scheduled_record(config, module.CycleState.REFRESHING_DATA,
                                   decision_session=date(2026, 10, 7))
    service, connection, routes, transitions, creates = tick_route(
        monkeypatch, cycle, permit, cycle.execute_at, unresolved=unrelated)
    result = asyncio.run(service.tick(connection, now=cycle.execute_at))
    assert result.cycle == cycle
    assert [route[0] for route in routes] == ['preflight_recover']
    assert all(route[1] == cycle.cycle_id for route in routes)
    assert creates == [cycle.cycle_id] and not transitions


def test_early_discovered_snapshot_waits_without_entering_a_callback(monkeypatch):
    config = AutomationConfig()
    cycle, permit = scheduled_record(config, module.CycleState.DISCOVERED)
    now = cycle.prepare_at - timedelta(microseconds=1)
    service, connection, routes, transitions, creates = tick_route(
        monkeypatch, cycle, permit, now)
    monkeypatch.setattr(module.schedule, 'for_clock',
        lambda *a: module.schedule.for_decision_session(cycle.decision_session, config))
    result = asyncio.run(service.tick(connection, now=now))
    assert result.action is module.TickAction.WAITING and result.cycle == cycle
    assert creates == [cycle.cycle_id] and not routes and not transitions


def test_inconsistent_recovery_classifier_still_adopts_before_transport(monkeypatch):
    config = AutomationConfig()
    cycle, permit = scheduled_record(config, module.CycleState.EXECUTING)
    cycle = cycle.model_copy(update={'last_fence_token': 0})
    service, connection, routes, transitions, creates = tick_route(
        monkeypatch, cycle, permit, cycle.execute_at)
    # Deliberately inconsistent dependency classification must not let the late
    # dispatch use another holder's fence for new transport.
    monkeypatch.setattr(module.store, 'cycle_recovery_capable', lambda _: False)
    adopted = []
    def adopt(conn, *, cycle_id, permit):
        assert cycle_id == cycle.cycle_id
        adopted.append(cycle_id)
        return cycle.model_copy(update={'last_fence_token': permit.fence_token})
    monkeypatch.setattr(module.store, 'adopt_cycle', adopt)
    result = asyncio.run(service.tick(connection, now=cycle.execute_at))
    assert adopted == [cycle.cycle_id] and creates == [cycle.cycle_id]
    assert [route[0] for route in routes] == ['recover']
    assert result.cycle.last_fence_token == permit.fence_token and not transitions


def test_unrecognized_dependency_phase_never_calls_the_executor(monkeypatch):
    class UnknownPhase(Enum):
        UNKNOWN = 'UNKNOWN'
        @property
        def terminal(self):
            return False
    config = AutomationConfig()
    cycle, permit = scheduled_record(config, module.CycleState.DISCOVERED)
    # Only the external snapshot double can supply this unmodelled phase. The
    # real PostgreSQL/catalog/lineage guards independently reject such records.
    cycle = cycle.model_copy(update={'state': UnknownPhase.UNKNOWN})
    service, connection, routes, transitions, creates = tick_route(
        monkeypatch, cycle, permit, cycle.execute_at)
    result = asyncio.run(service.tick(connection, now=cycle.execute_at))
    assert result.action is module.TickAction.WAITING and result.cycle == cycle
    assert 'UNKNOWN' in result.reason
    assert creates == [cycle.cycle_id] and not routes and not transitions


def supervised_reader_double(monkeypatch, process, parent, child_channel, *, group_ready=True):
    ready = Ready()
    ready.wait = lambda **kwargs: ready.is_set()
    events = iter([Ready(), ready])
    process.start = ready.set if group_ready else lambda: None
    process_context = SimpleNamespace(Event=lambda: next(events),
        Pipe=lambda **kwargs: (parent, child_channel), Process=lambda **kwargs: process)

    class Worker:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass  # Child finishes before the first independent renewal wake.

        def join(self, **kwargs):
            pass

        def is_alive(self):
            return False

    def owned_group(pid, sig):
        assert pid == process.pid
        raise ProcessLookupError('owned test process is already absent')

    monkeypatch.setattr(module.threading, 'Thread', Worker)
    monkeypatch.setattr(module.multiprocessing, 'get_context', lambda _: process_context)
    monkeypatch.setattr(module.store, 'register_instance', lambda *a, **k: None)
    monkeypatch.setattr(module.os, 'killpg', owned_group)
    return lambda: SimpleNamespace(close=lambda: None)


def test_startup_without_owned_connection_refuses_before_child_or_registration(monkeypatch):
    process = Process(alive=False)
    parent, child_channel = Channel(), Channel()
    parent.poll = lambda: True
    parent.recv_bytes = lambda: b'{"kind":"result","value":"canonical packet"}'
    supervised_reader_double(monkeypatch, process, parent, child_channel)
    registrations = []
    # The invalid factory owns no resource; it cannot register liveness, launch
    # a child or accept the otherwise available canonical packet.
    monkeypatch.setattr(module.store, 'register_instance',
        lambda connection, **kwargs: registrations.append(connection))
    async def callback(_context):
        pytest.fail('parent executed the supervised child callback')
    service = module.AutomationService(config=AutomationConfig(), holder_id='no-startup-resource',
        refresh=callback, prepare=callback, recover=callback, execute=callback)
    context = Context()
    with pytest.raises(module.StaleLeaderRefused, match='no owned startup connection'):
        asyncio.run(service._invoke(callback, context, permit=None, phase='PREPARE',
            heartbeat_conn_factory=lambda: None))
    assert registrations == [] and not context.cancellation.cancelled
    assert not parent.closed and not child_channel.closed  # Never owned by invocation.
    assert not process.joins and not process.is_alive()


@pytest.mark.parametrize('mode', ['flushed_after_exit', 'empty_exit', 'read_eof'])
def test_exited_child_requires_its_actual_canonical_packet(monkeypatch, mode):
    process = Process(alive=False)
    process.exitcode = 0
    parent, child_channel = Channel(), Channel()
    polls = iter([False, mode == 'flushed_after_exit'])
    parent.poll = (lambda: True) if mode == 'read_eof' else lambda: next(polls)
    observation = {'disposition': 'SUCCEEDED', 'last_clean_reconciliation_id': 'packet-proof'}
    failure = EOFError('child channel closed before delivering a packet')

    def read():
        if mode == 'read_eof':
            raise failure
        return json.dumps({'kind': 'result', 'value': observation}).encode()

    parent.recv_bytes = read
    connect = supervised_reader_double(monkeypatch, process, parent, child_channel)

    async def callback(_context):
        pytest.fail('parent executed a child callback')

    context = Context()
    service = module.AutomationService(config=AutomationConfig(), holder_id='packet-race-lab',
        refresh=callback, prepare=callback, recover=callback, execute=callback)
    invocation = service._invoke(callback, context, permit=None,
        phase='RECOVER', heartbeat_conn_factory=connect)
    if mode == 'flushed_after_exit':
        assert asyncio.run(invocation) == observation
        assert not context.cancellation.cancelled
    elif mode == 'empty_exit':
        with pytest.raises(SoftwareDefect, match='exited without canonical result; exitcode='):
            asyncio.run(invocation)
    else:
        with pytest.raises(EOFError) as actual:
            asyncio.run(invocation)
        assert actual.value is failure
    assert parent.closed and child_channel.closed
    assert process.joins and not process.is_alive()


def test_unready_process_group_is_reaped_before_any_callback_result(monkeypatch):
    process = Process()
    parent, child_channel = Channel(), Channel()
    parent.poll = lambda: pytest.fail('unready child was allowed to supply authority')
    connect = supervised_reader_double(monkeypatch, process, parent, child_channel,
        group_ready=False)

    async def callback(_context):
        pytest.fail('unready callback ran')

    service = module.AutomationService(config=AutomationConfig(), holder_id='unready-group-lab',
        refresh=callback, prepare=callback, recover=callback, execute=callback)
    with pytest.raises(SoftwareDefect, match='process group did not become ready'):
        asyncio.run(service._invoke(callback, Context(), permit=None,
            phase='PREPARE', heartbeat_conn_factory=connect))
    assert process.kills == 1 and process.joins
    assert parent.closed and child_channel.closed and not process.is_alive()


def test_local_sync_adapter_awaits_its_result_without_production_process_authority():
    import threading
    events = []
    caller = threading.get_ident()

    async def result():
        events.append(('resolved', threading.get_ident()))
        return {'checked': 'local adapter result'}

    def callback(context):
        context.require_active()
        events.append(('called', threading.get_ident()))
        return result()

    service = module.AutomationService(config=AutomationConfig(), holder_id='local-adapter-lab',
        refresh=callback, prepare=callback, recover=callback, execute=callback)
    context = Context()
    assert asyncio.run(service._invoke(callback, context, permit=None, phase='PREPARE')) == {
        'checked': 'local adapter result'}
    assert [event[0] for event in events] == ['called', 'resolved']
    assert events[0][1] != caller and events[1][1] == caller
    assert not context.cancellation.cancelled
