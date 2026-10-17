import base64
from copy import deepcopy
from decimal import Decimal
import json
import time
from unittest.mock import patch

import pytest

from sentinel import observation_storage as storage, schema, shadow_observation as shadow
from sentinel.controller.machine import Controller
from sentinel.core.session import SessionState
from sentinel.strategy import production_strategy
from stock_strategy_shared.wealth_core.ledger import Ledger, EventType
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source

__all__ = ['conn', 'pg', 'source']


def record(count=600, *, session='2026-09-14'):
    controller, strategy = production_strategy()
    state = SessionState.fresh(starting_cash=50_000, controller=Controller(controller), strategy_identity=strategy)
    ledger = Ledger()
    for index in range(count):
        ledger.post(session='2026-01-02', event_type=EventType.BUY if index % 2 == 0 else EventType.SELL,
            security_id=f'S{index % 25}', ticker=f'S{index % 25}', cash_before=50_000,
            shares_delta=1 if index % 2 == 0 else -1, price=10 + index/100,
            detail={'native_sequence':index})
    state.ledger = ledger.to_dict()
    return {'observation_id':'compact-ledger', 'session':session, 'state':state.to_dict(),
            'state_sha256':state.state_hash}


def reader(conn):
    return lambda name: storage._read_ledger_chunk(conn, name)


def test_standalone_compression_preserves_logical_state_hash_and_decimal_spelling():
    expected = record()
    encoded = storage.encode(expected, 'state')
    assert storage.LEDGER_KEY in encoded
    assert not any('ref' in group for group in encoded[storage.LEDGER_KEY]['groups'])
    actual = storage.decode(encoded)
    assert actual == expected
    assert SessionState.from_dict(actual['state']).state_hash == expected['state_sha256']
    exact = storage.decode(encoded, loads=lambda raw: json.loads(raw, parse_float=Decimal))
    assert storage.exact_value_equal(exact, expected)
    assert storage.decode(expected) is expected


@pytest.mark.parametrize('damage', ['checksum', 'sequence', 'count', 'inline', 'bytes', 'dangling', 'foreign'])
def test_ledger_storage_refuses_tampering_and_missing_chunks(conn, damage):
    schema.ensure_schema(conn)
    expected = record()
    store = shadow.PostgresShadowObservationStore(conn, observation_id='compact-ledger', commit_genesis=False)
    store.append(expected)
    conn.commit()
    encoded = conn.execute('SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s',
                           (store._name(expected['session']),)).fetchone()[0]
    envelope = encoded[storage.LEDGER_KEY]
    group = envelope['groups'][0]
    if damage == 'checksum':
        envelope['sha256'] = '0'*64
    elif damage == 'sequence':
        envelope['groups'][0], envelope['groups'][1] = envelope['groups'][1], envelope['groups'][0]
    elif damage == 'count':
        envelope['count'] += 1
    elif damage == 'inline':
        encoded['state']['ledger']['events'].append({})
    elif damage == 'bytes':
        group['bytes'] = storage.MAX_LEDGER_BYTES + 1
    elif damage == 'foreign':
        group['ref'] = 'foreign:v1:' + group['sha256']
    else:
        conn.execute('DELETE FROM sentinel_processed_sessions WHERE cursor_name=%s', (group['ref'],))
    with pytest.raises(ValueError, match='storage'):
        storage.decode(encoded, ledger_reader=reader(conn))


@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('field', ['state', 'initial_state'])
def test_chunked_observation_restarts_and_reuses_exact_immutable_chunks(conn, stream, field):
    schema.ensure_schema(conn)
    expected = record()
    if field == 'initial_state':
        expected = {**expected, 'first_session':expected['session'], 'initial_state':expected['state']}
        del expected['state']
    store = shadow.PostgresShadowObservationStore(conn, observation_id='compact-ledger', commit_genesis=False)
    append = store.append if field == 'state' else store.append_genesis
    append(expected)
    conn.commit()
    before = conn.execute('SELECT cursor_name,state FROM sentinel_processed_sessions '
                          'WHERE cursor_name LIKE %s ORDER BY cursor_name', (storage.LEDGER_PREFIX+'%',)).fetchall()
    append(expected)
    conn.commit()
    assert len(before) == 2
    assert conn.execute('SELECT cursor_name,state FROM sentinel_processed_sessions '
                        'WHERE cursor_name LIKE %s ORDER BY cursor_name', (storage.LEDGER_PREFIX+'%',)).fetchall() == before
    from sentinel.feed import store as database
    with database.connect(conn.info.dsn) as fresh:
        restored = shadow.PostgresShadowObservationStore(fresh, observation_id='compact-ledger', stream_state=stream)
        actual = restored.records()[0] if field == 'state' else restored.genesis()
        assert actual == expected
        assert SessionState.from_dict(actual[field]).state_hash == expected['state_sha256']


def test_old_inline_and_new_chunked_records_share_one_readable_lineage(conn):
    schema.ensure_schema(conn)
    first, second = record(), record(700, session='2026-09-15')
    store = shadow.PostgresShadowObservationStore(conn, observation_id='compact-ledger', commit_genesis=False)
    with patch.object(storage, 'encode', side_effect=lambda candidate, state_field, **kwargs: candidate):
        store.append(first)
    store.append(second)
    conn.commit()
    assert store.records() == [first, second]
    current = shadow.PostgresShadowObservationStore(conn, observation_id='compact-ledger',
        records_from='2026-09-15', stream_state=True)
    assert current.records() == [second]


def test_chunk_and_observation_inserts_roll_back_together(conn):
    schema.ensure_schema(conn)
    store = shadow.PostgresShadowObservationStore(conn, observation_id='compact-ledger', commit_genesis=False)
    store.append(record())
    conn.rollback()
    assert conn.execute('SELECT count(*) FROM sentinel_processed_sessions WHERE cursor_name LIKE %s',
                        (storage.LEDGER_PREFIX+'%',)).fetchone()[0] == 0
    assert not store.records()


def test_existing_chunk_conflict_cannot_be_silently_reused(conn):
    schema.ensure_schema(conn)
    expected = record()
    store = shadow.PostgresShadowObservationStore(conn, observation_id='compact-ledger', commit_genesis=False)
    store.append(expected)
    conn.commit()
    row = conn.execute('SELECT cursor_name,state FROM sentinel_processed_sessions WHERE cursor_name LIKE %s LIMIT 1',
                       (storage.LEDGER_PREFIX+'%',)).fetchone()
    changed = deepcopy(row[1])
    changed['group']['data'] = base64.b64encode(b'altered').decode()
    conn.execute('UPDATE sentinel_processed_sessions SET state=%s::jsonb WHERE cursor_name=%s',
                 (json.dumps(changed), row[0]))
    conn.commit()
    with pytest.raises(ValueError, match='existing ledger chunk differs'):
        store.append(record(session='2026-09-15'))


def test_normalized_growth_records_actual_database_and_serializer_bytes(conn):
    schema.ensure_schema(conn)
    store = shadow.PostgresShadowObservationStore(conn, observation_id='compact-ledger', commit_genesis=False)
    baseline = shadow.PostgresShadowObservationStore(conn, observation_id='compact-ledger', commit_genesis=False)
    baseline.prefix = 'baseline-ledger:'
    logical_bytes, elapsed, baseline_elapsed = 0, 0., 0.
    from sentinel.feed import calendar
    days = calendar.previous_sessions('2026-09-14', 24)
    for index, day in enumerate(days):
        value = record(count=512 + index*64, session=day)
        raw = storage._json(value)
        logical_bytes += len(raw)
        started = time.perf_counter()
        with patch.object(storage, 'encode', side_effect=lambda candidate, state_field, **kwargs: candidate):
            baseline.append(value)
        baseline_elapsed += time.perf_counter() - started
        started = time.perf_counter()
        store.append(value)
        elapsed += time.perf_counter() - started
    conn.commit()
    plain = conn.execute("SELECT sum(pg_column_size(state)) FROM sentinel_processed_sessions WHERE cursor_name LIKE 'baseline-ledger:%'").fetchone()[0]
    packed = conn.execute('SELECT sum(pg_column_size(state)) FROM sentinel_processed_sessions WHERE cursor_name LIKE %s OR cursor_name LIKE %s',
                          (store.prefix+'session:%', storage.LEDGER_PREFIX+'%')).fetchone()[0]
    chunks = conn.execute('SELECT count(*) FROM sentinel_processed_sessions WHERE cursor_name LIKE %s',
                          (storage.LEDGER_PREFIX+'%',)).fetchone()[0]
    assert chunks == (512 + 23*64)//storage.LEDGER_GROUP_SIZE
    assert packed < plain
    assert store.records()[-1] == value
    print(json.dumps({'sessions':len(days), 'final_events':512+23*64, 'chunks':chunks,
        'logical_json_bytes':logical_bytes, 'baseline_postgres_bytes':int(plain),
        'normalized_postgres_bytes':int(packed), 'append_seconds':elapsed,
        'baseline_append_seconds':baseline_elapsed}, sort_keys=True))


def test_total_ledger_decode_budget_and_reserved_envelope_are_enforced(monkeypatch):
    value = record()
    encoded = storage.encode(value, 'state')
    maximum = max(group['bytes'] for group in encoded[storage.LEDGER_KEY]['groups'])
    monkeypatch.setattr(storage, 'MAX_LEDGER_BYTES', maximum)
    with pytest.raises(ValueError, match='decoded bytes exceed bound'):
        storage.decode(encoded)
    with pytest.raises(ValueError, match='reserved ledger'):
        storage.encode({**value, storage.LEDGER_KEY:{}}, 'state')
