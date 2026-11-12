"""Exact unsent publication interval recovery retains every ordinary gate."""
import inspect
from types import SimpleNamespace

import pytest

from sentinel.automation import store, unsent_recovery as recovery
from sentinel.automation.model import AutomationRefused, CycleState
from sentinel import backup_runtime_authority
from tests.sentinel.test_automation_service import (pg, conn, config, enable, recovery_success,
    refresh_result, service_for)
from tests.sentinel.test_automation_generation import future_friday
from tests.sentinel.test_unsent_cycle_recovery import authorize, release

DEPLOYED_POLICY_MARKER = backup_runtime_authority.POLICY_MARKER


@pytest.fixture(autouse=True)
def private_scheduling_policy(tmp_path, monkeypatch):
    """Scheduling fixtures have no external WAL media; production is unchanged."""
    monkeypatch.setattr(backup_runtime_authority, 'POLICY_MARKER', tmp_path/'absent-policy')


def blocked(conn, monkeypatch):
    cfg = config()
    enable(conn, cfg)
    service = service_for(cfg)
    timing, now = future_friday(conn, cfg)
    monkeypatch.setattr(recovery.calendar, 'latest_closed_session', lambda _: str(timing.decision_session))
    permit = store.acquire_lease(conn, holder_id='worker-a', lease_seconds=30)
    cycle = store.create_cycle(conn, permit=permit, spec=service._spec(store.load_control(conn), timing))
    cycle = store.transition_cycle(conn, permit=permit, cycle_id=cycle.cycle_id,
                                  to_state=CycleState.REFRESHING_DATA)
    cycle = store.transition_cycle(conn, permit=permit, cycle_id=cycle.cycle_id,
        to_state=CycleState.BLOCKED, failure_code='NonRetryableCallbackRefused',
        failure_detail=recovery.PUBLICATION_CHANGED_FAILURE,
        diagnostic={'retry_phase': 'REFRESH', 'callback_failure': 'PERMANENT_OPERATIONAL_REFUSAL',
                    'terminal_reason': 'PERMANENT_OPERATIONAL_REFUSAL',
                    'exception_type': 'sentinel.automation.model.NonRetryableCallbackRefused'})
    store.engage_kill(conn, actor='test', reason='reviewed publication interval incident')
    return cfg, service, timing, now, cycle


@pytest.mark.asyncio
async def test_recovery_creates_fresh_plan_without_mutating_or_replaying_failed_cycle(conn, monkeypatch):
    cfg, service, timing, now, old = blocked(conn, monkeypatch)
    events = conn.execute('SELECT * FROM sentinel_automation_cycle_events WHERE cycle_id=%s ORDER BY seq',
                          (old.cycle_id,)).fetchall()
    conn.rollback()
    generation, auth = authorize(conn, cfg, timing, now, old)
    assert auth.kind == recovery.PUBLICATION_CHANGED_KIND
    assert authorize(conn, cfg, timing, now, old) == (generation, auth)
    assert recovery.decode_authorization(auth.model_dump(mode='json', by_alias=True)) == auth
    release(conn)
    for _ in range(12):
        result = await service.tick(conn, now=now)
        if result.cycle and result.cycle.state is CycleState.WAITING_OPEN:
            break
    assert result.cycle.state is CycleState.WAITING_OPEN
    assert result.cycle.cycle_id != old.cycle_id and result.cycle.plan_id is not None
    assert store.load_cycle(conn, old.cycle_id) == old
    assert conn.execute('SELECT * FROM sentinel_automation_cycle_events WHERE cycle_id=%s ORDER BY seq',
                        (old.cycle_id,)).fetchall() == events
    assert conn.execute('SELECT COUNT(*) FROM sentinel_commands').fetchone()[0] == 0
    assert (await service_for(cfg, holder='worker-a').tick(conn, now=now)).cycle.cycle_id == result.cycle.cycle_id


@pytest.mark.parametrize('field,value', [
    ('state', CycleState.RETRY_WAIT), ('historical_state_only', True), ('plan_id', 'old-plan'),
    ('failure_code', 'SoftwareDefect'), ('failure_detail', recovery.PUBLICATION_CHANGED_FAILURE+' extra'),
    ('failure_detail', 'ROLLING_RUNTIME_SNAPSHOT_CHANGED'), ('retry_phase', 'PREPARE'),
    ('callback_failure', 'SOFTWARE_DEFECT'), ('terminal_reason', 'SOFTWARE_DEFECT'),
    ('exception_type', 'other.NonRetryableCallbackRefused'),
])
def test_only_exact_reviewed_unprepared_failure_is_eligible(conn, monkeypatch, field, value):
    _, _, _, _, old = blocked(conn, monkeypatch)
    assert recovery.eligible_kind(old) == recovery.PUBLICATION_CHANGED_KIND
    update = {'diagnostic': dict(old.diagnostic, **{field: value})} if field in old.diagnostic else {field: value}
    assert recovery.eligible_kind(old.model_copy(update=update)) is None


@pytest.mark.parametrize('fault', ['kill_released', 'live_leader', 'open', 'transport', 'unknown_command'])
def test_original_unsent_and_operator_fences_still_refuse_recovery(conn, monkeypatch, fault):
    cfg, _, timing, now, old = blocked(conn, monkeypatch)
    if fault == 'kill_released':
        control = store.load_control(conn)
        store.release_kill(conn, expected_binding=control.binding, actor='test', reason='early')
    elif fault == 'live_leader':
        conn.execute("UPDATE sentinel_automation_lease SET holder_id='foreign',"
                     "control_generation=%s,acquired_at=clock_timestamp(),heartbeat_at=clock_timestamp(),"
                     "expires_at=clock_timestamp()+interval '1 hour' WHERE id=1",
                     (store.load_control(conn).generation,))
        conn.commit()
    elif fault == 'open':
        now = timing.execution_open_at
    elif fault == 'transport':
        conn.execute("INSERT INTO sentinel_automation_cycle_events (cycle_id,from_state,to_state,control_generation,fence_token,detail) "
                     "VALUES (%s,'EXECUTING','RECONCILING',%s,%s,'{}')",
                     (old.cycle_id, old.control_generation, old.last_fence_token))
        conn.commit()
    else:
        conn.execute("INSERT INTO sentinel_commands (client_key,plan_id,security_id,deployment_id,broker,broker_account_id,"
                     "takeover_epoch,symbol,side,quantity,state) VALUES ('sent','old-plan','s','sentinel-a','alpaca-paper',"
                     "'paper-account-1',1,'TEST','BUY',1,'UNKNOWN')")
        conn.commit()
    with pytest.raises(AutomationRefused):
        authorize(conn, cfg, timing, now, old)


def test_recovery_keeps_the_real_deployed_backup_fence(conn, monkeypatch):
    cfg, _, timing, now, old = blocked(conn, monkeypatch)
    monkeypatch.setattr(backup_runtime_authority, 'POLICY_MARKER', DEPLOYED_POLICY_MARKER)
    monkeypatch.setenv('SENTINEL_RUNTIME_BACKUP_AUTHORITY', 'REQUIRED_V1')
    with pytest.raises(backup_runtime_authority.BackupRuntimeRefused):
        authorize(conn, cfg, timing, now, old)


def test_removed_exact_failure_guard_is_detected(conn, monkeypatch):
    source = inspect.getsource(recovery.eligible_kind)
    line = 'cycle.failure_detail == PUBLICATION_CHANGED_FAILURE'
    assert source.count(line) == 1
    namespace = dict(vars(recovery))
    exec(compile(source.replace(line, 'True'), '<unsent-failure-falsifier>', 'exec'), namespace)
    monkeypatch.setattr(recovery, 'eligible_kind', namespace['eligible_kind'])
    with pytest.raises(AssertionError):
        test_only_exact_reviewed_unprepared_failure_is_eligible(conn, monkeypatch,
            'failure_detail', recovery.PUBLICATION_CHANGED_FAILURE+' extra')


def prepare_cash_correction_block():
    return SimpleNamespace(state=CycleState.BLOCKED, historical_state_only=False, plan_id=None,
        failure_code='SoftwareDefect', failure_detail=recovery.PREPARE_CASH_CORRECTION_FAILURE,
        diagnostic=dict(retry_phase='PREPARE', callback_failure='SOFTWARE_DEFECT',
            terminal_reason='SOFTWARE_DEFECT', exception_type='sentinel.automation.model.SoftwareDefect'))


@pytest.mark.parametrize('field,value', [
    ('state', CycleState.RETRY_WAIT), ('historical_state_only', True), ('plan_id', 'old-plan'),
    ('failure_code', 'NonRetryableCallbackRefused'),
    ('failure_detail', recovery.PREPARE_CASH_CORRECTION_FAILURE+' extra'),
    ('failure_detail', 'unreviewed callback exception builtins.ValueError: CASH_CORRECTION_MARKER_CHANGED'),
    ('retry_phase', 'PREFLIGHT_RECOVER'), ('callback_failure', 'TRANSIENT_INFRASTRUCTURE'),
    ('terminal_reason', None), ('exception_type', 'builtins.ValueError'),
])
def test_prepare_cash_correction_recovery_requires_exact_planless_signature(field, value):
    block = prepare_cash_correction_block()
    assert recovery.eligible_kind(block) == recovery.PREPARE_CASH_CORRECTION_KIND
    if field in block.diagnostic:
        block.diagnostic[field] = value
    else:
        setattr(block, field, value)
    assert recovery.eligible_kind(block) is None


def test_removed_prepare_cash_correction_signature_guard_is_detected(monkeypatch):
    source = inspect.getsource(recovery.eligible_kind)
    line = 'cycle.failure_detail == PREPARE_CASH_CORRECTION_FAILURE'
    assert source.count(line) == 1
    namespace = dict(vars(recovery))
    exec(compile(source.replace(line, 'True'), '<cash-correction-recovery-falsifier>', 'exec'), namespace)
    monkeypatch.setattr(recovery, 'eligible_kind', namespace['eligible_kind'])
    with pytest.raises(AssertionError):
        test_prepare_cash_correction_recovery_requires_exact_planless_signature(
            'failure_detail', recovery.PREPARE_CASH_CORRECTION_FAILURE+' extra')


@pytest.mark.asyncio
async def test_prepare_cash_correction_block_replays_latest_close_under_new_authority(conn, monkeypatch):
    cfg = config()
    enable(conn, cfg)
    timing, now = future_friday(conn, cfg)
    monkeypatch.setattr(recovery.calendar, 'latest_closed_session', lambda _: str(timing.decision_session))

    async def prepare_failed(_):
        raise ValueError('CASH_CORRECTION_ORIGINAL_LINK_CHANGED')

    async def use_current_publication(context):
        return {**refresh_result(context), 'already_published': True}

    async def reconcile_cleanly(context):
        return recovery_success(context)

    async def execute_early(_):
        pytest.fail('before-open recovery must not invoke execution')

    def heartbeat_conn():
        from sentinel.feed import store as feed_store
        return feed_store.connect(conn.info.dsn)

    failed_service = service_for(cfg, refresh=use_current_publication, prepare=prepare_failed,
        recover=reconcile_cleanly, execute=execute_early)
    for _ in range(12):
        blocked = (await failed_service.tick(conn, now=now, heartbeat_conn_factory=heartbeat_conn)).cycle
        if blocked.state is CycleState.BLOCKED:
            break
    assert blocked.state is CycleState.BLOCKED and blocked.plan_id is None
    assert blocked.data_version == f'publication-{timing.decision_session}', blocked.failure_detail
    assert recovery.eligible_kind(blocked) == recovery.PREPARE_CASH_CORRECTION_KIND
    events = conn.execute('SELECT * FROM sentinel_automation_cycle_events WHERE cycle_id=%s ORDER BY seq',
                          (blocked.cycle_id,)).fetchall()
    conn.rollback()
    store.engage_kill(conn, actor='operator', reason='cash-correction incident')
    generation, auth = authorize(conn, cfg, timing, now, blocked)
    assert auth.kind == recovery.PREPARE_CASH_CORRECTION_KIND
    assert authorize(conn, cfg, timing, now, blocked) == (generation, auth)
    assert recovery.decode_authorization(auth.model_dump(mode='json', by_alias=True)) == auth
    release(conn)

    repaired_service = service_for(cfg, refresh=use_current_publication, execute=execute_early)
    for _ in range(12):
        replacement = (await repaired_service.tick(conn, now=now)).cycle
        if replacement.state is CycleState.WAITING_OPEN:
            break
    assert replacement.state is CycleState.WAITING_OPEN
    assert replacement.control_generation == generation + 1 and replacement.cycle_id != blocked.cycle_id
    assert replacement.plan_id and replacement.data_version == blocked.data_version
    assert store.load_cycle(conn, blocked.cycle_id) == blocked
    assert conn.execute('SELECT * FROM sentinel_automation_cycle_events WHERE cycle_id=%s ORDER BY seq',
                        (blocked.cycle_id,)).fetchall() == events
    assert conn.execute('SELECT COUNT(*) FROM sentinel_commands').fetchone()[0] == 0
