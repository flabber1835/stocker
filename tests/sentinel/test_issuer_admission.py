"""Issuer entry reservations preserve real execution debt and canonical ownership."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
import json
from types import SimpleNamespace

import psycopg
import pytest

from sentinel.execution import issuer_admission as guard
from sentinel.execution.commands import Command
from sentinel.execution.contract import BrokerAccountIdentity, BrokerInstrument, BrokerObservation, BrokerOrder, BrokerPosition, Side
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.reconcile import ReconciliationResult
from sentinel.execution.states import CommandState as S, RuntimeState
from sentinel.feed.issuer_reference import IssuerReferenceSnapshot
from sentinel.feed.rolling_contract import digest
from tests.sentinel.test_order_terms_schema import pg  # noqa: F401
from tests.sentinel.test_issuer_executor_gate import harness  # noqa: F401

NOW = datetime(2026, 10, 27, 14, 0, tzinfo=timezone.utc)
BINDING = DeploymentIdentity('issuer-test', 'alpaca', 'paper-issuer', 3)
SYMBOLS = {'A': 'AAA', 'A2': 'AAA.A', 'B': 'BBB', 'C': 'CCC', 'U': 'UNKNOWN'}


class Rows:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class Memory:
    """The cursor table's insert-once semantics; real lock/rollback tested below."""
    def __init__(self):
        self.records, self.commands, self.plans, self.histories = {}, [], {}, {}
        self.locked = True

    def execute(self, sql, args=()):
        if 'FROM pg_locks' in sql:
            return Rows([(self.locked,)])
        if sql.startswith('SELECT state FROM sentinel_processed_sessions'):
            value = self.records.get(args[0])
            return Rows([] if value is None else [(deepcopy(value),)])
        if sql.startswith('INSERT INTO sentinel_processed_sessions'):
            self.records.setdefault(args[0], json.loads(args[2]))
            return Rows()
        if sql.startswith('SELECT cursor_name,state FROM sentinel_processed_sessions'):
            return Rows([(key, deepcopy(raw)) for key, raw in sorted(self.records.items())
                         if args[0] <= key < args[1]])
        if sql.startswith('SELECT cursor_name FROM sentinel_processed_sessions WHERE '):
            return Rows([(key,) for key in sorted(self.records)
                         if any(low <= key < high for low, high in zip(args[::2], args[1::2]))][:1])
        raise AssertionError(sql)

    @contextmanager
    def transaction(self):
        before = deepcopy(self.records)
        try:
            yield
        except BaseException:
            self.records = before
            raise


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setattr(guard.journal, 'load_commands', lambda conn, *_args, **_kw: tuple(conn.commands))
    monkeypatch.setattr(guard.journal, 'load_plan', lambda conn, key: conn.plans.get(key))
    monkeypatch.setattr(guard.journal, 'command_history', lambda conn, key: tuple(conn.histories.get(key, ())))
    return Memory()


@pytest.fixture
def source():
    return IssuerReferenceSnapshot.create(observed_at_utc=NOW,
        associations=[{'cik': '0000000001' if sid in {'A', 'A2'} else '0000000002' if sid == 'B' else '0000000003',
                       'ticker': symbol.replace('.', '-'), 'exchange': 'NYSE'}
                      for sid, symbol in SYMBOLS.items() if sid != 'U'],
        coverage='PARTIAL', source_method='WEB_EXTRACTED_REPRESENTATION')


def instruments(*sids):
    return {sid: {'symbol': SYMBOLS[sid], 'asset_id': 'native-' + sid, 'exchange': 'NYSE',
                  'security_type': 'Common Stock', 'security_type2': 'Common Stock'} for sid in sids}


def state(*, held=(), pending=(), signal='2026-10-26'):
    episodes = {str(slot): {'security_id': sid, 'ticker': SYMBOLS[sid], 'slot_id': slot,
                            'signal_date': signal, 'current_shares': 10}
                for slot, sid in enumerate(held)}
    orders = [{'operation': 'OPEN_SLOT_POSITION', 'security_id': sid, 'slot_id': slot,
               'signal_session': signal} for slot, sid in enumerate(pending, len(held))]
    raw = {'episodes': episodes, 'pending': orders}
    return SimpleNamespace(wealth_core={'episodes': episodes}, pending=orders,
                           state_hash=digest(raw), last_processed_session='2026-10-26')


def reconciliation(*sids, at=NOW, observation_id=1, expected=None):
    positions = tuple(BrokerPosition(BrokerInstrument(sid, SYMBOLS[sid], 'native-' + sid), D(10)) for sid in sids)
    observation = BrokerObservation(observed_at=at, positions=positions,
        account_identity=BrokerAccountIdentity(BINDING.broker, BINDING.broker_account_id))
    quantities = {sid: D(10) for sid in sids}
    return ReconciliationResult(RuntimeState.RUNNING, observation=observation,
        expected=quantities if expected is None else expected, observed=quantities, observation_id=observation_id)


def enroll(store, source, *held):
    return guard.enroll(store, binding=BINDING, state=state(held=held),
        reconciliation=reconciliation(*held), snapshot=source,
        instruments=instruments(*held), now=NOW)


def prepare(store, source, *, held=(), pending=(), signal='2026-10-26', rec=None, suffix='1', extra=()):
    value = state(held=held, pending=pending, signal=signal)
    opening = tuple(SimpleNamespace(to_dict=lambda sid=sid, slot=slot: {
        'security_id': sid, 'slot_id': slot, 'intended_dollars': '1000'})
        for slot, sid in enumerate(pending, len(held)))
    plan = SimpleNamespace(plan_id='plan-' + suffix, shadow_snapshot_hash=value.state_hash,
        decision_session=date(2026, 10, 26), effective_session=date(2026, 10, 27),
        opening_intents=opening, **BINDING.to_dict())
    plan.fingerprint = lambda: digest({'id': plan.plan_id, 'state': value.state_hash})
    projection = SimpleNamespace(plan_id=plan.plan_id, plan_fingerprint=plan.fingerprint(),
        through_session=plan.effective_session, target_basket={sid: D(10) for sid in held + pending})
    projection.fingerprint = lambda: digest({'plan': plan.fingerprint(), 'targets': sorted(projection.target_basket)})
    evidence = guard.prepare_plan_evidence(store, binding=BINDING, state=value, plan=plan,
        projection=projection, reconciliation=rec or reconciliation(), snapshot=source,
        instruments=instruments(*(set(held + pending + extra))), now=NOW)
    return value, plan, projection, evidence


def buy(store, evidence, sid, *, reserve=False, rec=None, now=NOW):
    return guard.check_buy(store, evidence=evidence, security_id=sid,
        reconciliation=rec or reconciliation(), now=now, reserve=reserve)


def command(sid, status=S.PLANNED, *, plan='old-plan', filled='0', epoch=3, side=Side.BUY):
    identity = CommandIdentity(DeploymentIdentity('issuer-test', 'alpaca', 'paper-issuer', epoch), plan, sid, 0)
    return Command(identity, BrokerInstrument(sid, SYMBOLS[sid], 'native-' + sid), side, D(10),
                   state=status, filled_quantity=D(filled))


def test_baseline_duplicate_classes_continue_and_state_is_untouched(store, source):
    initial = state(held=('A', 'A2'))
    before = deepcopy(initial.__dict__)
    baseline = guard.enroll(store, binding=BINDING, state=initial,
        reconciliation=reconciliation('A', 'A2'), snapshot=source,
        instruments=instruments('A', 'A2'), now=NOW)
    _, _, projection, evidence = prepare(store, source, held=('A', 'A2'), rec=reconciliation('A', 'A2'))
    assert len(baseline.episodes) == 2
    for sid in ('A', 'A2'):
        decision = buy(store, evidence, sid, now=NOW+timedelta(days=31))
        assert decision.allowed and decision.reason == 'GRANDFATHERED_EPISODE'
    assert initial.__dict__ == before
    assert projection.target_basket == {'A': D(10), 'A2': D(10)}


def test_same_issuer_class_loses_before_reservation_even_if_called_first(store, source):
    enroll(store, source)
    _, _, _, evidence = prepare(store, source, pending=('A', 'A2'))
    loser = buy(store, evidence, 'A2', reserve=True)
    assert not loser.allowed and loser.reason == 'ISSUER_CANONICAL_PRIORITY_CONFLICT'
    assert buy(store, evidence, 'A', reserve=True).allowed
    assert not buy(store, evidence, 'A2', reserve=True).allowed
    assert len(guard._claims(store, guard._binding(BINDING))) == 1


def test_distinct_issuers_admit_and_same_episode_reservation_is_idempotent(store, source):
    enroll(store, source)
    _, _, _, evidence = prepare(store, source, pending=('A', 'B'))
    assert buy(store, evidence, 'A', reserve=True).allowed
    first = deepcopy(store.records)
    assert buy(store, evidence, 'A', reserve=True, now=NOW+timedelta(seconds=1)).reason == 'ADMITTED_EPISODE'
    assert store.records == first
    assert buy(store, evidence, 'B', reserve=True).allowed


def test_preflight_does_not_reserve_and_final_submission_requires_reservation(store, source):
    enroll(store, source)
    _, plan, _, evidence = prepare(store, source, pending=('A',))
    assert buy(store, evidence, 'A').allowed
    assert guard._claims(store, guard._binding(BINDING)) == {}
    with pytest.raises(guard.IssuerAdmissionRefused, match='RESERVATION_REQUIRED'):
        guard.final_command_check(store, evidence=evidence, command=command('A', plan=plan.plan_id),
                                  reconciliation=reconciliation(), now=NOW)
    assert buy(store, evidence, 'A', reserve=True).allowed
    assert guard.final_command_check(store, evidence=evidence, command=command('A', plan=plan.plan_id),
                                    reconciliation=reconciliation(), now=NOW).allowed


def test_denied_model_episode_cannot_grandfather_on_next_day_or_new_plan(store, source):
    enroll(store, source, 'A')
    _, _, _, first = prepare(store, source, held=('A',), pending=('A2',), rec=reconciliation('A'))
    assert buy(store, first, 'A2', rec=reconciliation('A')).reason == 'ISSUER_CONFLICT'
    _, _, _, next_plan = prepare(store, source, held=('A', 'A2'), suffix='2', rec=reconciliation('A'))
    denied = buy(store, next_plan, 'A2', rec=reconciliation('A'))
    assert not denied.allowed and denied.reason == 'ISSUER_CONFLICT'
    shortfalls = [raw['body'] for key, raw in store.records.items() if key.startswith(guard.SHORTFALL_PREFIX)]
    assert len(shortfalls) == 2 and all(D(row['unmet_quantity']) == 10 for row in shortfalls)
    assert first.target_basket['A2'] == next_plan.target_basket['A2'] == '10'


def test_same_security_reentry_does_not_inherit_baseline_or_old_claim(store, source):
    enroll(store, source, 'A')
    _, _, _, evidence = prepare(store, source, pending=('A',), signal='2026-10-27')
    decision = buy(store, evidence, 'A', rec=reconciliation('A'))
    assert not decision.allowed and decision.reason == 'ISSUER_UNATTRIBUTED_EPISODE'


def test_unknown_incumbent_blocks_other_new_issuers_but_continuing_episode_survives(store, source):
    enroll(store, source, 'U')
    _, _, _, evidence = prepare(store, source, held=('U',), pending=('B',), rec=reconciliation('U'))
    assert buy(store, evidence, 'U', rec=reconciliation('U')).allowed
    blocked = buy(store, evidence, 'B', rec=reconciliation('U'))
    assert not blocked.allowed and blocked.reason == 'ISSUER_INCUMBENT_UNRESOLVED'


def test_unresolved_candidate_and_expired_evidence_preserve_positive_shortfall(store, source):
    enroll(store, source)
    _, _, _, evidence = prepare(store, source, pending=('U', 'B'))
    assert buy(store, evidence, 'U').reason == 'ISSUER_IDENTITY_UNRESOLVED'
    assert not buy(store, evidence, 'B', now=NOW+timedelta(days=30)).allowed
    assert evidence.target_basket == {'B': '10', 'U': '10'}


@pytest.mark.parametrize('status', [S.PLANNED, S.SEND_PENDING, S.ACKNOWLEDGED, S.UNKNOWN, S.PARTIALLY_FILLED, S.CANCEL_PENDING])
def test_all_plan_possibly_effective_buy_commands_keep_issuer_claim(store, source, status):
    enroll(store, source)
    store.commands = [command('A', status, epoch=2)]
    _, _, _, evidence = prepare(store, source, pending=('A2',), extra=('A',))
    assert not buy(store, evidence, 'A2', reserve=True).allowed


def test_cancelled_partial_fill_still_claims_issuer_when_attributed_position_remains(store, source):
    enroll(store, source)
    store.commands = [command('A', S.CANCELLED, filled='3')]
    _, _, _, evidence = prepare(store, source, pending=('A2',), extra=('A',))
    decision = buy(store, evidence, 'A2', rec=reconciliation(expected={'A': D(3)}))
    assert not decision.allowed and decision.reason == 'ISSUER_CONFLICT'


@pytest.mark.parametrize('kind', ['old_epoch_command', 'working_native_order'])
@pytest.mark.parametrize('changed', ['symbol', 'asset_id'])
def test_incumbent_native_identity_mismatch_blocks_otherwise_distinct_issuer(store, source, kind, changed):
    enroll(store, source)
    native = BrokerInstrument('A', 'WRONG' if changed == 'symbol' else SYMBOLS['A'],
                              'wrong-asset' if changed == 'asset_id' else 'native-A')
    rec = reconciliation()
    if kind == 'old_epoch_command':
        store.commands = [replace(command('A', S.UNKNOWN, epoch=2), instrument=native)]
    else:
        order = BrokerOrder(broker_order_id='native-working', client_key='sntl-native',
            instrument=native, side=Side.BUY, state=S.ACKNOWLEDGED, quantity=D(10))
        rec.observation = replace(rec.observation, orders=(order,))
    _, _, _, evidence = prepare(store, source, pending=('B',), extra=('A',), rec=rec)
    result = buy(store, evidence, 'B', rec=rec)
    assert not result.allowed and result.reason == 'ISSUER_INCUMBENT_UNRESOLVED'


def test_only_positive_obsolete_no_transport_history_can_ignore_planned_row(store, source):
    stale = command('A')
    store.commands = [stale]
    store.plans[stale.identity.plan_id] = SimpleNamespace(is_superseded=True,
        effective_session=date(2026, 10, 1), fingerprint=lambda: 'f'*64)
    with pytest.raises(guard.IssuerAdmissionRefused, match='POSSIBLY_EFFECTIVE'):
        enroll(store, source)
    store.histories[stale.client_key] = [{'from': None, 'to': 'PLANNED', 'filled': '0', 'detail': '', 'at': NOW}]
    baseline = enroll(store, source)
    assert baseline.excluded_unsent_proofs[0]['client_key'] == stale.client_key
    assert stale.state is S.PLANNED
    _, _, _, evidence = prepare(store, source, pending=('A2',), extra=('A',))
    assert buy(store, evidence, 'A2', reserve=True).allowed
    store.histories[stale.client_key].append({'from': 'PLANNED', 'to': 'UNKNOWN', 'filled': '0', 'detail': '', 'at': NOW})
    assert not buy(store, evidence, 'A2', reserve=True).allowed


@pytest.mark.parametrize('status', [S.UNKNOWN, S.SEND_PENDING, S.PARTIALLY_FILLED])
def test_enrollment_refuses_uncertain_or_working_commands(store, source, status):
    store.commands = [command('A', status)]
    with pytest.raises(guard.IssuerAdmissionRefused, match='COMMAND_PENDING'):
        enroll(store, source)
    assert not any(key.startswith(guard.ENROLLMENT_PREFIX) for key in store.records)


def test_enrollment_requires_native_positive_attribution_and_cannot_reseed(store, source):
    with pytest.raises(guard.IssuerAdmissionRefused, match='GENUINE_ATTRIBUTED'):
        guard.enroll(store, binding=BINDING, state=state(held=('A',)), snapshot=source,
            reconciliation=reconciliation('A', expected={}), instruments=instruments('A'), now=NOW)
    enrolled = enroll(store, source, 'A')
    assert guard.load_enrollment(store, binding=BINDING) == enrolled
    with pytest.raises(guard.IssuerAdmissionRefused, match='RESEED'):
        enroll(store, source, 'A', 'B')
    with pytest.raises(guard.IssuerAdmissionRefused, match='BINDING_CHANGED'):
        guard.load_enrollment(store, binding=DeploymentIdentity('issuer-test', 'alpaca', 'paper-issuer', 4))


def test_plan_retry_accepts_fresh_reconciliation_and_tamper_refuses(store, source):
    enroll(store, source)
    value, plan, projection, evidence = prepare(store, source, pending=('A',))
    fresh = reconciliation(at=NOW+timedelta(seconds=30), observation_id=99)
    retry = guard.prepare_plan_evidence(store, binding=BINDING, state=value, plan=plan,
        projection=projection, reconciliation=fresh, snapshot=source,
        instruments=instruments('A'), now=NOW+timedelta(seconds=31))
    assert retry == evidence
    key = guard._plan_key(evidence)
    store.records[key]['body']['target_basket']['A'] = '0'
    with pytest.raises(guard.IssuerAdmissionRefused, match='DIGEST_CHANGED'):
        buy(store, evidence, 'A')


def test_release_requires_ended_ownership_complete_zero_and_no_possible_command(store, source):
    enroll(store, source)
    _, _, _, evidence = prepare(store, source, pending=('A',))
    assert buy(store, evidence, 'A', reserve=True).allowed
    store.commands = [command('A', S.UNKNOWN)]
    assert guard.release_ended_claims(store, binding=BINDING, state=state(),
        reconciliation=reconciliation(), now=NOW) == ()
    store.commands = [command('A', S.CANCELLED, filled='3')]
    assert guard.release_ended_claims(store, binding=BINDING, state=state(),
        reconciliation=reconciliation(expected={'A': D(3)}), now=NOW) == ()
    store.commands = []
    assert guard.release_ended_claims(store, binding=BINDING, state=state(),
        reconciliation=reconciliation('A'), now=NOW) == ()
    assert len(guard.release_ended_claims(store, binding=BINDING, state=state(),
        reconciliation=reconciliation(), now=NOW)) == 1
    assert guard._claims(store, guard._binding(BINDING)) == {}


def test_sell_and_defensive_identity_never_depend_on_issuer_source(store):
    result = guard.final_command_check(None, evidence=None,
        command=command('A', side=Side.SELL), reconciliation=None, now=None)
    assert result.allowed and result.reason == 'REDUCTION'


def test_missing_lock_and_lost_transaction_do_not_publish_reservation(store, source):
    store.locked = False
    with pytest.raises(guard.IssuerAdmissionRefused, match='WRITER_LOCK_REQUIRED'):
        enroll(store, source)
    assert store.records == {}
    store.locked = True
    enroll(store, source)
    _, _, _, evidence = prepare(store, source, pending=('A',))
    with pytest.raises(RuntimeError):
        with store.transaction():
            assert buy(store, evidence, 'A', reserve=True).allowed
            raise RuntimeError('command admission failed before commit')
    assert guard._claims(store, guard._binding(BINDING)) == {}


@pytest.mark.parametrize('legacy_prefix', guard.LEGACY_PREFIXES)
def test_old_top_level_records_refuse_enrollment_without_copying(store, source, legacy_prefix):
    store.records[legacy_prefix + 'unpublished'] = {'old': 'preserved'}
    before = deepcopy(store.records)
    with pytest.raises(guard.IssuerAdmissionRefused, match='LEGACY_NAMESPACE_PRESENT'):
        enroll(store, source)
    assert store.records == before


@pytest.mark.parametrize('legacy_prefix', guard.LEGACY_PREFIXES)
def test_old_namespace_refuses_new_plan_and_new_episode_entry(store, source, legacy_prefix):
    enroll(store, source)
    _, _, _, proof = prepare(store, source, pending=('A',))
    store.records[legacy_prefix + 'old'] = {'old': 'preserved'}
    before = deepcopy(store.records)
    with pytest.raises(guard.IssuerAdmissionRefused, match='LEGACY_NAMESPACE_PRESENT'):
        prepare(store, source, pending=('A',), suffix='2')
    with pytest.raises(guard.IssuerAdmissionRefused, match='LEGACY_NAMESPACE_PRESENT'):
        buy(store, proof, 'A', reserve=True)
    assert store.records == before


def test_database_session_lock_and_rollback_boundary(pg, source, monkeypatch):
    monkeypatch.setattr(guard.journal, 'load_commands', lambda *_args, **_kw: ())
    with psycopg.connect(pg.sync_dsn) as first, psycopg.connect(pg.sync_dsn) as second:
        first.execute('CREATE TEMP TABLE sentinel_processed_sessions(cursor_name TEXT PRIMARY KEY, session DATE NOT NULL, state JSONB)')
        first.commit()
        first.execute('SELECT pg_advisory_lock(%s)', (guard.journal.WRITER_LOCK_KEY,))
        assert second.execute('SELECT pg_try_advisory_lock(%s)', (guard.journal.WRITER_LOCK_KEY,)).fetchone()[0] is False
        with pytest.raises(guard.IssuerAdmissionRefused, match='WRITER_LOCK_REQUIRED'):
            guard._lock(second)
        guard.enroll(first, binding=BINDING, state=state(), reconciliation=reconciliation(),
            snapshot=source, instruments={}, now=NOW)
        first.commit()
        _, _, _, evidence = prepare(first, source, pending=('A',))
        first.commit()
        assert buy(first, evidence, 'A', reserve=True).allowed
        first.rollback()
        assert guard._claims(first, guard._binding(BINDING)) == {}
        first.execute('SELECT pg_advisory_unlock(%s)', (guard.journal.WRITER_LOCK_KEY,))


def compose_executor(store, source, harness, monkeypatch, *, held=(), pending=()):
    """Real executor and real policy; only storage/transport use private fakes."""
    import asyncio
    from sentinel.execution import executor
    from sentinel.execution.plan import ExecutionPlan, OpeningIntent
    from sentinel.execution.target_reprojection import TargetProjection
    from tests.sentinel.test_issuer_executor_gate import DEPLOYMENT

    monkeypatch.setattr(__import__(__name__, fromlist=['BINDING']), 'BINDING', DEPLOYMENT)
    enroll(store, source, *held)
    canonical = state(held=held, pending=pending)
    intents = tuple(OpeningIntent(sid, slot, D(1000)) for slot, sid in enumerate(pending, len(held)))
    plan = ExecutionPlan('composed-plan', date(2026, 10, 26), date(2026, 10, 27), D(1),
        target_basket={sid: D(0) for sid in held + pending}, opening_intents=intents,
        shadow_snapshot_hash=canonical.state_hash, **DEPLOYMENT.to_dict())
    projection = TargetProjection(plan.plan_id, plan.fingerprint(), plan.effective_session,
        {}, (), {}, {sid: D(0 if sid in held else 10) for sid in held + pending})
    rec = reconciliation(*held)
    proof = guard.prepare_plan_evidence(store, binding=DEPLOYMENT, state=canonical,
        plan=plan, projection=projection, reconciliation=rec, snapshot=source,
        instruments=instruments(*(held + pending)), now=NOW, commands=[])

    async def observed(**_kwargs):
        assert harness.locked
        return rec

    monkeypatch.setattr(executor.R, 'reconcile', observed)

    def actual_policy(**kwargs):
        assert harness.locked
        return guard.check_buy(store, evidence=proof, security_id=kwargs['security_id'],
            reconciliation=kwargs['reconciliation'], now=NOW, commands=store.commands,
            reserve=kwargs['reserve'])

    native = {sid: BrokerInstrument(sid, SYMBOLS[sid], 'native-' + sid) for sid in held + pending}
    result = asyncio.run(executor.execute_session(broker=harness.broker, conn=store,
        deployment=DEPLOYMENT, plan=plan, instruments=native,
        today=plan.effective_session, target_projection=projection,
        buy_admission=actual_policy))
    return result, plan, projection, proof, canonical


def test_actual_executor_composes_same_issuer_guard_and_restart(store, source, harness, monkeypatch):
    result, plan, projection, proof, _canonical = compose_executor(
        store, source, harness, monkeypatch, pending=('A', 'A2'))
    assert [command.security_id for command in result.submitted] == ['A']
    assert result.deferred == ('A2',)
    assert projection.target_basket['A2'] == D(10)
    assert guard.load_plan_evidence(store, plan=plan, projection=projection) == proof
    restored = Memory()
    restored.records = deepcopy(store.records)
    assert not buy(restored, proof, 'A2').allowed
    assert buy(restored, proof, 'A', reserve=True).reason == 'ADMITTED_EPISODE'


def test_actual_executor_unknown_incumbent_blocks_buy_but_submits_sell(store, source, harness, monkeypatch):
    result, _plan, projection, _proof, _canonical = compose_executor(
        store, source, harness, monkeypatch, held=('U',), pending=('B',))
    assert [(command.security_id, command.side) for command in result.submitted] == [('U', Side.SELL)]
    assert result.deferred == ('B',)
    assert result.deferral_reasons['B'] == 'ISSUER_INCUMBENT_UNRESOLVED'
    assert projection.target_basket['B'] == D(10)


def test_composed_same_issuer_guard_has_removed_priority_falsifier(store, source, harness, monkeypatch):
    import inspect
    original = inspect.getsource(guard.check_buy)
    needle = 'elif current_issuer == issuer:'
    assert original.count(needle) == 1
    broken = original.replace(needle, 'elif False:')
    broken = broken.replace('if winner != security_id:', 'if False:')
    namespace = dict(vars(guard))
    exec(compile(broken, 'removed-issuer-conflict-guards', 'exec'), namespace)
    monkeypatch.setattr(guard, 'check_buy', namespace['check_buy'])
    with pytest.raises(AssertionError):
        test_actual_executor_composes_same_issuer_guard_and_restart(store, source, harness, monkeypatch)
