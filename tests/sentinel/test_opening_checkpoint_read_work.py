"""Owned canonical checkpoint reads, real MVCC and exact predecessor seams."""
from contextlib import nullcontext
from collections import Counter
from copy import deepcopy
import hashlib
import importlib
import inspect
import json
from pathlib import Path
import textwrap

import psycopg
import pytest

from sentinel import checkpoint_read_source_basis as basis, committed_read as reads
from sentinel import rolling_checkpoint as origin, rolling_daily_checkpoint as daily, schema
from sentinel import semantic_source_basis as semantic
from sentinel.feed.rolling_contract import digest
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg  # noqa: F401
from tests.sentinel.test_retained_binding_reuse import retained  # noqa: F401

BASE = 'e4d8671cb84af325fb5000cf8eaa2a4e0cf454c7'
FIXTURE_SHA = '8ba48d999f51d3ef8eaee65dc11a77d3884b5a76d037fef1b55df190c1b62702'
FIXTURE = Path(__file__).resolve().parents[1]/'support/checkpoint-read-e4d-sources.json'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def predecessors():
    raw = FIXTURE.read_bytes()
    assert sha(raw) == FIXTURE_SHA
    value = json.loads(raw)
    assert value['schema'] == 'sentinel.checkpoint-read-baseline/1' and value['revision'] == BASE
    assert set(value['modules']) == set(basis.BASELINES)
    for name, item in value['modules'].items():
        assert sha(item['source'].encode()) == item['sha256'] == basis.BASELINES[name]
    return value['modules']


@pytest.fixture
def checkpoints(conn, monkeypatch):
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'checkpoint-read-private-key-'+'a'*32)
    schema.ensure_schema(conn)
    cp = origin.Checkpoint(observation_id='primary', session='2026-09-14', starting_cash='100000',
        strategy_identity={}, runtime_identity={}, snapshot={}, publication={}, genesis_sha256='a'*64,
        record_sha256='b'*64, state_sha256='c'*64, input_value={'nested': {'value': [1, 2, 3]}},
        warmup_input_identity={}, precommit_timing={}, pitr={})
    origin.write(conn, cp)
    daily_cp = daily.Checkpoint(**{**cp.model_dump(by_alias=True), 'schema': daily.SCHEMA,
        'status': 'DAILY_CONTINUATION_COMMITTED', 'origin_sha256': digest(cp.model_dump(by_alias=True)),
        'history_anchor': {}})
    daily.write(conn, daily_cp, previous=cp)
    conn.commit()
    return cp, daily_cp


def measured_readers(monkeypatch):
    counts = Counter()
    for name, module, attribute in [('origin', origin, '_read'), ('daily', daily, '_read'),
                                     ('origin_hmac', origin, '_signature'), ('daily_hmac', daily, 'signature')]:
        original = getattr(module, attribute)
        def counted(*args, _name=name, _read=original, **kwargs):
            counts[_name] += 1
            return _read(*args, **kwargs)
        monkeypatch.setattr(module, attribute, counted)
    return counts


def test_exact_signed_readers_load_and_authenticate_once_per_owned_proof(conn, checkpoints, monkeypatch):
    counts = measured_readers(monkeypatch)
    with reads.proof_connection(conn, serialize_snapshot=True) as proof:
        for _ in range(3):
            assert origin.read(proof).model_dump() == checkpoints[0].model_dump()
            assert daily.read(proof).model_dump() == checkpoints[1].model_dump()
    assert counts == dict(origin=1, daily=1, origin_hmac=1, daily_hmac=1)
    origin.read(conn); origin.read(conn); conn.rollback()
    assert counts['origin'] == counts['origin_hmac'] == 3


def alias_oracle(conn):
    with reads.proof_connection(conn) as proof:
        first = origin.read(proof)
        first.input_value['nested']['value'].append('mutated')
        second = origin.read(proof)
        assert second.input_value['nested']['value'] == [1, 2, 3]
        assert first is not second
        second.input_value['nested']['value'].append('warm mutation')
        assert origin.read(proof).input_value['nested']['value'] == [1, 2, 3]


def test_first_and_warm_returns_never_alias_private_input(conn, checkpoints):
    alias_oracle(conn)


def test_first_read_returns_its_canonical_graph_without_a_second_restore(conn, checkpoints, monkeypatch):
    actual = origin._read; models = []
    def canonical(connection):
        result = actual(connection);models.append(result);return result
    monkeypatch.setattr(origin, '_read', canonical)
    with reads.proof_connection(conn) as proof:
        with monkeypatch.context() as first:
            first.setattr(reads.pickle, 'loads', lambda _: pytest.fail('first read reconstructed a second graph'))
            assert origin.read(proof) is models[0]
        assert origin.read(proof) == models[0] and origin.read(proof) is not models[0]


def test_bounded_buffer_falls_back_to_complete_reads_without_retaining_input(conn, checkpoints, monkeypatch):
    monkeypatch.setattr(reads, 'MAX_CHECKPOINT_BUFFER_BYTES', 1)
    counts = measured_readers(monkeypatch)
    packed = [];actual = reads._pack_checkpoint
    def count_pack(value, remaining):
        packed.append(1);return actual(value, remaining)
    monkeypatch.setattr(reads, '_pack_checkpoint', count_pack)
    with reads.proof_connection(conn) as proof:
        for _ in range(3):
            assert origin.read(proof) == checkpoints[0]
            owner = reads._checkpoint_owner.get()
            assert owner.values == {} and owner.buffered_bytes == 0
    assert counts['origin'] == counts['origin_hmac'] == 3
    assert len(packed) == 1, 'unchanged oversize input retried serialization'


def test_oversize_admission_memo_is_exact_and_owner_local(conn, checkpoints, monkeypatch):
    monkeypatch.setattr(reads, 'MAX_CHECKPOINT_BUFFER_BYTES', 1)
    packed = [];actual = reads._pack_checkpoint
    def count_pack(value, remaining):
        packed.append(1);return actual(value, remaining)
    monkeypatch.setattr(reads, '_pack_checkpoint', count_pack)
    metadata = reads._CheckpointOwner.metadata;version = [0]
    def native_version(owner, connection, cursor):
        row, key = metadata(owner, connection, cursor)
        return row+('native-test-version-'+str(version[0]),), key
    monkeypatch.setattr(reads._CheckpointOwner, 'metadata', native_version)
    with reads.proof_connection(conn) as proof:
        origin.read(proof);origin.read(proof)
        assert len(packed) == 1
        reader = origin._read
        monkeypatch.setattr(origin, '_read', lambda connection: reader(connection))
        origin.read(proof);origin.read(proof)
        assert len(packed) == 2
        monkeypatch.setattr(reads, 'MAX_CHECKPOINT_BUFFER_BYTES', 2)
        origin.read(proof);origin.read(proof)
        assert len(packed) == 3
        version[0] += 1
        origin.read(proof);origin.read(proof)
        assert len(packed) == 4
    with reads.proof_connection(conn) as proof:
        origin.read(proof)
        assert len(packed) == 5


def test_budget_is_total_across_both_checkpoint_members(conn, checkpoints, monkeypatch):
    canonical = origin.read(conn);conn.rollback()
    budget = len(reads._pack_checkpoint(canonical, reads.MAX_CHECKPOINT_BUFFER_BYTES))
    monkeypatch.setattr(reads, 'MAX_CHECKPOINT_BUFFER_BYTES', budget)
    with reads.proof_connection(conn) as proof:
        assert origin.read(proof) == checkpoints[0]
        assert daily.read(proof) == checkpoints[1]
        owner = reads._checkpoint_owner.get()
        assert set(owner.values) == {origin.CURSOR}
        assert owner.buffered_bytes == budget


def test_invalidated_bytes_are_evicted_before_the_replacement_load(conn, checkpoints, monkeypatch):
    with reads.proof_connection(conn) as proof:
        origin.read(proof)
        actual = origin._read
        def replacement(connection):
            owner = reads._checkpoint_owner.get()
            assert owner.values == {} and owner.buffered_bytes == 0
            return actual(connection)
        monkeypatch.setattr(origin, '_read', replacement)
        assert origin.read(proof) == checkpoints[0]


def test_removed_buffer_admission_is_detected(conn, checkpoints, monkeypatch):
    monkeypatch.setattr(reads._CheckpointBuffer, 'write', lambda self, value: self.buffer.write(value))
    with pytest.raises(AssertionError):
        test_bounded_buffer_falls_back_to_complete_reads_without_retaining_input(conn, checkpoints, monkeypatch)


def test_removed_negative_serialization_memo_is_detected(conn, checkpoints, monkeypatch):
    code = textwrap.dedent(inspect.getsource(reads.checkpoint))
    guard = 'owner.serialization_refusals[cursor] = admission'
    assert code.count(guard) == 1
    namespace = {}
    exec(compile(code.replace(guard, 'pass'), '<removed-serialization-refusal-memo>', 'exec'), vars(reads), namespace)
    monkeypatch.setattr(reads, 'checkpoint', namespace['checkpoint'])
    with pytest.raises(AssertionError, match='retried serialization'):
        test_bounded_buffer_falls_back_to_complete_reads_without_retaining_input(conn, checkpoints, monkeypatch)


def transaction_oracle(conn):
    with reads.proof_connection(conn) as proof:
        origin.read(proof)
        proof.rollback()
        proof.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        with pytest.raises(reads.CommittedReadRefused, match='TRANSACTION_CHANGED'):
            origin.read(proof)


def test_a_new_transaction_cannot_inherit_the_old_result(conn, checkpoints):
    transaction_oracle(conn)


def test_foreign_connection_and_nested_owner_cannot_borrow_material(conn, checkpoints, monkeypatch):
    counts = measured_readers(monkeypatch)
    with reads.proof_connection(conn) as proof:
        origin.read(proof)
        with psycopg.connect(conn.info.dsn) as other:
            origin.read(other); origin.read(other)
        with reads._checkpoint_scope(proof):
            assert origin.read(proof).input_value == checkpoints[0].input_value
        assert origin.read(proof).input_value == checkpoints[0].input_value
    assert counts['origin'] == 4


def test_live_pin_identity_cannot_change_during_read_reuse(conn, checkpoints, monkeypatch):
    from sentinel.feed import readiness_scope
    with reads.proof_connection(conn) as proof:
        origin.read(proof)
        monkeypatch.setattr(readiness_scope, 'capture', lambda c: object())
        with pytest.raises(reads.CommittedReadRefused, match='PIN_CHANGED'):
            origin.read(proof)


def test_receipt_key_change_reenters_complete_authentication(conn, checkpoints, monkeypatch):
    with reads.proof_connection(conn) as proof:
        origin.read(proof)
        monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'different-private-key-'+'b'*32)
        with pytest.raises(origin.RollingColdStartRefused, match='AUTHENTICATION_FAILED'):
            origin.read(proof)


@pytest.mark.parametrize('reader,cursor', [(origin, origin.CURSOR), (daily, daily.CURSOR)])
def test_concurrent_bad_signature_is_seen_by_the_next_proof(conn, checkpoints, reader, cursor):
    with reads.proof_connection(conn) as proof:
        original = reader.read(proof)
        with psycopg.connect(conn.info.dsn) as other:
            other.execute("UPDATE sentinel_processed_sessions SET state=jsonb_set(state,'{hmac_sha256}',to_jsonb(%s::text)) WHERE cursor_name=%s",
                          ('0'*64, cursor))
        # The original MVCC snapshot remains internally consistent; it is not
        # presented as a new current authority or carried into the next proof.
        assert reader.read(proof) == original
    with reads.proof_connection(conn) as proof:
        with pytest.raises(origin.RollingColdStartRefused, match='AUTHENTICATION_FAILED'):
            reader.read(proof)


def test_failed_complete_read_never_populates_a_positive_entry(conn, checkpoints, monkeypatch):
    original = origin._read
    calls = []
    def once(connection):
        calls.append(1)
        if len(calls) == 1:
            raise ValueError('injected canonical failure')
        return original(connection)
    monkeypatch.setattr(origin, '_read', once)
    with reads.proof_connection(conn) as proof:
        with pytest.raises(ValueError, match='canonical failure'):
            origin.read(proof)
        assert origin.read(proof) == checkpoints[0]
    assert len(calls) == 2


def test_expired_owner_unknown_cursor_and_absent_rows_do_not_gain_reuse(conn, checkpoints):
    with reads.proof_connection(conn) as proof:
        calls = []
        def read(_):
            calls.append(1); return {'mutable': []}
        for _ in range(2):
            reads.checkpoint(proof, cursor='unreviewed:v1', read=read)
        assert len(calls) == 2
        reads._checkpoint_owner.get().active = False
        with pytest.raises(reads.CommittedReadRefused, match='OWNER_CHANGED'):
            origin.read(proof)
    conn.execute('DELETE FROM sentinel_processed_sessions WHERE cursor_name=%s', (daily.CURSOR,))
    conn.commit()
    with reads.proof_connection(conn) as proof:
        assert daily.read(proof) is None and daily.read(proof) is None


def test_unowned_or_read_write_transaction_cannot_enable_reuse(conn, checkpoints):
    with reads._checkpoint_scope(conn):
        with pytest.raises(reads.CommittedReadRefused, match='OWNER_CHANGED'):
            origin.read(conn)
    conn.execute('SELECT 1')
    with reads._checkpoint_scope(conn):
        with pytest.raises(reads.CommittedReadRefused, match='TRANSACTION_REQUIRED'):
            origin.read(conn)
    conn.rollback()


def test_native_row_metadata_movement_during_load_refuses(conn, checkpoints, monkeypatch):
    original = reads._CheckpointOwner.metadata
    calls = []
    def changed(owner, connection, cursor):
        row, key = original(owner, connection, cursor)
        calls.append(1)
        return (row[:-1]+('changed-version',), key) if len(calls) == 2 else (row, key)
    monkeypatch.setattr(reads._CheckpointOwner, 'metadata', changed)
    with reads.proof_connection(conn) as proof:
        with pytest.raises(reads.CommittedReadRefused, match='CHANGED_DURING_READ'):
            origin.read(proof)


def test_removed_transaction_guard_is_detected(conn, checkpoints, monkeypatch):
    code = textwrap.dedent(inspect.getsource(reads._CheckpointOwner.metadata))
    target = 'elif row[:8] != self.transaction:'
    assert code.count(target) == 1
    namespace = {}
    exec(compile(code.replace(target, 'elif False:'), '<missing-transaction-guard>', 'exec'), vars(reads), namespace)
    monkeypatch.setattr(reads._CheckpointOwner, 'metadata', namespace['metadata'])
    with pytest.raises(pytest.fail.Exception):
        transaction_oracle(conn)


def test_removed_detachment_is_detected(conn, checkpoints, monkeypatch):
    original = reads.pickle.loads
    returned = []
    def shared(raw):
        if not returned:
            returned.append(original(raw))
        return returned[0]
    monkeypatch.setattr(reads.pickle, 'loads', shared)
    with pytest.raises(AssertionError):
        alias_oracle(conn)


def test_removed_post_read_version_guard_is_detected(conn, checkpoints, monkeypatch):
    code = textwrap.dedent(inspect.getsource(reads.checkpoint))
    guard = 'if owner.metadata(conn, cursor) != before:'
    assert code.count(guard) == 2
    namespace = {}
    exec(compile(code.replace(guard, 'if False:'), '<missing-read-version-guards>', 'exec'), vars(reads), namespace)
    monkeypatch.setattr(reads, 'checkpoint', namespace['checkpoint'])
    with pytest.raises(pytest.fail.Exception):
        test_native_row_metadata_movement_during_load_refuses(conn, checkpoints, monkeypatch)


def test_removed_read_reuse_is_detected_by_real_work_counts(conn, checkpoints, monkeypatch):
    monkeypatch.setattr(reads, 'checkpoint', lambda conn, *, cursor, read: read(conn))
    with pytest.raises(AssertionError):
        test_exact_signed_readers_load_and_authenticate_once_per_owned_proof(conn, checkpoints, monkeypatch)


@pytest.mark.parametrize('name', sorted(basis.BASELINES))
def test_exact_wrapper_reconstructs_the_independently_archived_module(name):
    records = predecessors()
    raw = Path(importlib.import_module(name).__file__).read_bytes()
    expected = basis.CAS_CANDIDATE if name == 'sentinel.rolling_daily_checkpoint' else basis.CANDIDATES[name]
    assert sha(raw) == expected
    before = basis.predecessor(name, raw)
    assert before == records[name]['source'].encode()
    assert semantic.canonical_contribution(name, raw) == semantic.canonical_contribution(name, before)


def test_daily_source_compares_equal_across_independent_physical_row_witnesses(conn, checkpoints):
    with reads.proof_connection(conn) as proof:
        left = daily.read(proof)
    with reads.proof_connection(conn) as proof:
        right = daily.read(proof)
    assert left._row_version != right._row_version
    assert left == right == checkpoints[1]
    assert left.model_copy(update={'history_anchor': {'changed': True}}) != right


@pytest.mark.parametrize('name', sorted(basis.BASELINES))
def test_unknown_neighbor_or_domain_change_cannot_inherit_old_identity(name):
    raw = Path(importlib.import_module(name).__file__).read_bytes()
    for changed in (raw+b'\n# unknown neighboring source\n',
                    raw.replace(b'if row is None:', b'if row is not None:', 1)):
        assert changed != raw
        assert basis.predecessor(name, changed) == changed
        assert semantic.canonical_contribution(name, changed) == sha(changed)


@pytest.mark.parametrize('change', ['schema', 'authority', 'base', 'before', 'after', 'missing', 'extra', 'reader'])
def test_source_pair_contract_is_closed_even_with_replaced_outer_pin(change, monkeypatch, tmp_path):
    value = json.loads(basis.PROFILE.read_bytes())
    name = next(iter(basis.BASELINES))
    if change == 'schema':value['schema'] = 'unknown/1'
    elif change == 'authority':value['authority_effect'] = 'BROKER'
    elif change == 'base':value['base_revision'] = '0'*40
    elif change in {'before', 'after'}:value['readers'][name][change] = '0'*64
    elif change == 'missing':value['readers'].pop(name)
    elif change == 'extra':value['readers']['unknown.module'] = deepcopy(value['readers'][name])
    else:value['module_sha256'] = '0'*64
    raw = json.dumps(value).encode(); path = tmp_path/'changed.json'; path.write_bytes(raw)
    monkeypatch.setattr(basis, 'PROFILE', path);monkeypatch.setattr(basis, 'PROFILE_SHA256', sha(raw))
    with pytest.raises(ValueError, match='CHECKPOINT_READ_SOURCE_'):
        basis._profile()


def test_profile_missing_tamper_duplicate_and_unknown_module_are_refused(monkeypatch, tmp_path):
    original = basis.PROFILE.read_bytes();path = tmp_path/'profile.json'
    monkeypatch.setattr(basis, 'PROFILE', path)
    with pytest.raises(FileNotFoundError):basis._profile()
    path.write_bytes(original+b' ')
    with pytest.raises(ValueError, match='WITNESS_CHANGED'):basis._profile()
    duplicate = original.replace(b'"authority_effect": "NONE",',b'"authority_effect": "NONE", "authority_effect": "NONE",')
    assert duplicate != original
    path.write_bytes(duplicate);monkeypatch.setattr(basis, 'PROFILE_SHA256', sha(duplicate))
    with pytest.raises(ValueError, match='DUPLICATE_KEY'):basis._profile()
    assert basis.predecessor('unreviewed.module', b'unknown') == b'unknown'


def test_full_economic_manifest_bytes_and_prior_action_witness_remain_unchanged():
    from sentinel import economic_manifest, operation_read_source_basis
    value = economic_manifest.identity(schema='checkpoint-read-qualification')
    assert value['economic_implementation']['preserved_behavior'] is True
    assert value['sha256'] == economic_manifest.PREDECESSOR_DATA_SEMANTICS_SHA256
    assert operation_read_source_basis._profile()['base_revision'] == '277160861e2353d8ad93d15da8e2615ebdb11c18'


def test_actual_nested_retained_binding_reuses_complete_checkpoint_readers(conn, retained, monkeypatch):
    from sentinel import runtime_admission as admission
    counts = measured_readers(monkeypatch)
    context = retained.context
    with monkeypatch.context() as canonical:
        canonical.setattr(reads, '_checkpoint_scope', lambda _: nullcontext())
        with reads.proof_connection(conn, serialize_snapshot=True) as proof:
            before = admission._retained_checkpoint_uncached(proof, deepcopy(context))
    old = dict(counts);counts.clear()
    with reads.proof_connection(conn, serialize_snapshot=True) as proof:
        after = admission._retained_checkpoint_uncached(proof, deepcopy(context))
    assert old['origin'] >= 2 and counts['origin'] == 1
    assert old['daily'] >= 2 and counts['daily'] == 1
    assert before == after
