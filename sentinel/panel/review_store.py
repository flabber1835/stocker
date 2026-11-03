"""Signed PostgreSQL operator history, independent of financial authority."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone

from psycopg.types.json import Jsonb

from sentinel.panel import review_schema as schema

SCHEMA = 'sentinel.operator-review-state/1'
EVENT_SCHEMA = 'sentinel.operator-review-event/1'
FIELDS = {'schema', 'head', 'reviewed_head', 'head_signature', 'active', 'warnings',
          'incidents', 'reviewed_at', 'observed_at', 'view_sha256', 'database_incarnation'}


class ReviewRefused(ValueError):
    pass


def require(value, reason):
    if not value:
        raise ReviewRefused(reason)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def signature(value, *, purpose):
    key = os.environ.get('SENTINEL_PUBLICATION_RECEIPT_KEY', '').encode('utf-8')
    require(len(key) >= 32, 'operator review signing key unavailable')
    return hmac.new(key, purpose.encode('ascii') + b'\0' + canonical(value), hashlib.sha256).hexdigest()


def authenticate(value, signed, *, purpose):
    require(isinstance(signed, str) and hmac.compare_digest(
        signed, signature(value, purpose=purpose)), 'operator review authentication failed')


def scope(conn):
    row = conn.execute('SELECT deployment_id,broker,broker_account_id,takeover_epoch,ownership_state '
                       'FROM sentinel_account_binding WHERE id=1').fetchone()
    require(row and row[4] == 'SENTINEL_OWNED' and all(row[:4]),
            'operator review requires a bound account')
    endpoint = os.environ.get('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets').rstrip('/')
    from sentinel.trading_environment import TradingEndpoint
    TradingEndpoint.parse(endpoint)
    identity = dict(deployment=row[0], broker=row[1], account=row[2], epoch=row[3], endpoint=endpoint)
    return hashlib.sha256(canonical(identity)).hexdigest()


def empty(now):
    return dict(schema=SCHEMA, head=0, reviewed_head=0, head_signature='', active=[],
                warnings=[], incidents=[], reviewed_at=None, observed_at=now.isoformat(),
                view_sha256='', database_incarnation='')


@contextmanager
def transaction(database_url):
    from sentinel.feed import store
    conn = store.connect(database_url, connect_timeout=3, statement_timeout_ms=3000)
    try:
        conn.execute("SET LOCAL lock_timeout='1000ms'")
        schema.require_schema(conn)
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def load_locked(conn, key, now):
    initial = empty(now)
    conn.execute(f'INSERT INTO {schema.STATE}(scope_sha256,payload,signature) VALUES (%s,%s,%s) '
                 'ON CONFLICT (scope_sha256) DO NOTHING',
                 (key, Jsonb(initial), signature(dict(scope=key, state=initial), purpose=SCHEMA)))
    payload, signed = conn.execute(f'SELECT payload,signature FROM {schema.STATE} '
                                  'WHERE scope_sha256=%s FOR UPDATE', (key,)).fetchone()
    require(isinstance(payload, dict) and set(payload) == FIELDS and payload['schema'] == SCHEMA,
            'operator review state malformed')
    authenticate(dict(scope=key, state=payload), signed, purpose=SCHEMA)
    require(type(payload['head']) is int and type(payload['reviewed_head']) is int
            and 0 <= payload['reviewed_head'] <= payload['head'], 'operator review head malformed')
    observed = datetime.fromisoformat(payload['observed_at'])
    require(observed.utcoffset() is not None and observed <= now,
            'operator review clock regressed')
    if payload['reviewed_at'] is not None:
        reviewed = datetime.fromisoformat(payload['reviewed_at'])
        require(reviewed.utcoffset() is not None and reviewed <= observed,
                'operator review acknowledgement clock malformed')
    require(isinstance(payload['view_sha256'], str) and (
        re.fullmatch('[a-f0-9]{64}', payload['view_sha256']) is not None
        or payload['head'] == 0 and payload['view_sha256'] == ''),
        'operator review subject malformed')
    for field, maximum in (('active', 64), ('warnings', 64), ('incidents', 1000)):
        require(isinstance(payload[field], list) and len(payload[field]) <= maximum
                and all(isinstance(item, str) and 0 < len(item) <= 200 for item in payload[field])
                and len(set(payload[field])) == len(payload[field]), 'operator review condition set malformed')
    tail = conn.execute(f'SELECT sequence,payload,signature FROM {schema.EVENTS} '
                        'WHERE scope_sha256=%s ORDER BY sequence DESC LIMIT 1', (key,)).fetchone()
    if payload['head']:
        require(tail is not None and tail[0] == payload['head']
                and tail[2] == payload['head_signature'], 'operator review history regressed')
        authenticate(tail[1], tail[2], purpose=EVENT_SCHEMA)
        require(tail[1]['scope'] == key and tail[1]['sequence'] == tail[0],
                'operator review history scope changed')
    else:
        require(tail is None and payload['head_signature'] == '', 'operator review history lost')
    return payload


def append(conn, key, state, *, kind, event_key, details, now):
    require(kind in {'STARTED', 'FAILED', 'RECOVERED', 'REVIEW', 'ACKNOWLEDGED'},
            'operator review event kind invalid')
    event = dict(schema=EVENT_SCHEMA, scope=key, sequence=state['head'] + 1,
                 kind=kind, at=now.isoformat(), details=details, previous=state['head_signature'])
    signed = signature(event, purpose=EVENT_SCHEMA)
    conn.execute(f'INSERT INTO {schema.EVENTS}'
                 '(scope_sha256,sequence,event_key,kind,at,payload,signature) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                 (key, event['sequence'], event_key, kind, now, Jsonb(event), signed))
    state.update(head=event['sequence'], head_signature=signed)


def has_event(conn, key, event_key):
    return conn.execute(f'SELECT 1 FROM {schema.EVENTS} WHERE scope_sha256=%s AND event_key=%s',
                        (key, event_key)).fetchone() is not None


def save(conn, key, state, now):
    state['observed_at'] = now.isoformat()
    conn.execute(f'UPDATE {schema.STATE} SET payload=%s,signature=%s,updated_at=%s '
                 'WHERE scope_sha256=%s', (Jsonb(state),
                 signature(dict(scope=key, state=state), purpose=SCHEMA), now, key))


def recent(conn, key, *, limit=20):
    rows = conn.execute(f'SELECT sequence,payload,signature FROM {schema.EVENTS} '
                        'WHERE scope_sha256=%s ORDER BY sequence DESC LIMIT %s', (key, limit)).fetchall()
    result = []
    for sequence, value, signed in rows:
        authenticate(value, signed, purpose=EVENT_SCHEMA)
        require(value['scope'] == key and value['sequence'] == sequence,
                'operator review event scope changed')
        result.append(dict(sequence=sequence, kind=value['kind'], at=value['at'], details=value['details']))
    return result


def database_now(conn):
    value = conn.execute('SELECT clock_timestamp()').fetchone()[0]
    require(isinstance(value, datetime) and value.utcoffset() is not None,
            'operator review database clock unavailable')
    return value.astimezone(timezone.utc)
