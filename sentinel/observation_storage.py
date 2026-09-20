"""Atomic observation inserts without parsing a whole feed as JSON text."""
from itertools import islice
from decimal import Decimal
import json
from uuid import uuid4

from psycopg import sql


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


def insert(conn, *, name, session, candidate, state_field):
    """Preserve one complete JSONB row and caller-owned transaction semantics.

    Temporary pieces are private to this connection. Only the final INSERT can
    reach the durable namespace; conflicts never overwrite existing evidence.
    """
    state = candidate.get(state_field)
    feed = state.get('feed') if isinstance(state, dict) else None
    series = feed.get('series') if isinstance(feed, dict) else None
    with conn.cursor() as cur:
        if not isinstance(series, dict) or len(series) <= 128:
            cur.execute(
                'INSERT INTO sentinel_processed_sessions (cursor_name,session,state)'
                ' VALUES (%s,%s,%s::jsonb) ON CONFLICT (cursor_name) DO NOTHING',
                (name, session, _json(candidate)))
            return
        header = {**candidate, state_field: {**state, 'feed': {**feed, 'series': {}}}}
        table = sql.Identifier('shadow_insert_' + uuid4().hex)
        cur.execute(sql.SQL('CREATE TEMP TABLE {} (depth integer, part integer, value jsonb,'
                            ' PRIMARY KEY(depth,part)) ON COMMIT DROP').format(table))
        entries = iter(series.items())
        count = 0
        while batch := dict(islice(entries, 128)):
            cur.execute(sql.SQL('INSERT INTO {} VALUES (0,%s,%s::jsonb)').format(table),
                        (count, _json(batch)))
            count += 1
        depth = 0
        while count > 1:
            cur.execute(sql.SQL(
                'INSERT INTO {} SELECT %s,a.part/2,a.value || COALESCE(b.value,\'{{}}\'::jsonb)'
                ' FROM {} a LEFT JOIN {} b ON b.depth=a.depth AND b.part=a.part+1'
                ' WHERE a.depth=%s AND a.part %% 2=0').format(table, table, table),
                (depth+1, depth))
            depth += 1
            count = (count+1)//2
        cur.execute(sql.SQL(
            'INSERT INTO sentinel_processed_sessions (cursor_name,session,state)'
            ' SELECT %s,%s,jsonb_set(%s::jsonb,%s,value) FROM {} WHERE depth=%s AND part=0'
            ' ON CONFLICT (cursor_name) DO NOTHING').format(table),
            (name, session, _json(header), [state_field, 'feed', 'series'], depth))
        cur.execute(sql.SQL('DROP TABLE {}').format(table))
