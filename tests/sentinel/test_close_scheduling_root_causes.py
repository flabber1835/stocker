"""The closing source handoff owns only its existing prospective obligation."""
import asyncio
from datetime import datetime, timedelta, timezone
import inspect
import textwrap
from types import SimpleNamespace

import pytest

from sentinel import automation_runtime as runtime, shadow_supervisor as supervisor
from sentinel.automation import service
from sentinel.automation.model import (
    ClosingDataPending, CycleState, NonRetryableCallbackRefused,
    RefreshPublicationPinUnavailable, TickAction,
)
from sentinel.automation_resilience import RecoveryAutomationService
from sentinel.dual_reconciliation import DualReconciliationRefused
from sentinel.feed import calendar, operational_snapshot, rolling_store
from sentinel.feed.publication import CORPUS_LOCK_KEY
from tests.sentinel.test_automation_service import (
    AFTER_WEDNESDAY_CLOSE, config, enable, execution_success, prepare_result, refresh_result,
)
from tests.sentinel.test_automation_service_fault_paths import child
from tests.sentinel.test_closing_data_notifications import closing_cycle
from tests.sentinel.test_source_completion_wake import (
    DECISION, attest, conn, pg, publications, publish, read_hint,
)


def refresh_runtime(monkeypatch, *, cfg, now, connection):
    worker = object.__new__(runtime.ProductionAutomation)
    worker.automation_config = cfg
    worker.sentinel_config = SimpleNamespace(database_url='private-test-db')
    worker._dual_run_enabled = worker._operational_source_only = True
    worker._shadow_observation_id = 'primary'
    worker._shadow_starting_cash = 50000
    worker.connect = connection
    worker._assert_cycle_authority = lambda _conn, context, **_kw: (context.cycle, None)
    monkeypatch.setattr(runtime.feed_store, 'require_feed_schema', lambda _conn: None)
    monkeypatch.setattr(runtime.schema, 'require_runtime_schema', lambda _conn: None)
    monkeypatch.setattr(runtime, 'require_observation_integrity', lambda _conn: None)
    monkeypatch.setattr(runtime, '_now_utc', now)
    return worker


@pytest.mark.asyncio
@pytest.mark.parametrize('omit', [None, 'pin_budget', 'pin_hint', 'consume_hint'])
async def test_publication_pin_handoff_keeps_its_own_retry_and_consumes_each_hint_once(
        publications, pg, monkeypatch, omit):
    cfg = config().model_copy(update={'retry_base_seconds': 10, 'retry_max_seconds': 900})
    enable(publications, cfg)
    now = AFTER_WEDNESDAY_CLOSE
    worker = refresh_runtime(monkeypatch, cfg=cfg, now=lambda: now,
                            connection=lambda: runtime.feed_store.connect(pg.sync_dsn))
    worker.sentinel_config.database_url = pg.sync_dsn
    from sentinel import source_publication_wait
    monkeypatch.setattr(source_publication_wait, 'observe', lambda *a, **kw: None)
    monkeypatch.setattr(runtime.feed_inputs, 'current', rolling_store._pin_reader)

    calls, reads = [], []

    def hint(cycle):
        reads.append(cycle.cycle_id)
        return read_hint(pg.sync_dsn, decision_session=cycle.decision_session)

    async def refresh(context):
        calls.append(context.cycle.cycle_id)
        if len(calls) <= 8:
            raise ClosingDataPending('the previous signed source is still current')
        if len(calls) <= 10:
            with pytest.raises(RefreshPublicationPinUnavailable) as failure:
                await worker.refresh(context)
            # Exercise the real callback envelope without creating a second owner.
            async def refused(_context):
                raise failure.value
            with monkeypatch.context() as wire:
                channel = await asyncio.to_thread(child, wire, refused)
            service._decode_child_callback(channel.payloads[0])
        return refresh_result(context)

    def running():
        return RecoveryAutomationService(
            config=cfg, holder_id='worker-a', refresh=refresh, prepare=prepare_result,
            recover=execution_success, execute=execution_success, source_completion_hint=hint)

    def mutate(name, old, new):
        original = getattr(service.AutomationService, name)
        source = textwrap.dedent(inspect.getsource(original))
        assert source.count(old) == 1
        namespace = {}
        exec(source.replace(old, new), vars(service), namespace)
        monkeypatch.setattr(service.AutomationService, name, namespace[name])

    if omit == 'pin_budget':
        mutate('_record_retry', 'classified.get("publication_pin_attempt_count",',
               'classified.get("phase_attempt_count",')
    elif omit == 'pin_hint':
        mutate('_advanced_source_completion',
               'and cycle.failure_code == RefreshPublicationPinUnavailable.__name__', 'and False')
    elif omit == 'consume_hint':
        mutate('_run_refresh', 'advancing_source or self._source_completion(cycle)',
               'self._source_completion(cycle)')

    async def exercise():
        nonlocal now
        supervisor_service = running()
        assert (await supervisor_service.tick(publications, now=now)).action is TickAction.RECOVERED
        for _ in range(8):
            result = await supervisor_service.tick(publications, now=now)
            assert result.action is TickAction.RETRY_SCHEDULED
            if len(calls) < 8:
                now = result.cycle.next_wake_at
        assert result.cycle.next_wake_at == now + timedelta(seconds=900)
        original = result.cycle
        now += timedelta(seconds=1)
        publish(publications)
        with runtime.feed_store.connect(pg.sync_dsn) as writer:
            writer.execute('SELECT pg_advisory_lock(%s)', (CORPUS_LOCK_KEY,))
            before = len(reads)
            pin = await supervisor_service.tick(publications, now=now)
            assert len(reads) == before + 1, 'the advancing producer token was read twice'
            assert pin.action is TickAction.RETRY_SCHEDULED
            assert pin.cycle.diagnostic['callback_failure'] == 'TRANSIENT_INFRASTRUCTURE'
            assert 'closing_data_wait' not in pin.cycle.diagnostic
            assert pin.cycle.diagnostic['phase_attempt_count'] == 9
            assert pin.cycle.diagnostic['publication_pin_attempt_count'] == 1
            assert pin.cycle.next_wake_at == now + timedelta(seconds=10), 'the old source delay was inherited'
            assert pin.cycle.diagnostic['source_completion_hint']['publication_frontier'] == str(DECISION)
            for _ in range(3):
                assert (await supervisor_service.tick(publications, now=now)).action is TickAction.WAITING
            assert len(calls) == 9
            now = pin.cycle.next_wake_at
            again = await supervisor_service.tick(publications, now=now)
            assert again.cycle.diagnostic['publication_pin_attempt_count'] == 2
            assert again.cycle.next_wake_at == now + timedelta(seconds=20)
            writer.execute('SELECT pg_advisory_unlock(%s)', (CORPUS_LOCK_KEY,))
        attest(publications, observation_id='foreign')
        assert (await supervisor_service.tick(publications, now=now)).action is TickAction.WAITING
        attest(publications)
        now += timedelta(seconds=1)
        assert supervisor_service._advanced_source_completion(
            again.cycle, now=original.execution_open_at) is None
        wrong = again.cycle.model_copy(update={'diagnostic': {
            **again.cycle.diagnostic, 'exception_type': 'some_other_pin_exception'}})
        assert supervisor_service._advanced_source_completion(wrong, now=now) is None
        complete = await running().tick(publications, now=now)
        assert complete.action is TickAction.REFRESHED, 'matching attestation could not wake exact pin retry'
        assert len(calls) == 11
        assert complete.cycle.cycle_id == original.cycle_id
        assert complete.cycle.decision_close_at == original.decision_close_at
        assert complete.cycle.execute_at == original.execute_at
        assert complete.cycle.execution_close_at == original.execution_close_at
        assert complete.cycle.plan_id is None

    if omit is None:
        await exercise()
    else:
        message = {'pin_budget': 'old source delay', 'pin_hint': 'matching attestation',
                   'consume_hint': 'token was read twice'}[omit]
        with pytest.raises(AssertionError, match=message):
            await exercise()


@pytest.mark.parametrize('condition', ['exact', 'legacy', 'older', 'target', 'ahead', 'bad_provider',
                                       'future_clock', 'at_open', 'moved_close', 'plan_present',
                                       'missing_frontier', 'omit_adjacency'])
def test_old_book_is_skipped_only_by_the_authenticated_adjacent_frontier(monkeypatch, condition):
    from sentinel import dual_reconciliation

    cfg, cycle, _permit = closing_cycle()
    now = cycle.prepare_at + timedelta(seconds=1)
    if condition == 'future_clock':
        now = cycle.decision_close_at - timedelta(seconds=1)
    elif condition == 'at_open':
        now = cycle.execution_open_at
    elif condition == 'moved_close':
        cycle = cycle.model_copy(update={'decision_close_at': cycle.decision_close_at - timedelta(seconds=1)})
    elif condition == 'plan_present':
        cycle = cycle.model_copy(update={'plan_id': 'existing'})
    calls = []
    connection = SimpleNamespace(close=lambda: calls.append('closed'))
    worker = refresh_runtime(monkeypatch, cfg=cfg, now=lambda: now, connection=lambda: connection)
    worker._operational_source_only = condition != 'legacy'
    worker.sentinel_config = None
    frontier = {'older': '2026-10-23', 'omit_adjacency': '2026-10-23', 'target': '2026-10-27',
                'ahead': '2026-10-28', 'missing_frontier': None}.get(condition, '2026-10-26')
    monkeypatch.setattr(runtime.feed_inputs, 'current', lambda _conn: SimpleNamespace(window_end=frontier))
    monkeypatch.setattr(runtime.feed_inputs, 'is_rolling', lambda _pub: True)

    def provider(_conn, _pub):
        calls.append('provider')
        if condition == 'bad_provider':
            raise operational_snapshot.OperationalSnapshotRefused('wrong provider')

    def verify(_conn, **_kw):
        calls.append('old book')
        raise DualReconciliationRefused('canonical proof refused')

    monkeypatch.setattr(operational_snapshot, 'require_alpaca_openfigi', provider)
    monkeypatch.setattr(dual_reconciliation, 'verified_shadow_intent', verify)
    if condition == 'omit_adjacency':
        source = textwrap.dedent(inspect.getsource(runtime.ProductionAutomation._closing_refresh_wait))
        guard = 'if frontier == calendar.latest_closed_session(before_close):'
        assert source.count(guard) == 1
        namespace = {}
        exec(source.replace(guard, 'if True:'), vars(runtime), namespace)
        monkeypatch.setattr(runtime.ProductionAutomation, '_closing_refresh_wait', namespace['_closing_refresh_wait'])
        with pytest.raises(AssertionError):
            with pytest.raises(ClosingDataPending):
                asyncio.run(worker.refresh(SimpleNamespace(cycle=cycle)))
            assert calls == ['provider', 'old book', 'closed']
        return
    failure = ClosingDataPending if condition == 'exact' else NonRetryableCallbackRefused
    with pytest.raises(failure):
        asyncio.run(worker.refresh(SimpleNamespace(cycle=cycle)))
    expected = [] if condition == 'legacy' else ['provider']
    if condition not in {'exact', 'bad_provider'}:
        expected.append('old book')
    assert calls == [*expected, 'closed']


@pytest.mark.parametrize('started, expected', [
    ('2026-11-10T20:59:55+00:00', '2026-11-10T21:00:00+00:00'),
    ('2026-11-10T21:00:00+00:00', '2026-11-11T21:00:00+00:00'),
    ('2026-11-26T20:59:55+00:00', '2026-11-27T18:00:00+00:00'),
    ('2026-11-27T17:59:55+00:00', '2026-11-27T18:00:00+00:00'),
])
def test_publisher_wake_uses_actual_exchange_close(started, expected):
    assert supervisor._next_acquisition_close(datetime.fromisoformat(started)).isoformat() == expected


def test_unavailable_calendar_retains_routine_wake(monkeypatch):
    def unavailable(_instant):
        raise calendar.CalendarUnavailable('no calendar')
    monkeypatch.setattr(supervisor.observation_timing, 'latest_acquirable_session', unavailable)
    assert supervisor._next_acquisition_close(datetime.now(timezone.utc)) is None


@pytest.mark.parametrize('operational, omit, busy', [
    (True, False, False), (False, False, False), (True, True, False), (True, False, True),
])
def test_actual_supervisor_launches_once_at_close_then_resumes_routine_poll(monkeypatch, operational, omit, busy):
    started = datetime.fromisoformat('2026-11-10T20:59:55+00:00')
    clock, launches, signals = [0.0], [], {}
    monkeypatch.setattr(supervisor.ShadowServiceConfig, 'from_env', lambda: SimpleNamespace(
        poll_seconds=300, operational_source_only=operational, database_url='isolated'))
    monkeypatch.setattr(supervisor.shadow_budget, 'now', lambda: started + timedelta(seconds=clock[0]))
    monkeypatch.setattr(supervisor.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(supervisor.time, 'sleep', lambda delay: clock.__setitem__(0, clock[0] + delay))
    monkeypatch.setattr(supervisor, '_Heartbeat', lambda: lambda: None)
    monkeypatch.setattr(supervisor, '_diagnostic', lambda *a, **kw: None)
    monkeypatch.setattr(supervisor, '_latch_exists', lambda: False)
    monkeypatch.setattr(supervisor, '_arm_worker', lambda _pid: 'same-owner')
    monkeypatch.setattr(supervisor, '_clear_worker', lambda: None)
    monkeypatch.setattr(supervisor, '_dependency_retry_alert', lambda: None)
    monkeypatch.setattr(supervisor, '_remove_heartbeat', lambda: None)
    monkeypatch.setattr(supervisor.shadow_worker_liveness, 'clear', lambda: None)
    monkeypatch.setattr(supervisor.supervisor_io, 'run', lambda fn, *a, **kw: fn(*a))
    monkeypatch.setattr(supervisor.signal, 'signal', lambda signal, callback: signals.update({signal: callback}))
    from sentinel import backup_retry
    def completed(database_url, failed_at):
        assert database_url == 'isolated' and failed_at == started + timedelta(seconds=5)
        return clock[0] == 15
    monkeypatch.setattr(backup_retry, 'completed_since', completed)

    def launch(*_a, **kwargs):
        assert kwargs['pass_fds'] == (42,)
        launches.append(clock[0])
        if len(launches) == 3:
            signals[supervisor.signal.SIGTERM]()
        if busy and len(launches) == 2:
            return SimpleNamespace(poll=lambda: supervisor.EXIT_BACKUP_PROOF_BUSY)
        return SimpleNamespace(poll=lambda: 0)

    monkeypatch.setattr(supervisor.subprocess, 'Popen', launch)
    if omit:
        monkeypatch.setattr(supervisor, '_next_acquisition_close', lambda _started: None)
    assert supervisor._run_owned(42) == 0
    if busy:
        assert launches == [0, 5, 15]
    elif not operational:
        assert launches == [0, 300, 600]
    elif omit:
        with pytest.raises(AssertionError):
            assert launches == [0, 5, 305]
    else:
        assert launches == [0, 5, 305]
