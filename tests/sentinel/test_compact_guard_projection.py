"""Private compact guard proofs keep real SQL fences and fresh refusals."""
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import dataclass
import inspect
import textwrap
from types import SimpleNamespace

import psycopg
import pytest

from sentinel import dual_plan_authority as sizing, dual_reconciliation as dual
from sentinel import rolling_runtime as rolling, schema, structural_verification as verified
from sentinel.execution import journal
from sentinel.feed import publication
from tests.sentinel.test_retained_binding_reuse import proof_scope
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg  # noqa: F401

SESSION = '2026-09-14'
STATE = 'a' * 64
RECORD = 'b' * 64


@dataclass
class Controller:
    setting: int = 1

    def to_dict(self):
        return {'setting': self.setting}


@dataclass
class LargeState:
    last_processed_session: str = SESSION
    data_version: int = 2
    strategy_identity: dict | None = None
    last_decision: dict | None = None
    concordance_witness_origin: str | None = None
    feed: str = 'UNUSED_FULL_FEED_GRAPH' * 5000

    @property
    def state_hash(self):
        pytest.fail('compact projection hashed the full state')


@pytest.fixture
def compact(conn, monkeypatch):
    schema.ensure_schema(conn)
    conn.execute('INSERT INTO sentinel_processed_sessions(cursor_name,session,state) '
                 "VALUES (%s,%s,'{}')", (rolling.origin.CURSOR, SESSION))
    conn.commit()
    context = dict(observation_id='primary', starting_cash='50000',
        controller=Controller(), strategy={'strategy': 'original'}, runtime={'source': 'actual'})
    expected = deepcopy(context)
    calls = dict(load=0, readiness=0, context=0)
    pub = {'version': 2}
    snapshot = {'snapshot': 'current'}
    certificate = rolling.authority.Authority(observation_id='primary', session=SESSION,
        checkpoint_sha256='c'*64, record_sha256=RECORD, state_sha256=STATE,
        input_sha256='d'*64, runtime_sha256='e'*64, publication_sha256='f'*64,
        previous_authority_sha256=None, previous_record_sha256=None,
        readiness_sha256='1'*64, timing={}, pitr={})
    state = LargeState(strategy_identity={'strategy': 'retained'},
                       last_decision={'session': SESSION})
    value = [rolling._StatusBinding(SESSION, deepcopy(pub), deepcopy(snapshot), STATE),
        None, SimpleNamespace(session=SESSION, state=state, record_sha256=RECORD), certificate, None]
    ready = [True]
    def load(connection, current):
        calls['load'] += 1
        if current != expected:
            raise rolling.Refused('CURRENT_CONTEXT_CHANGED')
        return tuple(value)
    def current_context(*_a, **_k):
        calls['context'] += 1
        return deepcopy(context)
    def validate(*_a, **_k):
        calls['readiness'] += 1
        if not ready[0]:
            raise rolling.inputs.RollingGoRefused('CURRENT_READINESS_REFUSED')
        return deepcopy(snapshot), SimpleNamespace(ready=True)
    monkeypatch.setattr(rolling.initial, '_context', current_context)
    monkeypatch.setattr(rolling.inputs, 'require_schemas', lambda c: c.rollback())
    monkeypatch.setattr(rolling.inputs, 'pinned', lambda c: nullcontext(
        SimpleNamespace(to_dict=lambda: deepcopy(pub))))
    monkeypatch.setattr(rolling.inputs, 'is_rolling', lambda p: True)
    monkeypatch.setattr(rolling.inputs, 'validate_status', validate)
    monkeypatch.setattr(rolling, '_status_closure', load)
    monkeypatch.setattr(dual.shadow_segments, 'active_segment',
        lambda *_a: SimpleNamespace(index=0, marker_sha256=None))
    with proof_scope(conn) as scope:
        conn.commit()
        def read():
            with psycopg.connect(conn.info.dsn) as fresh, scope.guard(fresh):
                return rolling._guard_status(fresh, observation_id='primary', starting_cash='50000')
        yield SimpleNamespace(scope=scope, read=read, calls=calls, context=context,
            value=value, pub=pub, ready=ready, snapshot=snapshot)


def test_projection_restores_full_graph_only_once_and_returns_detached_fields(compact, monkeypatch):
    first = compact.read()
    assert first.state_sha256 == STATE and first.record_sha256 == RECORD
    assert not hasattr(first.state, 'feed') and not hasattr(first.state, 'state_hash')
    assert not hasattr(first, 'shadow_verdict') and not hasattr(first, 'verification')
    record = compact.scope.values['rolling-checkpoint']
    assert b'UNUSED_FULL_FEED_GRAPH' in record[2]
    projected = compact.scope.projections[('rolling-checkpoint', 'rolling-guard-inputs')]
    assert b'UNUSED_FULL_FEED_GRAPH' not in projected[2]
    loads = verified.pickle.loads
    def small_only(raw):
        assert raw is not record[2], 'warm projection restored complete state'
        return loads(raw)
    monkeypatch.setattr(verified.pickle, 'loads', small_only)
    first.state.strategy_identity.clear()
    for _ in range(4):
        current = compact.read()
        assert current.state.strategy_identity == {'strategy': 'retained'}
    assert compact.calls == dict(load=1, readiness=5, context=5)


def test_projection_is_never_created_from_a_mutable_public_return(conn, compact):
    compact.read()
    key = compact.scope.values['rolling-checkpoint'][0]
    public = verified.material(conn, slot='rolling-checkpoint', key=key,
        load=lambda: pytest.fail('unexpected reload'))
    public[2].state.strategy_identity.clear()
    compact.scope.projections.clear()
    assert compact.read().state.strategy_identity == {'strategy': 'retained'}


def test_replacing_original_record_rebuilds_projection(compact, monkeypatch):
    projects = []
    project = rolling._guard_projection
    def counted(value):
        projects.append(1)
        return project(value)
    monkeypatch.setattr(rolling, '_guard_projection', counted)
    compact.read()
    old = compact.scope.values['rolling-checkpoint']
    compact.scope.values['rolling-checkpoint'] = (deepcopy(old[0]), old[1], old[2])
    compact.read()
    assert len(projects) == 2
    assert compact.scope.projections[('rolling-checkpoint', 'rolling-guard-inputs')][0] is not old


@pytest.mark.parametrize('name', ['unknown-economic:v1', 'dual-plan-sizing-authority:v1:test'])
def test_economic_or_unknown_write_reloads_full_proof(conn, compact, name):
    compact.read()
    conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES (%s,%s,'{}')", (name, SESSION))
    conn.commit()
    compact.read()
    assert compact.calls['load'] == 2


def test_exact_paper_write_keeps_projection(conn, compact):
    compact.read()
    original = compact.scope.projections[('rolling-checkpoint', 'rolling-guard-inputs')]
    conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES ('broker-observation:v4:compact',%s,'{}')", (SESSION,))
    conn.commit()
    compact.read()
    assert compact.calls['load'] == 1
    assert compact.scope.projections[('rolling-checkpoint', 'rolling-guard-inputs')] is original


@pytest.mark.parametrize('field', ['runtime', 'strategy', 'controller'])
def test_fresh_context_change_cannot_reuse_projection(compact, field):
    compact.read()
    if field == 'controller':
        compact.context[field].setting += 1
    else:
        compact.context[field]['changed'] = True
    with pytest.raises(rolling.Refused, match='CURRENT_CONTEXT_CHANGED'):
        compact.read()
    assert compact.calls['load'] == 2


@pytest.mark.parametrize('change', ['readiness', 'publication', 'snapshot'])
def test_current_validation_repeats_after_projection_is_warm(compact, change):
    compact.read()
    if change == 'readiness':
        compact.ready[0] = False
    elif change == 'publication':
        compact.pub['version'] += 1
    else:
        compact.snapshot['snapshot'] = 'different'
    with pytest.raises((rolling.Refused, rolling.inputs.RollingGoRefused)):
        compact.read()
    assert compact.calls['load'] == 1


@pytest.mark.parametrize('lost', ['writer', 'pin'])
def test_projection_refuses_lost_original_ownership(conn, compact, lost):
    compact.read()
    if lost == 'writer':
        conn.execute('SELECT pg_advisory_unlock(%s)', (journal.WRITER_LOCK_KEY,))
    else:
        conn.execute('SELECT pg_advisory_unlock_shared(%s)', (publication.CORPUS_LOCK_KEY,))
    conn.commit()
    with pytest.raises((verified.VerificationScopeRefused, publication.CorpusIncoherent)):
        compact.read()


@pytest.mark.parametrize('attested', ['missing', 'reconstruction'])
def test_projection_requires_prospective_attestation(compact, attested):
    if attested == 'missing':
        compact.value[3] = None
    else:
        raw = compact.value[3].model_dump()
        raw.pop('schema_id'); raw.pop('scope')
        compact.value[3] = rolling.authority.ReconstructionReceipt(**raw)
    with pytest.raises(rolling.Refused, match='ATTESTATION_REQUIRED|NOT_PROSPECTIVE'):
        compact.read()


def test_unscoped_projection_refuses_without_loading():
    with pytest.raises(verified.VerificationScopeRefused, match='SCOPE_REQUIRED'):
        verified.projected_material(None, slot='rolling-checkpoint', key='key',
            load=lambda: pytest.fail('unscoped projection loaded'),
            projection_slot='test', project=lambda v: v)
    with pytest.raises(rolling.Refused, match='SCOPE_REQUIRED'):
        rolling._guard_status(None, observation_id='primary', starting_cash='50000')


@pytest.mark.parametrize('failure', ['approval', 'handover'])
def test_private_intent_rechecks_current_transport_approval(compact, monkeypatch, failure):
    def read():
        with psycopg.connect(compact.scope.owner.info.dsn) as fresh, compact.scope.guard(fresh):
            return dual._verified_guard_intent(fresh, decision_session=SESSION,
                observation_id='primary', starting_cash='50000')
    read()
    if failure == 'approval':
        def refuse(*_a):
            raise dual.DualReconciliationPending('approval revoked')
        monkeypatch.setattr(dual, '_require_regenesis_transport_approval', refuse)
    else:
        monkeypatch.setattr(dual, '_require_regenesis_transport_approval',
            lambda *_a: SimpleNamespace(index=1))
        monkeypatch.setattr(dual, '_load_regenesis_handover', lambda *_a, **_k: None)
        monkeypatch.setattr(dual.journal, 'latest_plan',
            lambda *_a: SimpleNamespace(decision_session=SESSION))
    with pytest.raises(dual.DualReconciliationPending):
        read()


def test_private_sizing_acquires_commitment_and_keeps_canonical_cold_loader(conn, compact, monkeypatch):
    intent = compact.read()
    full = SimpleNamespace(record_sha256=RECORD, runtime_authority_sha256=intent.runtime_authority_sha256)
    calls = dict(intent=0, full=0, size=0)
    def private(*_a, **_k):
        calls['intent'] += 1
        return compact.read()
    def public(*_a, **_k):
        calls['full'] += 1
        return full
    def derive(*_a, **kwargs):
        assert kwargs['expected_shadow_result'] is full
        calls['size'] += 1
        return {'state_sha256': STATE, 'canonical_symbols': {'1': 'AAA'}}
    monkeypatch.setattr(dual, '_verified_guard_intent', private)
    monkeypatch.setattr(dual, 'verified_shadow_intent', public)
    monkeypatch.setattr(sizing, '_rederive_plan', derive)
    plan = SimpleNamespace(decision_session=SESSION, to_dict=lambda: {'plan': 'exact'})
    def read():
        return sizing._rederive_guard_plan(conn, plan=plan, binding='account', rollout_state='rollout',
            observation_id='primary', starting_cash='50000')
    _, proof = read()
    proof['canonical_symbols'].clear()
    assert read()[1]['canonical_symbols'] == {'1': 'AAA'}
    assert calls == dict(intent=2, full=1, size=1)
    with pytest.raises(TypeError):
        sizing._rederive_guard_plan(conn, plan=plan, binding='account', rollout_state='rollout',
            observation_id='primary', starting_cash='50000', state_sha256=STATE)


def test_public_sizing_keeps_hashing_mutated_caller_state(conn, compact, monkeypatch):
    intent = compact.read()
    class MutableState:
        state_hash = STATE
    expected = SimpleNamespace(state=MutableState(), record_sha256=RECORD,
        runtime_authority_sha256=intent.runtime_authority_sha256)
    plan = SimpleNamespace(decision_session=SESSION, to_dict=lambda: {'plan': 'exact'})
    def derive(*_a, **kwargs):
        if kwargs['expected_shadow_result'].state.state_hash != STATE:
            raise sizing.DualPlanAuthorityRefused('mutated supplied state')
        return {'state_sha256': STATE}
    monkeypatch.setattr(sizing, '_rederive_plan', derive)
    monkeypatch.setattr(dual, '_verified_guard_intent', lambda *_a, **_k: compact.read())
    monkeypatch.setattr(dual, 'verified_shadow_intent', lambda *_a, **_k: expected)
    sizing._rederive_guard_plan(conn, plan=plan, binding='account', rollout_state='rollout',
        observation_id='primary', starting_cash='50000')
    sizing.rederive_plan(conn, plan=plan, binding='account', rollout_state='rollout', expected_shadow_result=expected)
    expected.state.state_hash = 'd'*64
    with pytest.raises(sizing.DualPlanAuthorityRefused, match='mutated supplied state'):
        sizing.rederive_plan(conn, plan=plan, binding='account', rollout_state='rollout', expected_shadow_result=expected)


@pytest.mark.parametrize('field', ['state', 'record', 'authority'])
def test_private_cold_sizing_refuses_changed_commitments(conn, compact, monkeypatch, field):
    intent = compact.read()
    full = SimpleNamespace(record_sha256=RECORD, runtime_authority_sha256=intent.runtime_authority_sha256)
    proof = {'state_sha256': STATE}
    if field == 'state':
        proof['state_sha256'] = 'f'*64
    elif field == 'record':
        full.record_sha256 = 'f'*64
    else:
        full.runtime_authority_sha256 = 'f'*64
    monkeypatch.setattr(dual, '_verified_guard_intent', lambda *_a, **_k: compact.read())
    monkeypatch.setattr(dual, 'verified_shadow_intent', lambda *_a, **_k: full)
    monkeypatch.setattr(sizing, '_rederive_plan', lambda *_a, **_k: proof)
    plan = SimpleNamespace(decision_session=SESSION, to_dict=lambda: {'plan': 'exact'})
    with pytest.raises(sizing.DualPlanAuthorityRefused, match='commitment changed'):
        sizing._rederive_guard_plan(conn, plan=plan, binding='account', rollout_state='rollout',
            observation_id='primary', starting_cash='50000')


def _mutant(function, before, after):
    source = textwrap.dedent(inspect.getsource(function))
    assert source.count(before) == 1
    namespace = {}
    exec(compile(source.replace(before, after), '<private-guard-falsifier>', 'exec'),
         function.__globals__, namespace)
    return namespace[function.__name__]


@pytest.mark.parametrize('field', ['state', 'record', 'authority'])
def test_commitment_guard_falsifier_detects_removed_comparison(conn, compact, monkeypatch, field):
    before = """if (proof['state_sha256'] != intent.state_sha256
                or full.record_sha256 != intent.record_sha256
                or full.runtime_authority_sha256 != intent.runtime_authority_sha256):"""
    monkeypatch.setattr(sizing, '_rederive_guard_plan',
        _mutant(sizing._rederive_guard_plan, before, 'if False:'))
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_private_cold_sizing_refuses_changed_commitments(conn, compact, monkeypatch, field)


def test_original_record_identity_falsifier_detects_removed_binding(compact, monkeypatch):
    monkeypatch.setattr(verified, 'projected_material', _mutant(verified.projected_material,
        'retained[0] is not record or ', ''))
    with pytest.raises(AssertionError):
        test_replacing_original_record_rebuilds_projection(compact, monkeypatch)


def test_readiness_falsifier_detects_removed_current_validation(compact, monkeypatch):
    monkeypatch.setattr(rolling, '_guard_status', _mutant(rolling._guard_status,
        '_current(conn, checkpoint, pub)', 'None'))
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_current_validation_repeats_after_projection_is_warm(compact, 'readiness')


@pytest.mark.parametrize('native', [True, False])
def test_private_intent_preserves_typed_source_frontier_pending(monkeypatch, native):
    from sentinel.feed.rolling_go_inputs import RollingSourceFrontierPending
    def refuse(*_a, **_k):
        cls = RollingSourceFrontierPending if native else RuntimeError
        raise cls('RollingSourceFrontierPending: unavailable')
    monkeypatch.setattr(rolling, '_guard_status', refuse)
    expected = dual.DualReconciliationPending if native else dual.DualReconciliationRefused
    with pytest.raises(expected):
        dual._verified_guard_intent(None, decision_session=SESSION,
            observation_id='primary', starting_cash='50000')
