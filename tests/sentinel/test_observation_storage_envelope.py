"""Exact logical-value and refusal oracles for compressed observation storage."""
import base64
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import zlib

import pytest

from sentinel import observation_storage as storage, schema, shadow_observation as shadow
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401

__all__ = ['conn', 'pg', 'source']


def candidate(field='state'):
    return {'observation_id': 'packed', 'session': '2026-09-14', 'first_session': '2026-09-14',
            'unrelated': {'cash': 1985.80372, 'text': '\u00e9', 'flag': False},
            field: {'feed': {'series': {str(i): {'prices': [i, 1.0, None], 'label': 'AAA'}
                                       for i in range(257)}, 'history_sessions': 260}}}


@pytest.mark.parametrize('field', ['state', 'initial_state'])
@pytest.mark.parametrize('stream', [False, True])
def test_persisted_envelope_restarts_with_the_complete_original_value(conn, field, stream):
    schema.ensure_schema(conn)
    expected = candidate(field)
    store = shadow.PostgresShadowObservationStore(conn, observation_id='packed', commit_genesis=False)
    append = store.append if field == 'state' else store.append_genesis
    append(expected)
    conn.commit()
    from sentinel.feed import store as database
    with database.connect(conn.info.dsn) as fresh:
        restored = shadow.PostgresShadowObservationStore(fresh, observation_id='packed', stream_state=stream)
        actual = restored.records()[0] if field == 'state' else restored.genesis()
        assert actual == expected
        if field == 'initial_state':
            assert restored.matches_genesis(expected)
        # No returned mutable object can alter a subsequent read.
        actual[field]['feed']['series']['256']['prices'][-1] = 999
        again = restored.records()[0] if field == 'state' else restored.genesis()
        assert again == expected


@pytest.mark.parametrize('damage', ['checksum', 'length', 'count', 'missing-group',
    'duplicate-group', 'inline', 'schema', 'truncated', 'trailing', 'byte-bound'])
def test_storage_envelope_refuses_incomplete_or_contradictory_evidence(damage):
    value = storage.encode(candidate(), 'state')
    envelope = value[storage.STORAGE_KEY]
    group = envelope['groups'][0]
    if damage == 'checksum': group['sha256'] = '0'*64
    elif damage == 'length': group['bytes'] += 1
    elif damage == 'count': envelope['count'] += 1
    elif damage == 'missing-group': envelope['groups'].pop()
    elif damage == 'duplicate-group': envelope['groups'][1] = deepcopy(group)
    elif damage == 'inline': value['state']['feed']['series']['unexpected'] = {}
    elif damage == 'schema': envelope['schema'] = 'unknown'
    elif damage == 'byte-bound': group['bytes'] = storage.MAX_GROUP_BYTES + 1
    else:
        packed = base64.b64decode(group['data'])
        group['data'] = base64.b64encode(packed[:-2] if damage == 'truncated' else packed+b'extra').decode()
    with pytest.raises(ValueError, match='observation series storage'):
        storage.decode(value)


@pytest.mark.parametrize('field', ['state', 'initial_state'])
def test_persisted_sub_float_group_change_cannot_pass_exact_retry(conn, field):
    schema.ensure_schema(conn)
    expected = candidate(field)
    store = shadow.PostgresShadowObservationStore(conn, observation_id='packed', commit_genesis=False)
    append = store.append if field == 'state' else store.append_genesis
    name = store._name(expected['session']) if field == 'state' else store._genesis_name
    append(expected)
    conn.commit()
    value = conn.execute('SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s', (name,)).fetchone()[0]
    group = value[storage.STORAGE_KEY]['groups'][-1]
    raw = zlib.decompress(base64.b64decode(group['data']))
    assert b'1.0' in raw
    changed = raw.replace(b'1.0', b'1.00000000000000001', 1)
    group.update(bytes=len(changed), sha256=hashlib.sha256(changed).hexdigest(),
                 data=base64.b64encode(zlib.compress(changed)).decode())
    conn.execute('UPDATE sentinel_processed_sessions SET state=%s::jsonb WHERE cursor_name=%s', (json.dumps(value), name))
    conn.commit()
    # The physical checksum is internally coherent; logical equality must still
    # see the exact decimal change, even though ordinary float decoding loses it.
    if field == 'initial_state':
        assert store.matches_genesis(expected) is False
    with pytest.raises(shadow.ShadowObservationRefused, match='different evidence'):
        append(expected)


def test_reserved_envelope_cannot_enter_logical_input():
    with pytest.raises(ValueError, match='reserved'):
        storage.encode({**candidate(), storage.STORAGE_KEY: {}}, 'state')


def test_valid_larger_group_cannot_bypass_the_decompression_budget(monkeypatch):
    encoded = storage.encode(candidate(), 'state')
    group = encoded[storage.STORAGE_KEY]['groups'][0]
    assert len(group['data']) < 2048 < group['bytes']
    monkeypatch.setattr(storage, 'MAX_GROUP_BYTES', 1024)
    with pytest.raises(ValueError, match='byte bound'):
        storage.decode(encoded)


def test_exact_decode_retains_original_decimal_spelling():
    encoded = storage.encode(candidate(), 'state')
    decoded = storage.decode(encoded, loads=lambda raw: json.loads(raw, parse_float=Decimal))
    assert decoded['state']['feed']['series']['256']['prices'][1] == Decimal('1.0')
