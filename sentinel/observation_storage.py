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


def _require(condition, reason):
    if not condition:
        raise ValueError('observation series storage: ' + reason)


def encode(candidate, state_field):
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


def decode(value, *, loads=json.loads):
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


def insert(conn, *, name, session, candidate, state_field):
    """One atomic append in the caller-owned transaction, no partial state."""
    encoded = encode(candidate, state_field)
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO sentinel_processed_sessions (cursor_name,session,state)'
            ' VALUES (%s,%s,%s::jsonb) ON CONFLICT (cursor_name) DO NOTHING',
            (name, session, _json(encoded)))
