"""Atomic observation inserts without parsing a whole feed as JSON text."""
from itertools import islice
from decimal import Decimal
import json
import base64
import hashlib
import zlib


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def exact_value_equal(actual, expected):
    """JSONB equality for a canonical string-keyed observation, without rounding.

    Actual JSON decimals must be decoded as Decimal. Expected strategy floats
    name their canonical JSON decimal spelling, not their binary approximation.
    """
    if isinstance(actual, dict) and isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            exact_value_equal(value, expected[key]) for key, value in actual.items())
    if isinstance(actual, list) and isinstance(expected, (list, tuple)):
        return len(actual) == len(expected) and all(
            exact_value_equal(a, e) for a, e in zip(actual, expected))
    if type(actual) in (int, Decimal) and type(expected) in (int, float):
        return actual == Decimal(str(expected))
    return type(actual) is type(expected) and actual == expected


STORAGE_KEY = '_sentinel_series_storage'
STORAGE_SCHEMA = 'sentinel.observation-series/zlib-json/1'
GROUP_SIZE = 128
MAX_GROUP_BYTES = 16 * 1024 * 1024
LEDGER_KEY = '_sentinel_ledger_storage'
LEDGER_SCHEMA = 'sentinel.observation-ledger/zlib-json/1'
LEDGER_CHUNK_SCHEMA = 'sentinel.observation-ledger-chunk/1'
LEDGER_PREFIX = 'observation-ledger:v1:'
LEDGER_GROUP_SIZE = 256
MAX_LEDGER_GROUPS = 4096
MAX_LEDGER_BYTES = 256 * 1024 * 1024


def _require(condition, reason):
    if not condition:
        raise ValueError('observation series storage: ' + reason)


def _encode_series(candidate, state_field):
    """Change physical representation only; retain the complete logical value."""
    _require(STORAGE_KEY not in candidate, 'reserved storage envelope in logical input')
    state = candidate.get(state_field)
    feed = state.get('feed') if isinstance(state, dict) else None
    series = feed.get('series') if isinstance(feed, dict) else None
    if not isinstance(series, dict) or len(series) <= GROUP_SIZE:
        return candidate
    groups = []
    entries = iter(sorted(series.items()))
    while batch := dict(islice(entries, GROUP_SIZE)):
        raw = _json(batch).encode('ascii')
        _require(len(raw) <= MAX_GROUP_BYTES, 'group exceeds uncompressed byte bound')
        groups.append({'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
                       'count': len(batch),
                       'data': base64.b64encode(zlib.compress(raw)).decode('ascii')})
    return {**candidate, state_field: {**state, 'feed': {**feed, 'series': {}}},
            STORAGE_KEY: {'schema': STORAGE_SCHEMA, 'field': state_field,
                          'count': len(series), 'groups': groups}}


def _decode_series(value, *, loads=json.loads):
    """Verify bounded chunks before exposing their logical feed series."""
    if STORAGE_KEY not in value:
        return value
    envelope = value[STORAGE_KEY]
    _require(isinstance(envelope, dict) and set(envelope) == {'schema', 'field', 'count', 'groups'},
             'unknown envelope shape')
    _require(envelope['schema'] == STORAGE_SCHEMA, 'unknown schema')
    field = envelope['field']
    _require(field in ('state', 'initial_state'), 'unknown state field')
    state = value.get(field)
    feed = state.get('feed') if isinstance(state, dict) else None
    _require(isinstance(feed, dict) and feed.get('series') == {}, 'inline series must be empty')
    count, groups = envelope['count'], envelope['groups']
    _require(type(count) is int and count > GROUP_SIZE and isinstance(groups, list)
             and len(groups) == (count + GROUP_SIZE - 1) // GROUP_SIZE, 'group inventory mismatch')
    series = {}
    for index, group in enumerate(groups):
        _require(isinstance(group, dict) and set(group) == {'bytes', 'sha256', 'count', 'data'},
                 'unknown group shape')
        length = group['bytes']
        _require(type(length) is int and 0 < length <= MAX_GROUP_BYTES, 'invalid byte bound')
        expected_count = min(GROUP_SIZE, count - index * GROUP_SIZE)
        _require(type(group['count']) is int and group['count'] == expected_count, 'group count mismatch')
        _require(isinstance(group['data'], str) and len(group['data']) <= 2 * MAX_GROUP_BYTES,
                 'invalid compressed bound')
        packed = base64.b64decode(group['data'], validate=True)
        inflater = zlib.decompressobj()
        try:
            raw = inflater.decompress(packed, length + 1)
        except zlib.error as exc:
            raise ValueError('observation series storage: invalid compressed stream') from exc
        _require(len(raw) == length and inflater.eof and not inflater.unused_data
                 and not inflater.unconsumed_tail, 'compressed length or stream mismatch')
        _require(hashlib.sha256(raw).hexdigest() == group['sha256'], 'group checksum mismatch')
        batch = loads(raw)
        _require(isinstance(batch, dict) and len(batch) == expected_count, 'decoded count mismatch')
        _require(not series.keys() & batch.keys(), 'duplicate series')
        series.update(batch)
    _require(len(series) == count, 'series inventory mismatch')
    return {k: v for k, v in value.items() if k != STORAGE_KEY} | {
        field: {**state, 'feed': {**feed, 'series': series}}}


def _pack_events(events, *, raw=None):
    raw = _json(events).encode('ascii') if raw is None else raw
    _require(len(raw) <= MAX_GROUP_BYTES, 'ledger group exceeds byte bound')
    return {'count': len(events), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'data': base64.b64encode(zlib.compress(raw)).decode('ascii')}


def encode(candidate, state_field, *, ledger_writer=None):
    _require(LEDGER_KEY not in candidate, 'reserved ledger storage envelope in logical input')
    value = _encode_series(candidate, state_field)
    state = value.get(state_field)
    ledger = state.get('ledger') if isinstance(state, dict) else None
    events = ledger.get('events') if isinstance(ledger, dict) else None
    if not isinstance(events, list) or not events:
        return value
    _require(len(events) <= LEDGER_GROUP_SIZE * MAX_LEDGER_GROUPS, 'ledger event count exceeds bound')
    groups, total = [], 0
    sequence = hashlib.sha256(b'[')
    for start in range(0, len(events), LEDGER_GROUP_SIZE):
        batch = events[start:start + LEDGER_GROUP_SIZE]
        raw = _json(batch).encode('ascii')
        group = _pack_events(batch, raw=raw)
        total += group['bytes']
        _require(total <= MAX_LEDGER_BYTES, 'ledger decoded bytes exceed bound')
        if groups:
            sequence.update(b',')
        sequence.update(raw[1:-1])
        if ledger_writer is not None and len(batch) == LEDGER_GROUP_SIZE:
            ledger_writer(group, batch[-1]['session'])
            group = {key: item for key, item in group.items() if key != 'data'} | {
                'ref': LEDGER_PREFIX + group['sha256']}
        groups.append(group)
    sequence.update(b']')
    return {**value, state_field: {**state, 'ledger': {**ledger, 'events': []}},
            LEDGER_KEY: {'schema': LEDGER_SCHEMA, 'field': state_field, 'count': len(events),
                         'sha256': sequence.hexdigest(), 'groups': groups}}


def _unpack_events(group, *, loads):
    _require(isinstance(group, dict) and set(group) == {'count', 'bytes', 'sha256', 'data'},
             'unknown ledger group shape')
    length = group['bytes']
    _require(type(length) is int and 0 < length <= MAX_GROUP_BYTES, 'invalid ledger byte bound')
    _require(type(group['count']) is int and 0 < group['count'] <= LEDGER_GROUP_SIZE,
             'invalid ledger group count')
    _require(isinstance(group['data'], str) and len(group['data']) <= 2 * MAX_GROUP_BYTES,
             'invalid compressed ledger bound')
    try:
        packed = base64.b64decode(group['data'], validate=True)
        inflater = zlib.decompressobj()
        raw = inflater.decompress(packed, length + 1)
    except (ValueError, zlib.error) as exc:
        raise ValueError('observation series storage: invalid compressed ledger stream') from exc
    _require(len(raw) == length and inflater.eof and not inflater.unused_data
             and not inflater.unconsumed_tail, 'compressed ledger length or stream mismatch')
    _require(hashlib.sha256(raw).hexdigest() == group['sha256'], 'ledger group checksum mismatch')
    events = loads(raw)
    _require(isinstance(events, list) and len(events) == group['count'], 'ledger decoded count mismatch')
    return events, raw


def decode(value, *, loads=json.loads, ledger_reader=None):
    value = _decode_series(value, loads=loads)
    if LEDGER_KEY not in value:
        return value
    envelope = value[LEDGER_KEY]
    _require(isinstance(envelope, dict) and set(envelope) == {'schema', 'field', 'count', 'sha256', 'groups'}
             and envelope['schema'] == LEDGER_SCHEMA, 'unknown ledger envelope shape')
    field, count, groups = envelope['field'], envelope['count'], envelope['groups']
    _require(field in ('state', 'initial_state'), 'unknown ledger state field')
    state = value.get(field)
    ledger = state.get('ledger') if isinstance(state, dict) else None
    _require(isinstance(ledger, dict) and ledger.get('events') == [], 'inline ledger events must be empty')
    _require(type(count) is int and 0 < count <= LEDGER_GROUP_SIZE * MAX_LEDGER_GROUPS
             and isinstance(groups, list) and len(groups) == (count + LEDGER_GROUP_SIZE - 1) // LEDGER_GROUP_SIZE,
             'ledger group inventory mismatch')
    events, total = [], 0
    sequence = hashlib.sha256(b'[')
    for index, encoded in enumerate(groups):
        group = encoded
        if isinstance(encoded, dict) and 'ref' in encoded:
            _require(set(encoded) == {'count', 'bytes', 'sha256', 'ref'}
                     and isinstance(encoded['sha256'], str) and len(encoded['sha256']) == 64
                     and all(c in '0123456789abcdef' for c in encoded['sha256'])
                     and encoded['ref'] == LEDGER_PREFIX + encoded['sha256']
                     and encoded['count'] == LEDGER_GROUP_SIZE and ledger_reader is not None,
                     'invalid or unavailable ledger reference')
            group = ledger_reader(encoded['ref'])
            _require(isinstance(group, dict) and all(group.get(key) == encoded[key]
                     for key in ('count', 'bytes', 'sha256')), 'ledger reference binding changed')
        _require(isinstance(group, dict) and type(group.get('bytes')) is int,
                 'invalid ledger group shape')
        total += group['bytes']
        _require(total <= MAX_LEDGER_BYTES, 'ledger decoded bytes exceed bound')
        batch, raw = _unpack_events(group, loads=loads)
        _require(len(batch) == min(LEDGER_GROUP_SIZE, count - index * LEDGER_GROUP_SIZE),
                 'ledger group sequence count mismatch')
        events.extend(batch)
        if index:
            sequence.update(b',')
        sequence.update(raw[1:-1])
    sequence.update(b']')
    _require(sequence.hexdigest() == envelope['sha256'], 'ledger sequence checksum mismatch')
    return {key: item for key, item in value.items() if key != LEDGER_KEY} | {
        field: {**state, 'ledger': {**ledger, 'events': events}}}


def _read_ledger_chunk_payload(conn, name):
    with conn.cursor() as cur:
        cur.execute('SELECT session,state FROM sentinel_processed_sessions WHERE cursor_name=%s', (name,))
        row = cur.fetchone()
    _require(row is not None, 'ledger reference is missing')
    value = row[1]
    _require(isinstance(value, dict) and set(value) == {'schema', 'session', 'group'}
             and value['schema'] == LEDGER_CHUNK_SCHEMA and str(row[0]) == value['session'],
             'ledger chunk shape or session changed')
    return value


def _read_ledger_chunk(conn, name):
    return _read_ledger_chunk_payload(conn, name)['group']


def _write_ledger_chunk(conn, group, session):
    name = LEDGER_PREFIX + group['sha256']
    payload = {'schema': LEDGER_CHUNK_SCHEMA, 'session': session, 'group': group}
    with conn.cursor() as cur:
        cur.execute('INSERT INTO sentinel_processed_sessions (cursor_name,session,state)'
                    ' VALUES (%s,%s,%s::jsonb) ON CONFLICT (cursor_name) DO NOTHING',
                    (name, session, _json(payload)))
    _require(_read_ledger_chunk_payload(conn, name) == payload, 'existing ledger chunk differs')


def insert(conn, *, name, session, candidate, state_field):
    """One atomic append in the caller-owned transaction, no partial state."""
    encoded = encode(candidate, state_field,
                     ledger_writer=lambda group, day: _write_ledger_chunk(conn, group, day))
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO sentinel_processed_sessions (cursor_name,session,state)'
            ' VALUES (%s,%s,%s::jsonb) ON CONFLICT (cursor_name) DO NOTHING',
            (name, session, _json(encoded)))
