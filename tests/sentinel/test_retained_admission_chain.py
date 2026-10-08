"""Successive admitted executables authenticate the exact intermediate book."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from sentinel import runtime_admission as admission, rolling_daily_checkpoint as daily
from sentinel.economic_migration import POLICY, PROFILE_SHA256
from sentinel.feed.rolling_contract import digest


@pytest.fixture
def chain(monkeypatch):
    strategy = {'cash_distribution_policy': POLICY, 'economic_setting': 'unchanged',
                'data_semantics_source_sha256': '1'*64}
    config = {'starting_cash': '50000', 'validated_source_identity_sha256': '2'*64}
    runtime = {'schema': 'sentinel.shadow-runtime-identity/1', 'reviewed_shadow_config': config,
               'git_commit': '3'*40, 'runtime_image_digest': 'sha256:'+'4'*64}
    checkpoint = SimpleNamespace(observation_id='primary', starting_cash='50000',
        strategy_identity=strategy, runtime_identity=runtime, session='2026-09-14', publication={'version': 1})
    checkpoint.model_dump = lambda **kw: {'immutable_origin': 'a'*64}
    context = {'observation_id': 'primary', 'starting_cash': '50000',
        'strategy': {**strategy, 'data_semantics_source_sha256': '5'*64},
        'runtime': {**runtime, 'git_commit': '6'*40}}
    stored = {**strategy, 'data_semantics_source_sha256': '7'*64}
    retained = SimpleNamespace(observation_id='primary', starting_cash='50000',
        strategy_identity=stored, runtime_identity=runtime, session='2026-09-15',
        origin_sha256=digest(checkpoint.model_dump()), publication={'version': 2}, state_sha256='a'*64)
    rows = {}
    def append(strategy, process):
        value = admission.EconomicAdmission(observation_id='primary',
            origin_sha256=digest(checkpoint.model_dump()), book_runtime_sha256=digest(runtime),
            process_sha256=process, strategy_sha256=digest(strategy), manifest_sha256='8'*64,
            migration_profile_sha256=PROFILE_SHA256, origin_strategy_sha256=digest(checkpoint.strategy_identity), pitr={})
        raw = value.model_dump(by_alias=True)
        cursor = admission.PREFIX+'primary:'+process
        rows[cursor] = [checkpoint.session, {'admission': raw, 'hmac_sha256': admission._signature(raw)}]
        return cursor
    current_key = append(context['strategy'], digest(admission.process_binding(context['runtime'])))
    prior_key = append(stored, '9'*64)
    class Result:
        def __init__(self, rows): self.rows = rows
        def fetchone(self): return self.rows[0] if self.rows else None
        def __iter__(self): return iter(self.rows)
    class Connection:
        def execute(self, sql, params):
            if 'cursor_name=%s' in sql:
                return Result([rows[params[0]]] if params[0] in rows else [])
            assert "state->'admission'->>'strategy_sha256'=%s" in sql
            return Result([(key, *value) for key, value in rows.items()
                if key.startswith(params[0][:-1]) and value[1]['admission'].get('strategy_sha256') == params[1]])
    monkeypatch.setattr(admission.origin, 'read', lambda conn: checkpoint)
    monkeypatch.setattr(daily, 'read', lambda conn: retained)
    monkeypatch.setattr(admission, 'current_context', lambda **kw: deepcopy(context))
    monkeypatch.setenv('SENTINEL_SHADOW_STARTING_CASH', '50000')
    return Connection(), context, retained, checkpoint, rows, current_key, prior_key


def test_successive_admissions_keep_exact_retained_strategy_and_current_process(chain):
    conn, context, retained, checkpoint, rows, *_ = chain
    before = deepcopy(rows)
    bound = deepcopy(context)
    admission.bind_context(conn, bound)
    assert bound['runtime'] == checkpoint.runtime_identity
    assert bound['strategy'] == retained.strategy_identity != context['strategy']
    assert rows == before
    pub = SimpleNamespace(to_dict=lambda: retained.publication)
    assert admission.retained_publication_strategy(conn, pub) == retained.strategy_identity
    assert admission.retained_publication_strategy(conn, SimpleNamespace(to_dict=lambda: {'version': 3})) is None


@pytest.mark.parametrize('defect', ['missing_prior', 'missing_current', 'hmac', 'shape', 'origin',
    'book', 'observation', 'process', 'cursor', 'profile', 'origin_strategy', 'session',
    'unadmitted_strategy', 'economic_setting', 'cash_policy'])
def test_unproven_intermediate_book_or_target_is_refused(chain, defect):
    conn, context, retained, checkpoint, rows, current_key, prior_key = chain
    row = rows[prior_key]
    raw = row[1]['admission']
    if defect == 'missing_prior': del rows[prior_key]
    elif defect == 'missing_current': del rows[current_key]
    elif defect == 'hmac': row[1]['hmac_sha256'] = '0'*64
    elif defect == 'shape': raw['unknown'] = 'not ignored'
    elif defect == 'cursor': rows[prior_key+'0'] = rows.pop(prior_key)
    elif defect == 'session': row[0] = retained.session
    elif defect == 'unadmitted_strategy': retained.strategy_identity['data_semantics_source_sha256'] = 'e'*64
    elif defect == 'economic_setting':
        retained.strategy_identity['economic_setting'] = 'changed'
        raw['strategy_sha256'] = digest(retained.strategy_identity)
    elif defect == 'cash_policy':
        retained.strategy_identity['cash_distribution_policy'] = None
        raw['strategy_sha256'] = digest(retained.strategy_identity)
    else:
        key = {'origin': 'origin_sha256', 'book': 'book_runtime_sha256', 'observation': 'observation_id',
               'process': 'process_sha256', 'profile': 'migration_profile_sha256',
               'origin_strategy': 'origin_strategy_sha256'}[defect]
        raw[key] = 'foreign' if key == 'observation_id' else '0'*64
    if defect != 'hmac': row[1]['hmac_sha256'] = admission._signature(raw)
    before = deepcopy(context)
    with pytest.raises((RuntimeError, ValueError)):
        admission.bind_context(conn, context)
    assert context == before, 'refusal must not partially rebind the caller'


@pytest.mark.parametrize('defect', ['observation_id', 'starting_cash', 'origin_sha256', 'runtime_identity'])
def test_readiness_fallback_requires_exact_signed_checkpoint_binding(chain, defect):
    conn, _, retained, *_ = chain
    setattr(retained, defect, {} if defect == 'runtime_identity' else 'foreign')
    with pytest.raises(RuntimeError, match='RETAINED_PUBLICATION_CHECKPOINT_BINDING_CHANGED'):
        admission.retained_publication_strategy(conn, SimpleNamespace(to_dict=lambda: retained.publication))


@pytest.mark.parametrize('defect', [None, 'strategy', 'state_strategy', 'state_sha256', 'session'])
def test_dual_adapter_requires_exact_authenticated_checkpoint_state(chain, defect):
    conn, context, retained, *_ = chain
    values = dict(strategy=context['strategy'], state_strategy=retained.strategy_identity,
        state_sha256=retained.state_sha256, session=retained.session)
    if defect:
        values[defect] = {} if defect in {'strategy', 'state_strategy'} else 'foreign'
        with pytest.raises(RuntimeError, match='RETAINED_ADAPTER_STATE_BINDING_CHANGED'):
            admission.require_retained_state(conn, **values)
    else:
        admission.require_retained_state(conn, **values)


def test_paper_strategy_fallback_is_dual_only_and_rechecks_admissions(chain):
    from sentinel.paper.validation import _require_state_strategy, PaperActivationRefused
    conn, context, retained, _, rows, current_key, _ = chain
    state = SimpleNamespace(strategy_identity=retained.strategy_identity,
        state_hash=retained.state_sha256, last_processed_session=retained.session)
    with pytest.raises(PaperActivationRefused, match='differs from runtime'):
        _require_state_strategy(conn, state, context['strategy'])
    _require_state_strategy(conn, state, context['strategy'], retained_shadow=True)
    with pytest.raises(PaperActivationRefused, match='STATE_BINDING_CHANGED'):
        _require_state_strategy(conn, state, context['strategy'], retained_shadow=True, state_sha256='b'*64)
    del rows[current_key]
    with pytest.raises(PaperActivationRefused, match='ADMISSION_REQUIRED'):
        _require_state_strategy(conn, state, context['strategy'], retained_shadow=True)


@pytest.mark.parametrize('defect', [None, 'standalone', 'state', 'strategy', 'account', 'publication', 'effective'])
def test_complete_plan_authority_keeps_every_binding_around_retained_upgrade(chain, defect):
    from dataclasses import replace
    from datetime import date
    from decimal import Decimal
    from sentinel.authority import RolloutMode
    from sentinel.core.decision import publication_fingerprint
    from sentinel.execution.plan import ExecutionPlan
    from sentinel.paper.validation import _assert_plan_authorities, _hash, PaperActivationRefused
    conn, context, retained, *_ = chain
    state = SimpleNamespace(strategy_identity=retained.strategy_identity,
        state_hash=retained.state_sha256, last_processed_session=retained.session,
        data_version=2, last_decision={'session': retained.session, 'target_core_exposure': '1'})
    pub = SimpleNamespace(version=2, to_dict=lambda: retained.publication)
    bound = SimpleNamespace(identity=SimpleNamespace(deployment_id='deployment', broker='sim',
        broker_account_id='account', takeover_epoch=1))
    rollout = SimpleNamespace(mode=RolloutMode.PINNED_1_00, version=1, certificate_sha256=None)
    plan = ExecutionPlan(plan_id='', decision_session=date(2026,9,15), effective_session=date(2026,9,16),
        target_exposure=Decimal(1), data_version=2, shadow_snapshot_hash=state.state_hash,
        sentinel_transition_hash=_hash(state.last_decision), strategy_fingerprint=_hash(state.strategy_identity),
        publication_fingerprint=publication_fingerprint(pub), deployment_id='deployment', broker='sim',
        broker_account_id='account', takeover_epoch=1)
    changes = {'state': {'shadow_snapshot_hash':'b'*64}, 'strategy': {'strategy_fingerprint':'b'*64},
        'account': {'broker_account_id':'foreign'}, 'publication': {'publication_fingerprint':'b'*64},
        'effective': {'effective_session':date(2026,9,17)}}
    if defect in changes:
        plan = replace(plan, **changes[defect])
    plan = replace(plan, plan_id='sentinel-'+plan.fingerprint())
    arguments = dict(state=state, plan=plan, binding=bound, pinned=pub, frontier=retained.session,
        today=date(2026,9,16), runtime_identity=context['strategy'], rollout=rollout,
        retained_shadow=defect!='standalone')
    if defect:
        with pytest.raises(PaperActivationRefused):
            _assert_plan_authorities(conn, **arguments)
    else:
        _assert_plan_authorities(conn, **arguments)
