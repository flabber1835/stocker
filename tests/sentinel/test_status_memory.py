"""Fresh database ownership, full genesis comparison and single verified closure."""
from copy import deepcopy
import hashlib
import gc
import json
import weakref
from dataclasses import asdict
from pathlib import Path

import pytest

from sentinel import rolling_daily_checkpoint as checkpoints, rolling_initialization as initial
from sentinel import shadow_observation as shadow, rolling_runtime as runtime
from sentinel.feed.rolling_contract import canonical_json
from tests.sentinel.test_rolling_initialization import OBS, ready, start  # noqa: F401
from tests.sentinel.test_rolling_go_inputs import issuer_source, published  # noqa: F401
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401

__all__ = ['ready', 'issuer_source', 'published', 'operational_source', 'conn', 'pg', 'source']


def independently_unpacked(value):
    """Standard-library inverse for the physical format, never the store decoder."""
    import base64
    import zlib
    metadata = value.pop('_sentinel_series_storage', None)
    if metadata is not None:
        series = {}
        for group in metadata['groups']:
            raw = zlib.decompress(base64.b64decode(group['data']))
            assert len(raw) == group['bytes']
            assert hashlib.sha256(raw).hexdigest() == group['sha256']
            series.update(json.loads(raw))
        value[metadata['field']]['feed']['series'] = series
    return value


@pytest.mark.parametrize('length', [0, 1, 255, 256, 257, 512, 513, 1301])
def test_batched_json_matches_independent_standard_encoder(length):
    from sentinel.core.session import _canonical_chunks, _hash, _validate_json
    values = [None, True, False, -0.0, 1e-300, 1e300, -2**64, 2**64,
              '\U0001f642\n"\\\ud800', 'x'*65, [2, 1], {'z': 3, 'a': 2}]
    value = {'z': [values[i % len(values)] for i in range(length)],
             'a': tuple(range(length)), 'numeric_keys': {2: 'b', 1: 'a'}}
    expected = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    assert ''.join(_canonical_chunks(value)) == expected
    expected_hash = hashlib.sha256(expected.encode('ascii')).hexdigest()
    assert _hash(value) == shadow._sha256(value) == expected_hash
    _validate_json(value)


def test_batched_json_fuzz_and_final_element_commitment():
    import random
    from sentinel.core.session import _canonical_chunks, _hash
    rng = random.Random(399)
    def generate(depth):
        if depth == 0:
            return rng.choice([None, False, rng.uniform(-1e40, 1e40), rng.randrange(-2**80, 2**80),
                               ''.join(chr(rng.randrange(0x110000)) for _ in range(10))])
        children = [generate(depth-1) for _ in range(rng.randrange(6))]
        return children if rng.randrange(2) else {str(i): v for i, v in enumerate(children)}
    for _ in range(100):
        value = generate(4)
        assert ''.join(_canonical_chunks(value)) == json.dumps(
            value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    series = list(range(1301))
    original = _hash(series)
    series[-1] = -999
    assert _hash(series) != original


@pytest.mark.parametrize('invalid', [float('nan'), float('inf'), -float('inf'), object(),
                                    {1: 'a', 'z': 'b'}, {('invalid',): 1}])
def test_batched_json_rejects_invalid_value_in_last_batch(invalid):
    from sentinel.core.session import _canonical_chunks, _hash, _validate_json
    value = {'array': [0]*512 + [invalid]}
    with pytest.raises((TypeError, ValueError)):
        json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    for operation in (lambda v: list(_canonical_chunks(v)), _hash, _validate_json):
        with pytest.raises((TypeError, ValueError)):
            operation(value)
    with pytest.raises(shadow.ShadowObservationRefused):
        shadow._sha256(value)


def test_batched_json_refuses_cycles_but_allows_shared_children():
    from sentinel.core.session import _canonical_chunks
    child = [1, 2]
    assert ''.join(_canonical_chunks([child, child])) == '[[1,2],[1,2]]'
    child.append({'parent': child})
    with pytest.raises(ValueError, match='Circular reference'):
        list(_canonical_chunks(child))


def test_batched_json_never_encodes_a_whole_large_array():
    import tracemalloc
    from sentinel.core.session import _canonical_chunks
    value = {'prices': [1.25]*100001}
    expected = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                        allow_nan=False).encode()).hexdigest()
    digest = hashlib.sha256()
    tracemalloc.start()
    try:
        for chunk in _canonical_chunks(value):
            digest.update(chunk.encode('ascii'))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert digest.hexdigest() == expected
    # Incremental scratch space, measured after the caller-owned input exists.
    # This budget is independent of batch size or number of encoder calls.
    assert peak < 256*1024, f'encoded array allocated {peak} bytes of scratch space'


@pytest.mark.parametrize('genesis', [False, True])
@pytest.mark.parametrize('size', [0, 1, 128, 129, 513])
def test_database_batched_insert_preserves_complete_value_and_rollback(conn, genesis, size):
    from sentinel import schema
    schema.ensure_schema(conn)
    store = shadow.PostgresShadowObservationStore(conn, observation_id='bounded-write', commit_genesis=False)
    field = 'initial_state' if genesis else 'state'
    candidate = {'observation_id': 'bounded-write', 'first_session': '2026-09-14', 'session': '2026-09-14',
                 'unrelated': {'unicode': '\u00e9', 'fields': [False, None, 1.25]},
                 field: {'feed': {'series': {str(i): {'prices': [i, 1.25, None], 'label': 'a\\"\n'}
                                            for i in range(size)}, 'other': ['kept']},
                         'wealth_core': {'cash': 1985.80372}}}
    expected = json.loads(json.dumps(candidate, allow_nan=False))
    append = store.append_genesis if genesis else store.append
    name = store._genesis_name if genesis else store._name('2026-09-14')
    append(candidate)
    assert independently_unpacked(conn.execute('SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s', (name,)).fetchone()[0]) == expected
    assert not conn.execute("SELECT 1 FROM pg_class WHERE relnamespace=pg_my_temp_schema() AND relname LIKE 'shadow_insert_%'").fetchall()
    append(candidate)
    changed = deepcopy(candidate)
    changed['unrelated']['fields'][-1] = 999
    with pytest.raises(shadow.ShadowObservationRefused, match='different evidence'):
        append(changed)
    conn.rollback()
    assert conn.execute('SELECT count(*) FROM sentinel_processed_sessions WHERE cursor_name=%s', (name,)).fetchone()[0] == 0
    append(candidate)
    conn.commit()
    assert independently_unpacked(conn.execute('SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s', (name,)).fetchone()[0]) == expected


def test_database_batched_insert_refuses_missing_last_series(conn, monkeypatch):
    from sentinel import observation_storage, schema
    schema.ensure_schema(conn)
    store = shadow.PostgresShadowObservationStore(conn, observation_id='bounded-write')
    candidate = {'observation_id': 'bounded-write', 'session': '2026-09-14',
                 'state': {'feed': {'series': {str(i): {'prices': [i]} for i in range(257)}}}}
    insert = observation_storage.insert
    def corrupt(conn, **kwargs):
        changed = deepcopy(kwargs['candidate'])
        del changed['state']['feed']['series']['256']
        insert(conn, **{**kwargs, 'candidate': changed})
    monkeypatch.setattr(observation_storage, 'insert', corrupt)
    with pytest.raises(shadow.ShadowObservationRefused, match='different evidence'):
        store.append(candidate)
    conn.rollback()
    assert store.records() == []


def test_observation_storage_is_part_of_economic_source_identity(tmp_path, monkeypatch):
    from sentinel import observation_storage
    from sentinel.core import decision
    before = decision.data_semantics_source_identity()['sha256']
    changed = tmp_path/'observation_storage.py'
    changed.write_bytes(Path(observation_storage.__file__).read_bytes() + b'\n# simulated implementation edit\n')
    monkeypatch.setattr(observation_storage, '__file__', str(changed))
    assert decision.data_semantics_source_identity()['sha256'] != before


@pytest.mark.parametrize('stored,expected', [
    ('1.00000000000000001', 1.0), ('0.100000000000000001', .1), ('0.1', .1),
    ('1', 1.0), ('true', 1), ('0', False), ('null', None),
    ('{"v":[1.00000000000000001]}', {'v': [1.0]}),
    ('{"v":[1.0,null,true]}', {'v': [1, None, True]}),
    ('{"v":[]}', {'v': {}}), ('{}', {'extra': None})])
def test_exact_json_comparison_matches_postgresql_numeric_and_type_oracle(conn, stored, expected):
    from decimal import Decimal
    from sentinel.observation_storage import exact_value_equal
    sql_equal = conn.execute('SELECT %s::jsonb=%s::jsonb', (stored, json.dumps(expected))).fetchone()[0]
    actual = json.loads(stored, parse_float=Decimal)
    assert exact_value_equal(actual, expected) is sql_equal


@pytest.mark.parametrize('genesis', [False, True])
def test_database_retry_refuses_sub_float_precision_corruption(conn, genesis):
    from sentinel import schema
    schema.ensure_schema(conn)
    store = shadow.PostgresShadowObservationStore(conn, observation_id='precise-write', commit_genesis=False)
    candidate = {'observation_id': 'precise-write', 'first_session': '2026-09-14', 'session': '2026-09-14',
                 'price': 1.0, 'genesis_sha256': 'a'*64}
    append = store.append_genesis if genesis else store.append
    name = store._genesis_name if genesis else store._name('2026-09-14')
    append(candidate)
    conn.commit()
    conn.execute("UPDATE sentinel_processed_sessions SET state=jsonb_set(state,'{price}','1.00000000000000001') WHERE cursor_name=%s", (name,))
    conn.commit()
    if genesis:
        assert store.matches_genesis(candidate) is False
    with pytest.raises(shadow.ShadowObservationRefused, match='different evidence'):
        append(candidate)


def assert_original_serialization(state):
    from sentinel.core import session
    namespace = dict(vars(session), asdict=asdict)
    oracle = Path(__file__).with_name('fixtures')/'session_serializer_99410e5a.txt'
    exec(compile(oracle.read_text(), str(oracle), 'exec'), namespace)
    expected = namespace['to_dict'](state)
    actual = state.to_dict()
    assert actual == expected
    assert state.state_hash == hashlib.sha256(json.dumps(expected, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    if actual['feed']['series']:
        sid = next(iter(actual['feed']['series']))
        actual['feed']['series'][sid]['signal_closes'][0] = -999
        assert namespace['to_dict'](state) == expected
    actual['wealth_core']['cash'] = -999
    assert namespace['to_dict'](state) == expected


def test_database_genesis_comparison_checks_complete_payload_and_row_session(conn):
    from sentinel import schema
    schema.ensure_schema(conn)
    store = shadow.PostgresShadowObservationStore(conn, observation_id='memory-check', commit_genesis=False)
    expected = {'observation_id': 'memory-check', 'first_session': '2026-09-14',
                'deep': {'prices': [1.25, 2.5], 'label': '\u00e9'}, 'genesis_sha256': 'a'*64}
    assert store.matches_genesis(expected) is None
    conn.execute('INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES(%s,%s,%s::jsonb)',
                 (store._genesis_name, expected['first_session'], canonical_json(expected)))
    assert store.matches_genesis(expected) is True
    changed = deepcopy(expected)
    changed['deep']['prices'][-1] = 3.5
    # The advertised digest is unchanged: equality must inspect the payload.
    assert store.matches_genesis(changed) is False
    conn.execute('UPDATE sentinel_processed_sessions SET session=%s WHERE cursor_name=%s',
                 ('2026-09-11', store._genesis_name))
    assert store.matches_genesis(expected) is False


def test_database_reads_transfer_fresh_objects_without_roundtrip(conn, monkeypatch):
    from sentinel import schema
    schema.ensure_schema(conn)
    store = shadow.PostgresShadowObservationStore(conn, observation_id='memory-check', commit_genesis=False)
    value = {'first_session': '2026-09-14', 'nested': {'values': [1, 2]}}
    conn.execute('INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES(%s,%s,%s::jsonb)',
                 (store._genesis_name, value['first_session'], canonical_json(value)))
    monkeypatch.setattr(shadow, '_as_mapping', lambda *_a, **_kw: pytest.fail('duplicate JSON round trip'))
    first = store.genesis()
    first['nested']['values'][0] = 999
    assert store.genesis() == value


def test_formed_checkpoint_reuses_verified_observer_and_retains_economics(conn, ready, monkeypatch):
    expected = start(conn)
    context = initial._context(OBS, 100_000)
    calls = []
    resume = shadow.ShadowObserver.resume.__func__
    def counted(cls, **kwargs):
        calls.append(1)
        assert len(calls) == 1, 'formed closure reconstructed its observer twice'
        return resume(cls, **kwargs)
    monkeypatch.setattr(shadow.ShadowObserver, 'resume', classmethod(counted))
    conn.rollback()
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    checkpoint, observer, result = checkpoints.load(conn, context)
    assert len(calls) == 1
    assert result.state.state_hash == expected.state.state_hash == checkpoint.state_sha256
    assert result.strategy_nav == '100000'
    assert result.state.wealth_core == expected.state.wealth_core
    assert result.state.wealth_core['episodes'] and not result.state.pending
    # Restore must preserve actual formation trades, not put their spend back
    # into cash. Reconcile independently from the canonical ledger movements.
    events = result.state.ledger['events']
    assert any(event['event_type'] == 'BUY' for event in events)
    assert result.state.wealth_core['cash'] == pytest.approx(
        100000 + sum(event['cash_delta'] for event in events), abs=1e-7, rel=0)
    assert observer.genesis_sha256 == checkpoint.genesis_sha256
    assert_original_serialization(result.state)
    for table in ('sentinel_commands', 'sentinel_fills'):
        assert conn.execute('SELECT count(*) FROM '+table).fetchone()[0] == 0


def test_genesis_recheck_rejects_changed_payload_after_resume(conn, ready):
    start(conn)
    context = initial._context(OBS, 100_000)
    _checkpoint, observer, _result = checkpoints.load(conn, context)
    conn.execute("UPDATE sentinel_processed_sessions SET state=jsonb_set(state,'{initial_state,wealth_core,cash}','1')"
                 ' WHERE cursor_name=%s', (observer.store._genesis_name,))
    with pytest.raises(shadow.ShadowObservationRefused, match='genesis changed'):
        observer.verify_history()


def test_daily_checkpoint_verifies_history_once(conn, published, operational_source, monkeypatch):
    from tests.sentinel.test_rolling_daily import refresh
    runtime.advance(conn, through='2026-09-14', observation_id=OBS, starting_cash=100_000)
    refresh(conn, operational_source, monkeypatch)
    # The fixture's deployment identity is an explicitly external test authority.
    expected = runtime.advance(conn, through='2026-09-15', observation_id=OBS, starting_cash=100_000)
    calls = []
    history = shadow.ShadowObserver._history
    def counted(self, **kwargs):
        calls.append(1)
        assert len(calls) == 1, 'daily closure duplicated full history validation'
        assert kwargs.get('consume_seed') is True, 'status retained the advancement seed'
        return history(self, **kwargs)
    monkeypatch.setattr(shadow.ShadowObserver, '_history', counted)
    result = runtime.status(conn, observation_id=OBS, starting_cash=100_000)
    assert len(calls) == 1
    assert result.state.wealth_core['episodes']
    assert result.state.state_hash == expected.state.state_hash
    assert result.runtime_authority_sha256 == expected.runtime_authority_sha256
    assert result.strategy_nav == expected.strategy_nav
    assert_original_serialization(result.state)


@pytest.mark.parametrize('value', [None, True, -0.0, 1e-30, '\u00e9\n\"',
    {'z': [1, 1.0, -2.25, None], 'a': {'unicode': '\U0001f642'}},
    {1: ['integer key'], 2: 'second'}, {'values': list(range(2000))}])
def test_incremental_digest_matches_independent_json_bytes(value, monkeypatch):
    from sentinel.core import session
    expected = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=True, allow_nan=False).encode('ascii')).hexdigest()
    monkeypatch.setattr(shadow, '_canonical_json', lambda *_: pytest.fail('whole payload encoded'))
    assert shadow._sha256(value) == expected
    assert session._hash(value) == expected


@pytest.mark.parametrize('value', [float('nan'), {'v': float('inf')}, {'v': object()}])
def test_incremental_digest_refuses_noncanonical_values(value):
    from sentinel.core import session
    with pytest.raises(shadow.ShadowObservationRefused, match='canonical JSON'):
        shadow._sha256(value)
    with pytest.raises((ValueError, TypeError)):
        session._hash(value)


def test_compact_decoder_preserves_standard_json_and_mutable_ownership():
    encoded = ('{"first":{"sessions":["2026-09-14","2026-09-14"],'
               '"numbers":[-0.0,0.0,1,1.0,1e-30,1000000.0,1000000.0],"label":"\\u00e9"},'
               '"second":{"sessions":["2026-09-14"],"numbers":[1000000.0]}}').encode()
    expected = json.loads(encoded)
    actual = shadow._compact_json_loads(encoded)
    assert json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True)
    assert actual['first']['sessions'][0] is actual['second']['sessions'][0]
    assert actual['first']['numbers'][-1] is actual['second']['numbers'][0]
    actual['first']['sessions'][0] = 'changed'
    actual['first']['numbers'][-1] = 0
    assert actual['second'] == expected['second']
    assert shadow._compact_json_loads(encoded) == expected


def test_compact_decoder_keeps_more_than_cache_capacity_and_long_scalars():
    values = {str(i): {'text': str(i), 'values': [i + .25, i + .5]} for i in range(5000)}
    values['long'] = {'text': 'long'*100, 'values': [1e100]}
    encoded = json.dumps(values).encode()
    assert shadow._compact_json_loads(encoded) == json.loads(encoded)


@pytest.mark.parametrize('binary', [False, True])
@pytest.mark.parametrize('exact_numbers', [False, True])
def test_cursor_decoder_cache_is_released_and_connection_unchanged(conn, monkeypatch, binary, exact_numbers):
    from psycopg.pq import Format
    original = conn.adapters.get_loader(3802, Format.BINARY if binary else Format.TEXT)
    factory = shadow._compact_json_decoder
    decoders = []
    def tracked(**kwargs):
        decoder = factory(**kwargs)
        decoders.append(weakref.ref(decoder))
        return decoder
    monkeypatch.setattr(shadow, '_compact_json_decoder', tracked)
    for _ in range(3):
        with conn.cursor(binary=binary) as cur:
            shadow.PostgresShadowObservationStore._compact_decoder(cur, exact_numbers=exact_numbers)
            cur.execute("SELECT '{\"values\":[1000000.25,1000000.25]}'::jsonb")
            value = cur.fetchone()[0]
            assert value == {'values': [1000000.25, 1000000.25]}
            assert value['values'][0] is value['values'][1]
        del cur
        gc.collect()
        assert all(ref() is None for ref in decoders)
        assert conn.adapters.get_loader(3802, Format.BINARY if binary else Format.TEXT) is original


def test_read_only_verifier_releases_seed_and_cannot_be_reused(conn, ready, monkeypatch):
    expected = start(conn)
    _checkpoint, observer, _result = checkpoints.load(conn, initial._context(OBS, 100_000))
    seed = weakref.ref(observer.initial_state)
    records = observer.store.records
    def checked():
        assert seed() is None, 'large seed remains live while loading next session'
        return records()
    monkeypatch.setattr(observer.store, 'records', checked)
    result = observer.verify_history(consume_seed=True)
    assert result.state.state_hash == expected.state.state_hash
    with pytest.raises(shadow.ShadowObservationRefused, match='consumed'):
        observer.verify_history()


@pytest.mark.parametrize('series', [None, [], {}, {'last': {'sessions': ['2026-09-14'], 'values': [1.25]}}])
def test_streamed_row_is_complete_direct_jsonb_value(conn, series):
    from sentinel import schema
    schema.ensure_schema(conn)
    value = {'first_session': '2026-09-14', 'extra': ['preserved'],
             'initial_state': {'feed': {'series': series}, 'other': {'untouched': True}}}
    storage = shadow.PostgresShadowObservationStore(conn, observation_id='stream-check', stream_state=True)
    conn.execute('INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES(%s,%s,%s::jsonb)',
                 (storage._genesis_name, value['first_session'], canonical_json(value)))
    assert storage.genesis() == value


def test_streamed_record_spans_multiple_batches(conn):
    from sentinel import schema
    schema.ensure_schema(conn)
    series = {f'key{i:03d}': {'sessions': ['2026-09-14'], 'values': [i + .25]} for i in range(70)}
    value = {'first_session': '2026-09-14', 'initial_state': {'feed': {'series': series}}}
    storage = shadow.PostgresShadowObservationStore(conn, observation_id='stream-many', stream_state=True)
    conn.execute('INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES(%s,%s,%s::jsonb)',
                 (storage._genesis_name, value['first_session'], canonical_json(value)))
    result = storage.genesis()
    assert result == value
    assert len(result['initial_state']['feed']['series']) == 70


def test_streamed_status_refuses_excess_suffix_before_payloads(conn, monkeypatch):
    from sentinel import schema
    schema.ensure_schema(conn)
    storage = shadow.PostgresShadowObservationStore(conn, observation_id='stream-excess', stream_state=True)
    for day in ('2026-09-14', '2026-09-15'):
        conn.execute('INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES(%s,%s,%s::jsonb)',
                     (storage._name(day), day, canonical_json({'session': day})))
    monkeypatch.setattr(storage, '_streamed_row', lambda *_: pytest.fail('payload loaded before inventory refused'))
    with pytest.raises(shadow.ShadowObservationRefused, match='excess session records'):
        storage.records()


def test_status_snapshot_cannot_be_reused_across_transactions(conn, published):
    runtime.advance(conn, through='2026-09-14', observation_id=OBS, starting_cash=100_000)
    context = initial._context(OBS, 100_000)
    storage = shadow.PostgresShadowObservationStore(conn, observation_id=OBS, stream_state=True)
    kwargs = dict(store=storage, observation_id=OBS, starting_cash=100_000,
        first_session='2026-09-14', controller_config=context['controller'],
        strategy_identity=context['strategy'], runtime_identity=context['runtime'], status_only=True)
    with pytest.raises(shadow.ShadowObservationRefused, match='read-only snapshot'):
        shadow.ShadowObserver.resume(**kwargs)
    conn.rollback()
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    observer = shadow.ShadowObserver.resume(**kwargs)
    conn.rollback()
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    with pytest.raises(shadow.ShadowObservationRefused, match='snapshot changed'):
        observer.verify_history(consume_seed=True)


@pytest.mark.parametrize('which', ['genesis', 'session'])
def test_public_status_checks_last_streamed_security(conn, published, which):
    runtime.advance(conn, through='2026-09-14', observation_id=OBS, starting_cash=100_000)
    storage = shadow.PostgresShadowObservationStore(conn, observation_id=OBS)
    name = storage._genesis_name if which == 'genesis' else storage._name('2026-09-14')
    state_field = 'initial_state' if which == 'genesis' else 'state'
    row = conn.execute('SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s', (name,)).fetchone()[0]
    sid = sorted(row[state_field]['feed']['series'])[-1]
    # Neither the advertised record/state hashes nor signed checkpoint change.
    path = [state_field, 'feed', 'series', sid, 'signal_closes', '0']
    conn.execute('UPDATE sentinel_processed_sessions SET state=jsonb_set(state,%s,%s::jsonb) WHERE cursor_name=%s',
                 (path, '999.125', name))
    conn.commit()
    with pytest.raises(shadow.ShadowObservationRefused):
        runtime.status(conn, observation_id=OBS, starting_cash=100_000)
