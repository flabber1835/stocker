"""An exact enrolled no-send proof can close intent, never create transport."""
import asyncio
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
import importlib
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'scripts'))
operation = importlib.import_module('sentinel_retire_expired_unsent')
from sentinel.execution import issuer_admission as issuer, journal
from sentinel.execution.contract import BrokerAccountSnapshot
from sentinel.execution.guarded import PaperPreparationGrant
from sentinel.execution.states import CommandState as S
from tests.sentinel.test_issuer_admission import (
    BINDING, NOW, Memory, Rows, command, reconciliation, store,
)
from tests.sentinel.test_issuer_enrollment import preparation_wrapper
from tests.sentinel.test_order_terms_schema import pg


@pytest.fixture
def program():
    namespace = {'__name__': 'qualified_retirement_test'}
    exec(compile(operation.PROGRAM, '<qualified-retirement>', 'exec'), namespace)
    return namespace


class SqlMemory(Memory):
    def __init__(self):
        super().__init__()
        self.fill_exists = False
        self.lease_live = False
        self.events = []

    def execute(self, sql, args=()):
        if 'FROM sentinel_fills' in sql:return Rows([(self.fill_exists,)])
        if 'FROM sentinel_automation_lease' in sql:return Rows([(self.lease_live,)])
        return super().execute(sql, args)

    def close(self):self.events.append('close')


@pytest.fixture
def lab(store, program, monkeypatch):
    conn = SqlMemory()
    conn.locked = False
    conn.commands = [command('A'), command('B')]
    conn.plans = {c.identity.plan_id: SimpleNamespace(is_superseded=True,
        effective_session=date(2026, 10, 1), fingerprint=lambda:'f'*64) for c in conn.commands}
    for c in conn.commands:
        conn.histories[c.client_key] = [
            {'from':None,'to':'PLANNED','filled':'0','detail':'','at':NOW-timedelta(seconds=3)},
            {'from':'PLANNED','to':'SEND_PENDING','filled':'0','detail':'','at':NOW-timedelta(seconds=2)},
            {'from':'SEND_PENDING','to':'PLANNED','filled':'0',
             'detail':'PRE_TRANSPORT_CHECKPOINT_RESTORED: original protected preflight refusal',
             'at':NOW-timedelta(seconds=1)}]
    rec = reconciliation()
    proofs = [issuer._unsent_proof(conn,c,rec.observation,NOW) for c in conn.commands]
    expected = dict(operation_id='retire-exact-historical-intents',account=BINDING.broker_account_id,
        deployment=BINDING.deployment_id,certificate_sha256='c'*64,generation=51,
        enrollment_sha256='e'*64,keys=sorted(c.client_key for c in conn.commands),
        runtime_commit='a'*40,image_digest='sha256:'+'b'*64,decision_session='2026-10-26',
        blocked_cycle_id='d'*64,actor='qualified-test',reason='exact no-send closure',recover=False)
    expected['keyset_sha256'] = program['digest'](expected['keys'])
    owner = SimpleNamespace(identity=BINDING,**BINDING.to_dict())
    control_binding = SimpleNamespace(**BINDING.to_dict(),certificate_sha256=expected['certificate_sha256'])
    control = SimpleNamespace(enabled=True,kill_switch_engaged=True,generation=51,binding=control_binding)
    enrollment = SimpleNamespace(sha256=expected['enrollment_sha256'],binding=issuer._binding(BINDING),
        excluded_unsent_proofs=tuple(proofs))
    config = SimpleNamespace(database_url='postgresql://private.invalid/test',base_url='https://paper-api.alpaca.markets')
    certificate = SimpleNamespace(certificate_sha256=expected['certificate_sha256'])
    writes = []

    def save(conn, updated, *, previous):
        assert conn.locked and previous is S.PLANNED
        current = next(c for c in conn.commands if c.client_key == updated.client_key)
        assert current.state is S.PLANNED and updated.state is S.SUPERSEDED
        assert program['economics'](current) == program['economics'](updated)
        conn.commands = [updated if c.client_key == updated.client_key else c for c in conn.commands]
        conn.histories[updated.client_key].append(dict(
            **{'from':'PLANNED','to':'SUPERSEDED','filled':'0','detail':updated.detail,'at':NOW}))
        writes.append(updated.client_key)

    @contextmanager
    def writer(conn):
        assert not conn.locked
        conn.events.append('backup-protected-writer')
        conn.locked = True
        try:yield
        finally:conn.locked=False

    @contextmanager
    def pinned(conn, *, commit):
        assert conn.locked and commit is False
        yield SimpleNamespace(window_end='2026-10-26')

    class Inner:
        async def account_snapshot(self):
            conn.events.append('fresh-account')
            return BrokerAccountSnapshot(rec.observation.account_identity, Decimal(50000), Decimal(50000))
        async def identify_account(self):return rec.observation.account_identity
        async def observe(self):return rec.observation
        async def submit(self, **_kwargs):pytest.fail('maintenance submitted an order')
        async def cancel(self, **_kwargs):pytest.fail('maintenance cancelled an order')

    def wrap(**kwargs):
        assert type(kwargs['grant']) is PaperPreparationGrant
        assert kwargs['grant'].expected_account == BINDING.broker_account_id
        return preparation_wrapper(kwargs['broker'], conn.events)

    async def reconcile(**kwargs):
        assert kwargs['actions'] is actions and kwargs['informational_current_book'] is True
        assert kwargs['binding'] is None and kwargs['deployment'] == BINDING
        await kwargs['broker'].identify_account()
        await kwargs['broker'].observe()
        conn.events.append('fresh-reconciliation')
        return rec

    actions = object()
    monkeypatch.setenv('SENTINEL_GIT_COMMIT',expected['runtime_commit'])
    monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_DIGEST',expected['image_digest'])
    monkeypatch.setitem(program,'now',lambda:NOW)
    monkeypatch.setitem(program,'require_authorized_runtime',lambda _:None)
    monkeypatch.setitem(program,'_automation_authority',lambda *_:(owner,object(),certificate))
    monkeypatch.setitem(program,'config_from_env',lambda:SimpleNamespace(fingerprint='f'*64))
    monkeypatch.setitem(program,'_guard_broker',wrap)
    monkeypatch.setitem(program,'_action_lookup',lambda *_:actions)
    monkeypatch.setitem(program,'build_security_resolver',lambda *_:object())
    monkeypatch.setitem(program,'build_execution_broker',lambda *_args,**_kwargs:Inner())
    monkeypatch.setattr(program['SentinelConfig'],'from_env',lambda:config)
    monkeypatch.setattr(program['store'],'connect',lambda _:conn)
    monkeypatch.setattr(program['schema'],'require_runtime_schema',lambda _:None)
    monkeypatch.setattr(program['feed_inputs'],'pinned',pinned)
    monkeypatch.setattr(journal,'writer_lock',writer)
    monkeypatch.setattr(journal,'require_observation_integrity',lambda _:None)
    monkeypatch.setattr(journal,'in_flight_commands',lambda *_:tuple(c for c in conn.commands if c.state in
        {S.SEND_PENDING,S.UNKNOWN,S.ACKNOWLEDGED,S.PARTIALLY_FILLED,S.CANCEL_PENDING}))
    monkeypatch.setattr(journal,'save_command',save)
    monkeypatch.setattr(program['binding'],'require',lambda _:owner)
    monkeypatch.setattr(program['automation'],'load_control',lambda _:control)
    monkeypatch.setattr(program['authority'],'load_active_signed_certificate',lambda *_args,**_kwargs:certificate)
    monkeypatch.setattr(issuer,'load_enrollment',lambda *_args,**_kwargs:enrollment)
    monkeypatch.setattr(program['reconciliation'],'reconcile',reconcile)
    return SimpleNamespace(conn=conn,expected=expected,rec=rec,enrollment=enrollment,owner=owner,
        control=control,certificate=certificate,proofs=proofs,writes=writes,program=program,save=save)


def run(lab):return asyncio.run(lab.program['run'](lab.expected))


def test_canonical_proof_closes_only_exact_existing_commands_and_restarts_without_another_event(lab):
    before = {c.client_key:lab.program['economics'](c) for c in lab.conn.commands}
    result = run(lab)
    assert len(lab.conn.commands) == len(before) == len(lab.writes) == 2
    assert all(c.state is S.SUPERSEDED and lab.program['economics'](c)==before[c.client_key] for c in lab.conn.commands)
    assert result['broker_mutations'] is False and set(result['after'])==set(before)
    assert lab.conn.events.index('backup-protected-writer') < lab.conn.events.index('fresh-account')
    assert run(lab)['after'] == result['after'] and len(lab.writes)==2


def test_partial_per_command_commit_is_convergent_without_reopening_completed_identity(lab, monkeypatch):
    def interrupted(conn, command, **kwargs):
        if lab.writes:raise RuntimeError('injected process interruption')
        lab.save(conn,command,**kwargs)
    monkeypatch.setattr(journal,'save_command',interrupted)
    with pytest.raises(RuntimeError,match='interruption'):run(lab)
    assert len(lab.writes)==1
    monkeypatch.setattr(journal,'save_command',lab.save)
    assert len(run(lab)['after'])==2 and len(lab.writes)==2


@pytest.mark.parametrize('damage',['history','unmatched_pending','bad_restoration','plan','fill','broker_id','recovered','pending','unknown',
    'enrollment','extra_enrolled_key','keyset','binding','kill','generation','live_leader','stale_observation'])
def test_changed_or_uncertain_evidence_cannot_retire_any_intent(lab,damage):
    first=lab.conn.commands[0]
    if damage=='history':lab.conn.histories[first.client_key][0]['detail']='changed after enrollment'
    elif damage=='unmatched_pending':lab.conn.histories[first.client_key].pop()
    elif damage=='bad_restoration':lab.conn.histories[first.client_key][-1]['detail']='generic timeout is not no-send proof'
    elif damage=='plan':lab.conn.plans[first.identity.plan_id].fingerprint=lambda:'9'*64
    elif damage=='fill':lab.conn.fill_exists=True
    elif damage=='broker_id':lab.conn.commands[0]=replace(first,broker_order_id='native-order')
    elif damage=='recovered':lab.conn.commands[0]=replace(first,recovered_key=first.client_key)
    elif damage=='pending':lab.conn.commands[0]=replace(first,state=S.SEND_PENDING)
    elif damage=='unknown':lab.conn.commands[0]=replace(first,state=S.UNKNOWN)
    elif damage=='enrollment':lab.enrollment.sha256='9'*64
    elif damage=='extra_enrolled_key':lab.enrollment.excluded_unsent_proofs+=({'client_key':'extra'},)
    elif damage=='keyset':lab.expected['keyset_sha256']='9'*64
    elif damage=='binding':lab.control.binding.broker_account_id='foreign-account'
    elif damage=='kill':lab.control.kill_switch_engaged=False
    elif damage=='generation':lab.control.generation=52
    elif damage=='live_leader':lab.conn.lease_live=True
    else:lab.rec.observation=replace(lab.rec.observation,observed_at=NOW-timedelta(seconds=61))
    with pytest.raises((RuntimeError,issuer.IssuerAdmissionRefused)):run(lab)
    assert not lab.writes


def test_same_operation_cannot_accept_foreign_terminal_closure(lab):
    run(lab)
    c=lab.conn.commands[0]
    lab.conn.commands[0]=replace(c,detail='unrelated retirement')
    with pytest.raises(RuntimeError,match='TERMINAL_CLOSURE'):run(lab)


def test_removed_enrollment_history_guard_is_detected(lab,monkeypatch):
    source=operation.PROGRAM
    guard="('client_key','plan_id','plan_fingerprint','events_sha256')"
    assert source.count(guard)==1
    altered=source.replace(guard,"('client_key','plan_id','plan_fingerprint')")
    mutant={'__name__':'mutation_test'}
    exec(compile(altered,'<removed-enrolled-history>','exec'),mutant)
    monkeypatch.setitem(lab.program,'validate_command',mutant['validate_command'])
    # The mutant's globals need the same storage and operation helpers.
    mutant.update({k:v for k,v in lab.program.items() if k!='validate_command'})
    with pytest.raises(AssertionError):
        test_changed_or_uncertain_evidence_cannot_retire_any_intent(lab,'history')


def test_sealed_program_refuses_unknown_bytes_and_contains_no_transport_dispatch(program):
    with pytest.raises(ValueError,match='DIGEST'):operation.sealed_program({'program_sha256':'0'*64})
    assert repr(operation.PROGRAM) in operation.sealed_program({'program_sha256':operation.program_sha256()})
    assert '.submit(' not in operation.PROGRAM and '.cancel(' not in operation.PROGRAM


@pytest.mark.parametrize('release_damage',[None,'generation','kill'])
def test_explicit_recovery_uses_existing_authorize_and_release_and_checks_exact_result(lab,monkeypatch,release_damage):
    lab.expected['recover']=True
    calls=[]
    monkeypatch.setitem(lab.program,'_automation_control_binding',lambda *_:lab.control.binding)
    def authorize(conn,**kwargs):
        assert all(c.state is S.SUPERSEDED for c in conn.commands)
        assert kwargs['blocked_cycle_id']==lab.expected['blocked_cycle_id']
        assert kwargs['binding'] is lab.control.binding
        calls.append('authorize')
        lab.control.generation=52
        return 52,SimpleNamespace(model_dump=lambda **_:{'kind':'reviewed-original-recovery'})
    def release(conn,**kwargs):
        assert lab.control.generation==52 and kwargs['expected_binding'] is lab.control.binding
        calls.append('release')
        lab.control.generation=54 if release_damage=='generation' else 53
        lab.control.kill_switch_engaged=release_damage=='kill'
        return lab.control
    monkeypatch.setattr(lab.program['unsent_recovery'],'authorize',authorize)
    monkeypatch.setattr(lab.program['automation'],'release_kill',release)
    if release_damage is not None:
        with pytest.raises(RuntimeError,match='RELEASE_GENERATION_OR_KILL_CHANGED'):run(lab)
    else:
        result=run(lab)
        assert result['recovery']['generation']==53 and result['recovery']['kill_switch_engaged'] is False
    assert calls==['authorize','release'] and len(lab.writes)==2


def test_real_postgres_journal_preserves_history_and_terminal_restart(pg,program,monkeypatch):
    import psycopg
    from sentinel import schema
    with psycopg.connect(pg.sync_dsn) as conn:
        from tests.support.postgres import drop_public_tables
        drop_public_tables(conn)
        schema.ensure_schema(conn)
        planned=command('A')
        journal.save_command(conn,planned)
        planned=journal.load_commands(conn,BINDING)[0]
        plan=SimpleNamespace(is_superseded=True,effective_session=date(2026,10,1),fingerprint=lambda:'f'*64)
        monkeypatch.setattr(journal,'load_plan',lambda *_:plan)
        observation=reconciliation().observation
        retained=issuer._unsent_proof(conn,planned,observation,NOW)
        expected=dict(operation_id='pg-retirement',keyset_sha256=program['digest']([planned.client_key]),
            enrollment_sha256='e'*64)
        before=program['validate_command'](conn,planned,retained,expected,observation,NOW)
        journal.save_command(conn,planned.transition(S.SUPERSEDED,detail=before['closure_detail']),previous=S.PLANNED)
        retired=journal.load_commands(conn,BINDING)[0]
        after=program['validate_command'](conn,retired,retained,expected,observation,NOW)
        assert after['economics']==before['economics'] and after['state']=='SUPERSEDED'
        assert len(journal.command_history(conn,planned.client_key))==2
