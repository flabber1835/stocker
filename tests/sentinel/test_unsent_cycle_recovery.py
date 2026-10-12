"""Actual PostgreSQL recovery, immutable history and transport falsifiers."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from types import SimpleNamespace

import psycopg
import pytest

from sentinel.automation import integrity, schedule, store, unsent_recovery as recovery
from sentinel.automation.model import AutomationRefused, CycleState, ProspectiveReplacementRefused
from tests.sentinel.test_automation_service import pg, conn, config, enable, service_for
from tests.sentinel.test_automation_generation import future_friday


def blocked(conn, monkeypatch, *, cause='CorpusLockUnavailable', transported=False):
    cfg = config()
    enable(conn, cfg)
    service = service_for(cfg)
    timing, now = future_friday(conn, cfg)
    monkeypatch.setattr(recovery.calendar, 'latest_closed_session', lambda _: str(timing.decision_session))
    permit = store.acquire_lease(conn, holder_id='worker-a', lease_seconds=30)
    spec = service._spec(store.load_control(conn), timing)
    cycle = store.create_cycle(conn, permit=permit, spec=spec)
    for state in (CycleState.PREPARING, CycleState.PLAN_READY, CycleState.WAITING_OPEN):
        cycle = store.transition_cycle(conn, permit=permit, cycle_id=cycle.cycle_id, to_state=state,
            **({'plan_id': 'old-plan'} if state is CycleState.PLAN_READY else {}))
    if transported:
        cycle = store.transition_cycle(conn, permit=permit, cycle_id=cycle.cycle_id,
                                       to_state=CycleState.EXECUTING)
    cycle = store.transition_cycle(conn, permit=permit, cycle_id=cycle.cycle_id,
        to_state=CycleState.BLOCKED, failure_code='NonRetryableCallbackRefused',
        failure_detail='automation authority/integrity refusal: ' + cause + ': temporary dependency',
        diagnostic={'control_poll_failure': 'NONRETRYABLE'})
    store.engage_kill(conn, actor='test', reason='incident')
    return cfg, service, timing, now, cycle


def authorize(conn, cfg, timing, now, cycle):
    return recovery.authorize(conn, binding=store.load_control(conn).binding,
        decision_session=timing.decision_session, blocked_cycle_id=cycle.cycle_id,
        actor='operator', reason='reviewed temporary failure', now=now,
        automation_config=cfg)


def release(conn):
    control = store.load_control(conn)
    store.release_kill(conn, expected_binding=control.binding, actor='operator', reason='fresh checks passed')
    return store.acquire_lease(conn, holder_id='worker-a', lease_seconds=30)


def preflight_blocked(conn, monkeypatch):
    cfg = config()
    enable(conn, cfg)
    service = service_for(cfg)
    timing, now = future_friday(conn, cfg)
    monkeypatch.setattr(recovery.calendar, 'latest_closed_session', lambda _: str(timing.decision_session))
    permit = store.acquire_lease(conn, holder_id='worker-a', lease_seconds=30)
    cycle = store.create_cycle(conn, permit=permit, spec=service._spec(store.load_control(conn), timing))
    cycle = store.transition_cycle(conn, permit=permit, cycle_id=cycle.cycle_id,
        to_state=CycleState.BLOCKED, failure_code='SoftwareDefect',
        failure_detail=recovery.PREFLIGHT_FAILURE,
        diagnostic={'retry_phase': 'PREFLIGHT_RECOVER', 'callback_failure': 'SOFTWARE_DEFECT',
                    'terminal_reason': 'SOFTWARE_DEFECT',
                    'exception_type': 'sentinel.automation.model.SoftwareDefect'})
    store.engage_kill(conn, actor='test', reason='reviewed preflight incident')
    return cfg, service, timing, now, cycle


@pytest.mark.asyncio
async def test_preflight_unsent_recovery_preserves_failed_history_and_reaches_waiting_open(conn, monkeypatch):
    cfg, service, timing, now, old = preflight_blocked(conn, monkeypatch)
    events = conn.execute('SELECT * FROM sentinel_automation_cycle_events ORDER BY seq').fetchall()
    conn.rollback()
    generation, auth = authorize(conn, cfg, timing, now, old)
    assert auth.kind == recovery.PREFLIGHT_KIND
    assert authorize(conn, cfg, timing, now, old) == (generation, auth)
    release(conn)
    for _ in range(12):
        result = await service.tick(conn, now=now)
        if result.cycle and result.cycle.state is CycleState.WAITING_OPEN: break
    assert result.cycle.state is CycleState.WAITING_OPEN
    assert result.cycle.cycle_id != old.cycle_id and result.cycle.plan_id is not None
    assert store.load_cycle(conn, old.cycle_id) == old
    assert conn.execute('SELECT * FROM sentinel_automation_cycle_events WHERE cycle_id=%s ORDER BY seq',
                        (old.cycle_id,)).fetchall() == events
    assert conn.execute('SELECT COUNT(*) FROM sentinel_commands').fetchone()[0] == 0


@pytest.mark.parametrize('defect', ['detail', 'phase', 'type', 'plan', 'command', 'kind'])
def test_preflight_recovery_requires_exact_untransported_failure_and_receipt(conn, monkeypatch, defect):
    cfg, service, timing, now, old = preflight_blocked(conn, monkeypatch)
    if defect == 'kind':
        generation, _ = authorize(conn, cfg, timing, now, old)
        conn.execute("UPDATE sentinel_automation_events SET detail=jsonb_set(detail,'{kind}',%s::jsonb) WHERE generation=%s",
                     (json.dumps(recovery.KIND), generation)); conn.commit()
        permit = release(conn)
        with pytest.raises(AutomationRefused):
            store.create_cycle(conn, permit=permit, spec=service._spec(store.load_control(conn), timing), now=now)
        return
    if defect == 'command':
        conn.execute("INSERT INTO sentinel_commands (client_key,plan_id,security_id,deployment_id,broker,"
            "broker_account_id,takeover_epoch,symbol,side,quantity,state) VALUES ('unknown','unbound','s',"
            "'sentinel-a','alpaca-paper','paper-account-1',1,'TEST','BUY',1,'UNKNOWN')")
    elif defect == 'plan':
        conn.execute("UPDATE sentinel_automation_cycles SET plan_id='old-plan' WHERE cycle_id=%s", (old.cycle_id,))
    elif defect == 'detail':
        conn.execute("UPDATE sentinel_automation_cycles SET failure_detail=failure_detail || ' extra' WHERE cycle_id=%s", (old.cycle_id,))
    else:
        key, value = ('retry_phase', 'REFRESH') if defect == 'phase' else ('exception_type', 'other.SoftwareDefect')
        conn.execute('UPDATE sentinel_automation_cycles SET diagnostic=jsonb_set(diagnostic,%s,%s::jsonb) WHERE cycle_id=%s',
                     ([key], json.dumps(value), old.cycle_id))
    conn.commit()
    before = store.load_control(conn)
    with pytest.raises(AutomationRefused): authorize(conn, cfg, timing, now, old)
    assert store.load_control(conn) == before


@pytest.mark.asyncio
async def test_explicit_recovery_replans_and_survives_restart_without_rewriting_failure(conn, monkeypatch):
    cfg, service, timing, now, old = blocked(conn, monkeypatch)
    events = conn.execute('SELECT * FROM sentinel_automation_cycle_events ORDER BY seq').fetchall()
    conn.rollback()
    generation, auth = authorize(conn, cfg, timing, now, old)
    assert authorize(conn, cfg, timing, now, old) == (generation, auth)
    assert store.load_control(conn).kill_switch_engaged
    permit = release(conn)
    spec = service._spec(store.load_control(conn), timing)
    fresh = store.create_cycle(conn, permit=permit, spec=spec, now=now)
    assert fresh.cycle_id == spec.generation_cycle_id != old.cycle_id and fresh.plan_id is None
    for _ in range(12):
        result = await service.tick(conn, now=now)
        if result.cycle and result.cycle.state is CycleState.WAITING_OPEN:
            break
    assert result.cycle.state is CycleState.WAITING_OPEN
    assert result.cycle.plan_id != old.plan_id
    integrity.validate_cycle_lineage(conn, result.cycle)
    restarted = service_for(cfg, holder='worker-a')
    again = await restarted.tick(conn, now=now)
    assert again.cycle.cycle_id == fresh.cycle_id
    assert store.load_cycle(conn, old.cycle_id) == old
    assert conn.execute('SELECT * FROM sentinel_automation_cycle_events WHERE cycle_id=%s ORDER BY seq',
                        (old.cycle_id,)).fetchall() == events
    assert conn.execute('SELECT COUNT(*) FROM sentinel_commands').fetchone()[0] == 0


@pytest.mark.parametrize('defect', ['signature', 'ownership', 'unknown', 'transport',
                                   'command', 'scheduler_open', 'wrong_cycle', 'wrong_config',
                                   'active_leader', 'released_kill', 'historical', 'other_predecessor'])
def test_recovery_refuses_and_rolls_back_unsafe_obligations(conn, monkeypatch, defect):
    causes = {'signature': 'AuthorityRefused', 'ownership': 'CorpusBusy', 'unknown': 'RuntimeError'}
    cfg, _, timing, now, old = blocked(conn, monkeypatch,
        cause=causes.get(defect, 'CorpusLockUnavailable'), transported=defect == 'transport')
    if defect == 'command':
        conn.execute("INSERT INTO sentinel_commands (client_key,plan_id,security_id,deployment_id,broker,"
            "broker_account_id,takeover_epoch,symbol,side,quantity,state) VALUES ('sent','old-plan','s',"
            "'sentinel-a','alpaca-paper','paper-account-1',1,'TEST','BUY',1,'UNKNOWN')")
        conn.commit()
    if defect == 'scheduler_open':
        now = timing.execution_open_at
    if defect == 'wrong_cycle':
        old = old.model_copy(update={'cycle_id': 'f'*64})
    if defect == 'wrong_config':
        cfg = cfg.model_copy(update={'retry_base_seconds': cfg.retry_base_seconds+1})
    if defect == 'active_leader':
        conn.execute("UPDATE sentinel_automation_lease SET holder_id='foreign',"
            "control_generation=%s,acquired_at=clock_timestamp(),heartbeat_at=clock_timestamp(),"
            "expires_at=clock_timestamp()+interval '1 hour' WHERE id=1",
            (store.load_control(conn).generation,))
        conn.commit()
    if defect == 'released_kill':
        release(conn)
    if defect == 'historical':
        conn.execute('UPDATE sentinel_automation_cycles SET historical_state_only=TRUE WHERE cycle_id=%s', (old.cycle_id,))
        conn.commit()
    if defect == 'other_predecessor':
        conn.execute("UPDATE sentinel_automation_cycles SET failure_code='different' WHERE cycle_id=%s", (old.cycle_id,))
        conn.commit()
    before = store.load_control(conn)
    with pytest.raises((AutomationRefused, ValueError)):
        authorize(conn, cfg, timing, now, old)
    assert store.load_control(conn) == before
    assert conn.execute("SELECT COUNT(*) FROM sentinel_automation_events WHERE detail->>'schema'='sentinel.unsent-recovery/1'").fetchone()[0] == 0


def test_blocked_history_cannot_be_replaced_without_operator_authorization(conn, monkeypatch):
    cfg, service, timing, now, old = blocked(conn, monkeypatch)
    permit = release(conn)
    spec = service._spec(store.load_control(conn), timing)
    with pytest.raises(ProspectiveReplacementRefused):
        store.create_cycle(conn, permit=permit, spec=spec, now=now)
    assert store.load_cycle(conn, old.cycle_id) == old


@pytest.mark.parametrize('defect', ['receipt', 'predecessor', 'binding', 'generation', 'command'])
def test_replacement_repeats_receipt_scope_and_transport_proof(conn, monkeypatch, defect):
    cfg, service, timing, now, old = blocked(conn, monkeypatch)
    generation, _ = authorize(conn, cfg, timing, now, old)
    permit = release(conn)
    spec = service._spec(store.load_control(conn), timing)
    if defect == 'receipt':
        conn.execute("UPDATE sentinel_automation_events SET detail=detail-'kind' WHERE generation=%s", (generation,))
        conn.commit()
        with pytest.raises(AutomationRefused): store.load_control(conn)
        return
    if defect == 'predecessor':
        conn.execute('UPDATE sentinel_automation_cycles SET updated_at=updated_at+interval \'1 second\' WHERE cycle_id=%s', (old.cycle_id,))
        conn.commit()
    if defect == 'binding':
        spec = spec.model_copy(update={'broker_account_id': 'foreign'})
    if defect == 'generation':
        store.engage_kill(conn, actor='operator', reason='another boundary')
        permit = release(conn)
        spec = service._spec(store.load_control(conn), timing)
    if defect == 'command':
        conn.execute("INSERT INTO sentinel_commands (client_key,plan_id,security_id,deployment_id,broker,"
            "broker_account_id,takeover_epoch,symbol,side,quantity,state) VALUES ('late','unknown-plan','s',"
            "'sentinel-a','alpaca-paper','paper-account-1',1,'TEST','BUY',1,'UNKNOWN')")
        conn.commit()
    with pytest.raises((AutomationRefused, ProspectiveReplacementRefused)):
        store.create_cycle(conn, permit=permit, spec=spec, now=now)


def test_concurrent_creation_converges_on_one_authorized_cycle(conn, pg, monkeypatch):
    cfg, service, timing, now, old = blocked(conn, monkeypatch)
    authorize(conn, cfg, timing, now, old)
    permit = release(conn)
    spec = service._spec(store.load_control(conn), timing)
    def create(_):
        with psycopg.connect(pg.sync_dsn) as c:
            try: return store.create_cycle(c, permit=permit, spec=spec, now=now).cycle_id
            except store.CycleCreationBusy: return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(create, range(4)))
    assert set(ids) <= {None, spec.generation_cycle_id}
    assert spec.generation_cycle_id in ids
    integrity.validate_cycle_lineage(conn, store.load_cycle(conn, spec.generation_cycle_id))


@pytest.mark.parametrize('guard', ['eligibility', 'commands'])
def test_guard_falsifier_kills_the_corresponding_negative_test(conn, monkeypatch, guard):
    if guard == 'eligibility':
        monkeypatch.setattr(recovery, 'eligible_kind',
                            lambda c: recovery.KIND if c.state is CycleState.BLOCKED else None)
        defect = 'signature'
    else:
        monkeypatch.setattr(recovery, 'require_unsent', lambda *a, **kw: None)
        defect = 'command'
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_recovery_refuses_and_rolls_back_unsafe_obligations(conn, monkeypatch, defect)


def test_recovery_parser_requires_explicit_confirmations():
    from sentinel.cli.main import build_parser
    parser = build_parser()
    with pytest.raises(SystemExit): parser.parse_args(['authorize-unsent-paper-recovery'])
    args = parser.parse_args(['authorize-unsent-paper-recovery', '--confirm-paper-account', 'account',
        '--confirm-deployment-id', 'deployment', '--confirm-certificate-sha256', 'a'*64,
        '--decision-session', '2026-08-12', '--blocked-cycle-id', 'b'*64,
        '--actor', 'operator', '--reason', 'incident', '--confirm-old-writer-fenced',
        '--confirm-authorize-unsent-paper-recovery'])
    assert args.confirm_authorize_unsent_paper_recovery


@pytest.mark.parametrize('defect', [None, 'certificate', 'fresh_authority', 'confirmation', 'backup'])
def test_actual_operator_cli_preserves_kill_and_repeats_current_authority(conn, pg, monkeypatch, defect):
    from sentinel import authority, backup_runtime_authority, handover
    from sentinel.cli import automation as cli, _shared
    from sentinel.automation_runtime import config_from_env
    cfg, _, timing, now, old = blocked(conn, monkeypatch)
    control = store.load_control(conn)
    signed_calls = []
    def signed(*a):
        signed_calls.append(1)
        if defect == 'fresh_authority':
            raise authority.AuthorityRefused('revoked signature')
        return (control.binding,
            SimpleNamespace(mode=authority.RolloutMode.PINNED_1_00, version=control.binding.rollout_version),
            SimpleNamespace(certificate_sha256=control.binding.certificate_sha256))
    monkeypatch.setattr(_shared, 'require_authorized_runtime', lambda _: None)
    monkeypatch.setattr(cli, 'require_authorized_runtime', lambda _: None)
    monkeypatch.setattr(cli, '_automation_authority', signed)
    monkeypatch.setattr('sentinel.automation_runtime.config_from_env', lambda: cfg)
    monkeypatch.setattr(handover, 'assert_no_legacy_path', lambda _: control.binding)
    if defect == 'backup':
        from sentinel.backup_guard import BackupWriteFenced
        def no_backup(*a, **kw): raise BackupWriteFenced('backup unavailable')
        monkeypatch.setattr(backup_runtime_authority, 'require', no_backup)
    # CLI host clock is real; the fixture's calendar seam chooses the isolated
    # future obligation. No real market state or certificate is manufactured.
    args = SimpleNamespace(confirm_old_writer_fenced=True,
        confirm_authorize_unsent_paper_recovery=defect != 'confirmation',
        confirm_paper_account=control.binding.broker_account_id,
        confirm_deployment_id=control.binding.deployment_id,
        confirm_certificate_sha256=('f'*64 if defect == 'certificate' else control.binding.certificate_sha256),
        decision_session=str(timing.decision_session), blocked_cycle_id=old.cycle_id,
        actor='operator', reason='isolated CLI qualification')
    code = cli._authorize_unsent_paper_recovery(SimpleNamespace(database_url=pg.sync_dsn,
        base_url='https://paper-api.alpaca.markets'), args)
    assert code == (0 if defect is None else 1 if defect == 'confirmation' else 2)
    assert store.load_control(conn).kill_switch_engaged
    assert bool(signed_calls) == (defect not in {'confirmation','backup'})
    assert conn.execute('SELECT COUNT(*) FROM sentinel_commands').fetchone()[0] == 0


def test_ordinary_runtime_cannot_dispatch_recovery_before_database_access(monkeypatch):
    from sentinel.cli import _shared, automation as cli
    monkeypatch.setattr(_shared, 'require_authorized_runtime', lambda _: 1)
    assert cli._authorize_unsent_paper_recovery(None, None) == 1


def test_lineage_rejects_deleted_or_rebound_recovery_receipt(conn, monkeypatch):
    cfg, service, timing, now, old = blocked(conn, monkeypatch)
    generation, _ = authorize(conn, cfg, timing, now, old)
    permit = release(conn)
    fresh = store.create_cycle(conn, permit=permit,
        spec=service._spec(store.load_control(conn), timing), now=now)
    integrity.validate_cycle_lineage(conn, fresh)
    conn.execute("UPDATE sentinel_automation_events SET detail=jsonb_set(detail,'{blocked_cycle_id}',to_jsonb(%s::text)) WHERE generation=%s",
        ('f'*64,generation))
    conn.commit()
    with pytest.raises(AutomationRefused): integrity.validate_cycle_lineage(conn, fresh)


def test_authorization_covers_every_predecessor_and_preserves_supersession(conn, monkeypatch):
    from tests.sentinel.test_automation_generation import retained
    service, first, spec, permit, now = retained(conn)
    fresh = store.create_cycle(conn, permit=permit, spec=spec, now=now)
    old = store.transition_cycle(conn, permit=permit, cycle_id=fresh.cycle_id,
        to_state=CycleState.BLOCKED, failure_code='NonRetryableCallbackRefused',
        failure_detail='automation authority/integrity refusal: WriterLockUnavailable: temporary',
        diagnostic={'control_poll_failure':'NONRETRYABLE'})
    store.engage_kill(conn, actor='operator', reason='incident')
    timing = schedule.for_decision_session(spec.decision_session, config())
    monkeypatch.setattr(recovery.calendar, 'latest_closed_session', lambda _: str(spec.decision_session))
    _, auth = authorize(conn, config(), timing, now, old)
    assert sorted(auth.predecessor_fingerprints) == sorted([first.cycle_id,old.cycle_id])
    permit = release(conn)
    current = store.create_cycle(conn, permit=permit,
        spec=service._spec(store.load_control(conn), timing), now=now)
    integrity.validate_cycle_lineage(conn, current)
    assert store.load_cycle(conn, first.cycle_id) == first
    assert store.load_cycle(conn, old.cycle_id) == old


@pytest.mark.parametrize('field,value', [('broker_account_id','foreign'), ('takeover_epoch',2),
    ('certificate_sha256','f'*64), ('rollout_version',2)])
def test_authorization_refuses_foreign_or_changed_binding(conn, monkeypatch, field, value):
    cfg, _, timing, now, old = blocked(conn, monkeypatch)
    binding = store.load_control(conn).binding.model_copy(update={field:value})
    with pytest.raises(AutomationRefused):
        recovery.authorize(conn, binding=binding, decision_session=timing.decision_session,
            blocked_cycle_id=old.cycle_id, actor='operator',reason='incident',now=now,automation_config=cfg)


def test_recovery_cannot_bypass_canonical_writer_ownership(conn, pg, monkeypatch):
    from sentinel.execution.journal import WRITER_LOCK_KEY, WriterLockUnavailable
    cfg, _, timing, now, old = blocked(conn, monkeypatch)
    with psycopg.connect(pg.sync_dsn) as owner:
        owner.execute('SELECT pg_advisory_lock(%s)', (WRITER_LOCK_KEY,))
        owner.commit()
        with pytest.raises(WriterLockUnavailable): authorize(conn, cfg, timing, now, old)


def test_failed_authorization_audit_write_rolls_back_control_generation(conn, monkeypatch):
    cfg, _, timing, now, old = blocked(conn, monkeypatch)
    insert = store._insert_control_event
    def fail_commit(*a, **kw):
        raise RuntimeError('injected audit-write failure')
    monkeypatch.setattr(store, '_insert_control_event', fail_commit)
    before = store.load_control(conn)
    with pytest.raises(RuntimeError, match='audit-write'): authorize(conn, cfg, timing, now, old)
    assert store.load_control(conn) == before
    monkeypatch.setattr(store, '_insert_control_event', insert)


def test_authorization_commit_rechecks_database_open_boundary(conn, monkeypatch):
    cfg, _, timing, now, old = blocked(conn, monkeypatch)
    clock = conn.execute('SELECT clock_timestamp()').fetchone()[0]
    conn.rollback()
    class Crossing:
        reads = 0
        @property
        def execution_open_at(self):
            self.reads += 1
            return timing.execution_open_at if self.reads <= 2 else clock-timedelta(seconds=1)
        def __getattr__(self, name): return getattr(timing, name)
    monkeypatch.setattr(schedule, 'for_decision_session', lambda *a: Crossing())
    before = store.load_control(conn)
    with pytest.raises(AutomationRefused, match='boundary changed'):
        authorize(conn, cfg, timing, now, old)
    assert store.load_control(conn) == before


def test_database_commit_clock_guard_falsifier_kills_boundary_test(conn, monkeypatch):
    import inspect,textwrap
    source = textwrap.dedent(inspect.getsource(recovery.authorize))
    old = 'AND enabled AND kill_switch_engaged AND clock_timestamp()<%s'
    assert old in source
    namespace = {}
    exec(compile(source.replace(old, 'AND enabled AND kill_switch_engaged AND (clock_timestamp()<%s OR TRUE)'),
        'recovery-clock-falsifier', 'exec'), recovery.__dict__, namespace)
    monkeypatch.setattr(recovery, 'authorize', namespace['authorize'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_authorization_commit_rechecks_database_open_boundary(conn, monkeypatch)


def test_recovered_cycle_cannot_rebind_the_failed_plan(conn, monkeypatch):
    cfg, service, timing, now, old = blocked(conn, monkeypatch)
    authorize(conn, cfg, timing, now, old)
    permit = release(conn)
    fresh = store.create_cycle(conn, permit=permit,
        spec=service._spec(store.load_control(conn), timing), now=now)
    fresh = store.transition_cycle(conn, permit=permit, cycle_id=fresh.cycle_id,
                                   to_state=CycleState.PREPARING)
    with pytest.raises(AutomationRefused, match='fresh plan'):
        store.transition_cycle(conn, permit=permit, cycle_id=fresh.cycle_id,
            to_state=CycleState.PLAN_READY, plan_id=old.plan_id)
    assert store.load_cycle(conn, fresh.cycle_id) == fresh


def test_fresh_plan_guard_falsifier_kills_the_old_plan_test(conn, monkeypatch):
    monkeypatch.setattr(recovery, 'require_fresh_plan', lambda *a: None)
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_recovered_cycle_cannot_rebind_the_failed_plan(conn, monkeypatch)


def test_receipt_survives_a_restarted_connection_with_a_different_timezone(conn, pg, monkeypatch):
    cfg, service, timing, now, old = blocked(conn, monkeypatch)
    authorize(conn, cfg, timing, now, old)
    permit = release(conn)
    spec = service._spec(store.load_control(conn), timing)
    with psycopg.connect(pg.sync_dsn) as restarted:
        restarted.execute("SET TIME ZONE 'America/Los_Angeles'")
        restarted.commit()
        fresh = store.create_cycle(restarted, permit=permit, spec=spec, now=now)
        integrity.validate_cycle_lineage(restarted, fresh)
