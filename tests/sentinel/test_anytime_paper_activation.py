"""Host anytime admission joined to the actual durable scheduler cutover."""
from datetime import datetime, timedelta, timezone
import inspect
import textwrap
from types import SimpleNamespace

import pytest

import sentinel_autonomous_deploy_install_entry as install
from sentinel.automation import store
from sentinel.automation.model import CycleState, TickAction
from sentinel.automation.service import AutomationService
from test_automation_service import (
    conn, pg, config, enable, service_for, prepare_result, refresh_result,
    recovery_success, execution_success, AFTER_WEDNESDAY_CLOSE,
    THURSDAY_BEFORE_OPEN, THURSDAY_AFTER_OPEN, THURSDAY_AFTER_CLOSE,
)

UTC = timezone.utc


def host(*, mode='dual', operational=True, **changes):
    obj = object.__new__(install.InstallAnytimeDeploy)
    obj.reviewed_validation = SimpleNamespace(mode=mode)
    obj._operational_source_only = operational
    obj._causal_timing = lambda: dict(
        dict(target='2026-08-12', frontier='2026-08-12',
             target_source_final=True, prospective=False, remaining_ms=0),
        **changes)
    return obj


@pytest.mark.parametrize('prospective,remaining', [(False, 0), (True, 1), (True, 60000)])
def test_operational_dual_activation_does_not_wait_for_an_open(prospective, remaining):
    host(prospective=prospective, remaining_ms=remaining).assert_activation_timing('2026-08-12')


@pytest.mark.parametrize('changes', [dict(target='2026-08-13'),
    dict(frontier='2026-08-11'), dict(target_source_final=False)])
def test_anytime_activation_retains_exact_current_source_and_decision(changes):
    with pytest.raises(install.core.ActivationPending):
        host(**changes).assert_activation_timing('2026-08-12')


@pytest.mark.parametrize('mode,operational', [('paper', True), ('dual', False)])
def test_historical_or_other_modes_do_not_gain_operational_admission(mode, operational):
    with pytest.raises(install.core.ActivationPending):
        host(mode=mode, operational=operational).assert_activation_timing('2026-08-12')


def test_reintroduced_host_clock_coupling_is_detected(monkeypatch):
    source = textwrap.dedent(inspect.getsource(install.InstallAnytimeDeploy.assert_activation_timing))
    source = source.replace('or not eligible', 'or not self._timing_eligible(timing)')
    namespace = {}
    exec(compile(source, 'old-activation-clock', 'exec'), install.__dict__, namespace)
    monkeypatch.setattr(install.InstallAnytimeDeploy, 'assert_activation_timing', namespace['assert_activation_timing'])
    with pytest.raises(install.core.ActivationPending):
        test_operational_dual_activation_does_not_wait_for_an_open(False, 0)


@pytest.mark.asyncio
@pytest.mark.parametrize('minute', [0, 1, 5, 9, 10, 90, 330])
async def test_intraday_activation_starts_control_but_never_same_open_callbacks(conn, minute):
    cfg = config()
    enable(conn, cfg)
    calls = []
    def forbidden(context):
        calls.append(context.cycle.cycle_id)
        raise AssertionError('late first obligation entered a callback')
    recovery_calls = []
    def recover(context):
        recovery_calls.append(context.cycle.cycle_id)
        return recovery_success(context)
    service = service_for(cfg, refresh=forbidden, prepare=forbidden,
                          recover=recover, execute=forbidden)
    now = THURSDAY_AFTER_OPEN - timedelta(minutes=1) + timedelta(minutes=minute)
    result = await service.tick(conn, now=now)
    assert result.action is TickAction.SUPERSEDED
    assert result.cycle.failure_code == 'DISCOVERED_AFTER_SESSION_OPEN'
    assert result.cycle.plan_id is None
    assert calls == []
    assert recovery_calls == [result.cycle.cycle_id]
    control = store.load_control(conn)
    assert control.enabled and not control.kill_switch_engaged
    # Durable terminal identity survives a replacement Python service.
    restarted = service_for(cfg, refresh=forbidden, prepare=forbidden,
                            recover=recover, execute=forbidden)
    again = await restarted.tick(conn, now=now)
    assert again.action is TickAction.WAITING
    assert again.cycle.cycle_id == result.cycle.cycle_id
    assert calls == []
    assert recovery_calls == [result.cycle.cycle_id]


@pytest.mark.asyncio
async def test_after_open_activation_advances_next_actual_decision(conn):
    cfg = config()
    enable(conn, cfg)
    service = service_for(cfg)
    skipped = await service.tick(conn, now=THURSDAY_AFTER_OPEN)
    assert skipped.action is TickAction.SUPERSEDED
    next_day = await service.tick(conn, now=THURSDAY_AFTER_CLOSE)
    assert next_day.action is TickAction.RECOVERED
    await service.tick(conn, now=THURSDAY_AFTER_CLOSE)
    prepared = await service.tick(conn, now=THURSDAY_AFTER_CLOSE)
    assert prepared.action is TickAction.PREPARED
    assert prepared.cycle.decision_session > skipped.cycle.decision_session
    assert prepared.cycle.effective_session > skipped.cycle.effective_session


@pytest.mark.asyncio
async def test_preopen_prepared_cycle_survives_restart_and_keeps_normal_execution(conn):
    cfg = config()
    enable(conn, cfg)
    service = service_for(cfg)
    await service.tick(conn, now=THURSDAY_BEFORE_OPEN)
    await service.tick(conn, now=THURSDAY_BEFORE_OPEN)
    prepared = await service.tick(conn, now=THURSDAY_BEFORE_OPEN)
    assert prepared.action is TickAction.PREPARED
    restarted = service_for(cfg)
    executed = await restarted.tick(conn, now=THURSDAY_AFTER_OPEN)
    assert executed.action is TickAction.EXECUTED
    assert executed.cycle.plan_id == prepared.cycle.plan_id


@pytest.mark.asyncio
async def test_open_crossed_before_first_preflight_is_state_only(conn):
    cfg = config()
    enable(conn, cfg)
    service = service_for(cfg)
    permit = store.acquire_lease(conn, holder_id=service.holder_id, lease_seconds=30)
    from sentinel.automation import schedule
    discovered = store.create_cycle(conn, permit=permit,
        spec=service._spec(store.load_control(conn), schedule.for_clock(THURSDAY_BEFORE_OPEN, cfg)))
    result = await service.tick(conn, now=THURSDAY_AFTER_OPEN)
    assert result.action is TickAction.SUPERSEDED
    assert result.cycle.cycle_id == discovered.cycle_id


@pytest.mark.asyncio
async def test_uncertain_transport_recovery_precedes_anytime_cutover(conn):
    cfg = config()
    enable(conn, cfg)
    service = service_for(cfg, execute=lambda context: {
        'disposition': 'RECONCILE', 'failure_code': 'UNKNOWN_TRANSPORT'})
    for _ in range(3):
        await service.tick(conn, now=THURSDAY_BEFORE_OPEN)
    transported = await service.tick(conn, now=THURSDAY_AFTER_OPEN)
    assert transported.cycle.state is CycleState.RECONCILING
    control = store.load_control(conn)
    expected = control.binding
    store.deactivate(conn, actor='fixture', reason='software upgrade')
    store.activate(conn, binding=expected, actor='fixture', reason='new release')
    store.release_kill(conn, expected_binding=expected, actor='fixture', reason='restore proven')
    calls = []
    def recovery(context):
        calls.append(context.cycle.plan_id)
        return recovery_success(context)
    def forbidden(context):
        raise AssertionError('new transport replaced an uncertain prior obligation')
    resumed = service_for(cfg, recover=recovery, execute=forbidden)
    result = await resumed.tick(conn, now=THURSDAY_AFTER_OPEN)
    assert result.action is TickAction.RECOVERED
    assert calls == [transported.cycle.plan_id]
    assert result.cycle.cycle_id == transported.cycle.cycle_id


@pytest.mark.asyncio
@pytest.mark.parametrize('now', [datetime(2026, 8, 14, 22, tzinfo=UTC),
    datetime(2026, 8, 15, 18, tzinfo=UTC), datetime(2026, 8, 16, 18, tzinfo=UTC)])
async def test_postclose_and_weekend_activation_prepares_a_future_actual_open(conn, now):
    cfg = config()
    enable(conn, cfg)
    service = service_for(cfg)
    assert (await service.tick(conn, now=now)).action is TickAction.RECOVERED
    await service.tick(conn, now=now)
    result = await service.tick(conn, now=now)
    assert result.action is TickAction.PREPARED
    assert result.cycle.execution_open_at > now


@pytest.mark.asyncio
async def test_pending_shared_journal_is_not_discarded_by_open_cutover(conn):
    cfg = config()
    enable(conn, cfg)
    replies = iter([{'disposition': 'RETRY', 'failure_code': 'UNKNOWN_TRANSPORT'}, None])
    calls = []
    def recover(context):
        calls.append(context.cycle.cycle_id)
        return next(replies) or recovery_success(context)
    service = service_for(cfg, recover=recover)
    pending = await service.tick(conn, now=THURSDAY_AFTER_OPEN)
    assert pending.action is TickAction.RETRY_SCHEDULED
    assert pending.cycle.state is CycleState.RETRY_WAIT
    completed = await service.tick(conn, now=THURSDAY_AFTER_OPEN+timedelta(seconds=6))
    assert completed.action is TickAction.SUPERSEDED
    assert completed.cycle.failure_code == 'DISCOVERED_AFTER_SESSION_OPEN'
    assert completed.cycle.plan_id is None
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_removed_scheduler_cutover_is_detected(conn, monkeypatch):
    import sentinel.automation.service as module
    source = textwrap.dedent(inspect.getsource(AutomationService._run_preflight_recover)).replace(
        'and now >= cycle.execution_open_at)', 'and False)')
    namespace = {}
    exec(compile(source, 'removed-cycle-cutover', 'exec'), module.__dict__, namespace)
    monkeypatch.setattr(AutomationService, '_run_preflight_recover', namespace['_run_preflight_recover'])
    with pytest.raises(AssertionError):
        await test_intraday_activation_starts_control_but_never_same_open_callbacks(conn, 1)
