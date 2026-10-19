"""Real signed checkpoint/admission proofs under owned callback SQL fences."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import is_dataclass
from types import SimpleNamespace

import psycopg
import pytest

from sentinel import runtime_admission as admission, rolling_daily_checkpoint as daily
from sentinel import schema, shadow_runtime, structural_verification as verified
from sentinel.economic_migration import POLICY, PROFILE_SHA256
from sentinel.execution import journal
from sentinel.feed import publication, readiness_scope
from sentinel.feed.rolling_contract import canonical_json, digest
from sentinel.retained_input_namespaces import PAPER_CURSOR_NAMES, PAPER_CURSOR_PREFIXES
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg  # noqa: F401


@pytest.fixture
def retained(conn, monkeypatch):
    """Only current-image attestation I/O is a fixture; SQL/HMAC/models are real."""
    schema.ensure_schema(conn)
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'retained-binding-test-key-' * 4)
    monkeypatch.setenv('SENTINEL_SHADOW_OBSERVATION_ID', 'primary')
    monkeypatch.setenv('SENTINEL_SHADOW_STARTING_CASH', '50000')
    strategy = {'cash_distribution_policy': POLICY, 'economic_setting': 'unchanged',
                'data_semantics_source_sha256': '1' * 64}
    runtime = {'schema': 'sentinel.shadow-runtime-identity/1',
        'reviewed_shadow_config': {'starting_cash': '50000',
            'validated_source_identity_sha256': '2' * 64},
        'git_commit': '3' * 40, 'runtime_image_digest': 'sha256:' + '4' * 64}
    initial = admission.origin.Checkpoint(observation_id='primary', starting_cash='50000',
        strategy_identity=strategy, runtime_identity=runtime, session='2026-09-14',
        snapshot={'snapshot_id': '5' * 64}, publication={'version': 1},
        genesis_sha256='6' * 64, record_sha256='7' * 64, state_sha256='8' * 64,
        input_value={'large_history': 'HISTORICAL_INPUT_PAYLOAD' * 1024},
        warmup_input_identity={}, precommit_timing={}, pitr={})
    admission.origin.write(conn, initial)
    stored_strategy = {**strategy, 'data_semantics_source_sha256': '9' * 64}
    checkpoint = daily.Checkpoint(**{**initial.model_dump(by_alias=True),
        'schema': daily.SCHEMA, 'status': 'DAILY_CONTINUATION_COMMITTED',
        'strategy_identity': stored_strategy, 'session': '2026-09-15',
        'publication': {'version': 2}, 'state_sha256': 'a' * 64,
        'origin_sha256': digest(initial.model_dump(by_alias=True)), 'history_anchor': {}})
    daily.write(conn, checkpoint, previous=initial)
    context = {'observation_id': 'primary', 'starting_cash': '50000',
        'controller': shadow_runtime._strategy()[0],
        'strategy': {**strategy, 'data_semantics_source_sha256': 'b' * 64},
        'runtime': {**runtime, 'git_commit': 'c' * 40}}
    def append(selected, process):
        value = admission.EconomicAdmission(observation_id='primary',
            origin_sha256=digest(initial.model_dump(by_alias=True)),
            book_runtime_sha256=digest(runtime), process_sha256=process,
            strategy_sha256=digest(selected), manifest_sha256='d' * 64,
            migration_profile_sha256=PROFILE_SHA256,
            origin_strategy_sha256=digest(strategy), pitr={})
        raw = value.model_dump(by_alias=True)
        cursor = admission.PREFIX + 'primary:' + process
        conn.execute('INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES (%s,%s,%s::jsonb)',
            (cursor, initial.session, canonical_json({'admission': raw, 'hmac_sha256': admission._signature(raw)})))
        return cursor
    current_key = append(context['strategy'], digest(admission.process_binding(context['runtime'])))
    prior_key = append(stored_strategy, 'e' * 64)
    conn.commit()
    calls = {'origin': 0, 'daily': 0, 'context': 0}
    origin_read, daily_read = admission.origin.read, daily.read
    def counted_origin(connection):
        calls['origin'] += 1
        return origin_read(connection)
    def counted_daily(connection):
        calls['daily'] += 1
        return daily_read(connection)
    def current_context(**kwargs):
        calls['context'] += 1
        return deepcopy(context)
    monkeypatch.setattr(admission.origin, 'read', counted_origin)
    monkeypatch.setattr(daily, 'read', counted_daily)
    monkeypatch.setattr(admission, 'current_context', current_context)
    return SimpleNamespace(context=context, checkpoint=checkpoint, initial=initial,
        current_key=current_key, prior_key=prior_key, calls=calls)


@contextmanager
def proof_scope(conn):
    # This read-only proof fixture owns the real SQL writer/publication locks.
    # Publication-content authentication is exercised by the gateway tests.
    pub = SimpleNamespace(evidence={'rolling_snapshot': {}}, to_dict=lambda: {'version': 2})
    conn.execute('SELECT pg_advisory_lock_shared(%s)', (publication.CORPUS_LOCK_KEY,))
    conn.execute('SELECT pg_advisory_lock(%s)', (journal.WRITER_LOCK_KEY,))
    try:
        with readiness_scope.pinned(conn, pub), verified.callback(conn) as scope:
            yield scope
    finally:
        conn.execute('SELECT pg_advisory_unlock(%s)', (journal.WRITER_LOCK_KEY,))
        conn.execute('SELECT pg_advisory_unlock_shared(%s)', (publication.CORPUS_LOCK_KEY,))
        conn.commit()


def publication_for(retained):
    return SimpleNamespace(to_dict=lambda: deepcopy(retained.checkpoint.publication))


def state_binding(retained):
    return dict(strategy=retained.context['strategy'], state_strategy=retained.checkpoint.strategy_identity,
        state_sha256=retained.checkpoint.state_sha256, session=retained.checkpoint.session)


def test_historical_binding_reuses_real_proof_across_exact_paper_writes(conn, retained):
    assert retained.context['strategy'] != retained.checkpoint.strategy_identity != retained.initial.strategy_identity
    with proof_scope(conn) as scope:
        assert admission.retained_publication_strategy(conn, publication_for(retained)) == retained.checkpoint.strategy_identity
        for name in (*PAPER_CURSOR_NAMES, *(prefix + 'binding-proof' for prefix in PAPER_CURSOR_PREFIXES)):
            conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES (%s,'2026-09-15','{}')", (name,))
            conn.commit()
            with psycopg.connect(conn.info.dsn) as fresh, scope.guard(fresh):
                admission.require_retained_state(fresh, **state_binding(retained))
                assert admission.retained_publication_strategy(fresh, publication_for(retained)) == retained.checkpoint.strategy_identity
        assert retained.calls['origin'] == 2 and retained.calls['daily'] == 2
        assert retained.calls['context'] == 1 + 2 * (len(PAPER_CURSOR_NAMES) + len(PAPER_CURSOR_PREFIXES))
        binding, context, selected = admission._retained_checkpoint(conn)
        assert is_dataclass(binding) and not hasattr(binding, 'input_value')
        assert b'HISTORICAL_INPUT_PAYLOAD' not in scope.values['retained-runtime-checkpoint'][2]
        binding.strategy_identity.clear()
        context['strategy'].clear()
        selected.clear()
        admission.require_retained_state(conn, **state_binding(retained))


@pytest.mark.parametrize('defect', ['origin_hmac', 'daily_hmac', 'admission_hmac',
    'missing_current', 'missing_prior', 'daily_origin', 'admission_binding'])
def test_reused_binding_refuses_real_checkpoint_or_admission_tamper(conn, retained, defect):
    with proof_scope(conn):
        admission.require_retained_state(conn, **state_binding(retained))
        if defect.startswith('missing_'):
            cursor = retained.current_key if defect == 'missing_current' else retained.prior_key
            conn.execute('DELETE FROM sentinel_processed_sessions WHERE cursor_name=%s', (cursor,))
        elif defect.endswith('_hmac'):
            cursor = {'origin_hmac': admission.origin.CURSOR, 'daily_hmac': daily.CURSOR,
                      'admission_hmac': retained.current_key}[defect]
            conn.execute("UPDATE sentinel_processed_sessions SET state=jsonb_set(state,'{hmac_sha256}',to_jsonb(repeat('0',64))) WHERE cursor_name=%s", (cursor,))
        else:
            cursor = daily.CURSOR if defect == 'daily_origin' else retained.current_key
            raw = conn.execute('SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s', (cursor,)).fetchone()[0]
            if defect == 'daily_origin':
                raw['checkpoint']['origin_sha256'] = '0' * 64
                raw['hmac_sha256'] = daily.signature(raw['checkpoint'])
            else:
                raw['admission']['process_sha256'] = '0' * 64
                raw['hmac_sha256'] = admission._signature(raw['admission'])
            conn.execute('UPDATE sentinel_processed_sessions SET state=%s::jsonb WHERE cursor_name=%s', (canonical_json(raw), cursor))
        conn.commit()
        with pytest.raises(admission.Refused):
            admission.require_retained_state(conn, **state_binding(retained))


def test_reuse_never_accepts_changed_supplied_state_or_publication(conn, retained):
    with proof_scope(conn):
        admission.require_retained_state(conn, **state_binding(retained))
        for field in ('strategy', 'state_strategy', 'state_sha256', 'session'):
            value = state_binding(retained)
            value[field] = {} if field in {'strategy', 'state_strategy'} else 'foreign'
            with pytest.raises(admission.Refused, match='ADAPTER_STATE_BINDING_CHANGED'):
                admission.require_retained_state(conn, **value)
        assert admission.retained_publication_strategy(conn, SimpleNamespace(to_dict=lambda: {'version': 3})) is None
        assert retained.calls['origin'] == 2 and retained.calls['daily'] == 2


@pytest.mark.parametrize('field', ['observation_id', 'starting_cash', 'strategy', 'runtime'])
def test_reuse_keys_fresh_current_context(conn, retained, field):
    with proof_scope(conn):
        admission.require_retained_state(conn, **state_binding(retained))
        if field == 'strategy':
            retained.context[field]['data_semantics_source_sha256'] = 'f' * 64
        elif field == 'runtime':
            retained.context[field]['git_commit'] = 'f' * 40
        else:
            retained.context[field] = 'foreign'
        with pytest.raises(admission.Refused):
            admission.require_retained_state(conn, **state_binding(retained))
        assert retained.calls['origin'] > 2


def test_reuse_keys_actual_controller_and_revalidates_current_executable(conn, retained, monkeypatch):
    with proof_scope(conn):
        admission.require_retained_state(conn, **state_binding(retained))
        controller = type(retained.context['controller'])
        original = controller.to_dict
        monkeypatch.setattr(controller, 'to_dict', lambda self: {**original(self), 'fixture_changed': True})
        admission.require_retained_state(conn, **state_binding(retained))
        assert retained.calls['origin'] == 4 and retained.calls['daily'] == 4
        def refuse(**kwargs):
            raise admission.Refused('RETAINED_CURRENT_EXECUTABLE_UNCERTIFIED')
        monkeypatch.setattr(admission, 'current_context', refuse)
        with pytest.raises(admission.Refused, match='CURRENT_EXECUTABLE_UNCERTIFIED'):
            admission.require_retained_state(conn, **state_binding(retained))


def test_current_context_key_falsifier_detects_removed_binding(conn, retained, monkeypatch):
    material = verified.material
    def without_context(connection, *, slot, key, load):
        return material(connection, slot=slot, key='context-removed', load=load)
    monkeypatch.setattr(verified, 'material', without_context)
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_reuse_keys_fresh_current_context(conn, retained, 'runtime')


@pytest.mark.parametrize('lost', ['writer', 'pin'])
def test_reused_binding_requires_live_original_ownership(conn, retained, lost):
    with proof_scope(conn) as scope:
        admission.require_retained_state(conn, **state_binding(retained))
        if lost == 'writer':
            conn.execute('SELECT pg_advisory_unlock(%s)', (journal.WRITER_LOCK_KEY,))
            error, message = verified.VerificationScopeRefused, 'WRITER_LOCK_LOST'
        else:
            conn.execute('SELECT pg_advisory_unlock_shared(%s)', (publication.CORPUS_LOCK_KEY,))
            error, message = publication.CorpusIncoherent, 'PUBLICATION_PIN_LOST'
        conn.commit()
        with psycopg.connect(conn.info.dsn) as fresh:
            with pytest.raises(error, match=message), scope.guard(fresh):
                admission.require_retained_state(fresh, **state_binding(retained))


def test_unscoped_binding_runs_complete_proof_every_time(conn, retained):
    admission.require_retained_state(conn, **state_binding(retained))
    admission.require_retained_state(conn, **state_binding(retained))
    assert retained.calls == {'origin': 4, 'daily': 4, 'context': 2}


@pytest.mark.parametrize('scoped', [False, True])
def test_absent_origin_still_skips_current_executable_context(conn, retained, monkeypatch, scoped):
    conn.execute('DELETE FROM sentinel_processed_sessions WHERE cursor_name=%s', (admission.origin.CURSOR,))
    conn.commit()
    monkeypatch.setattr(admission, 'current_context', lambda **kw: pytest.fail('absent origin validated executable'))
    if scoped:
        with proof_scope(conn):
            assert admission._retained_checkpoint(conn) == (None, None, None)
    else:
        assert admission._retained_checkpoint(conn) == (None, None, None)
