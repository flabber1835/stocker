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
    AutomationConfig, CancellationAuthority, PermanentOperationalRefusal,
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


def scheduled_record(config, state):
    from sentinel.automation.model import CycleRecord, CycleSpec, LeaderPermit
    timing = module.schedule.for_decision_session(date(2026, 10, 8), config)
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
    if new_generation:
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


@pytest.mark.parametrize('initial', ['DISCOVERED', 'RETRY_WAIT'])
@pytest.mark.parametrize('supersede', [False, True])
@pytest.mark.parametrize('disposition', ['SUCCEEDED', 'SUPERSEDED', 'RETRY', 'BLOCKED'])
def test_preflight_recovery_must_finish_before_publication_and_never_executes(
        monkeypatch, initial, supersede, disposition):
    config = AutomationConfig()
    cycle, permit = scheduled_record(config, module.CycleState[initial])
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
        current = current.model_copy(update={'state': to_state, **fields})
        return current

    monkeypatch.setattr(module.store, 'transition_cycle', transition)
    result = asyncio.run(service._run_preflight_recover(connection, now=cycle.execute_at,
        cycle=cycle, permit=permit, supersede_on_success=supersede))
    stale_clean = supersede and disposition in {'SUCCEEDED', 'SUPERSEDED'}
    expected = ('SUPERSEDED' if stale_clean else 'REFRESHING_DATA' if disposition == 'SUCCEEDED'
                else 'BLOCKED' if disposition == 'BLOCKED' else 'RETRY_WAIT')
    assert result.cycle.state is module.CycleState[expected]
    assert events == ['read-only recovery']
    assert transitions[-1] is module.CycleState[expected]
    assert result.cycle.last_clean_reconciliation_id == observation.last_clean_reconciliation_id
    if stale_clean:
        assert result.action is module.TickAction.SUPERSEDED
        assert result.cycle.failure_code == 'STALE_PREFLIGHT_RECOVERED'
    elif disposition == 'SUCCEEDED':
        assert result.action is module.TickAction.RECOVERED
        assert result.cycle.diagnostic['preflight_recovery_complete'] is True
    elif disposition == 'BLOCKED':
        assert result.action is module.TickAction.BLOCKED
    else:
        assert result.action is module.TickAction.RETRY_SCHEDULED
        assert result.cycle.diagnostic['retry_phase'] == 'PREFLIGHT_RECOVER'
        assert result.cycle.next_wake_at > cycle.execute_at
