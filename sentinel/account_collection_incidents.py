"""Bounded account collector history. No financial or verifier ownership."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, model_validator

from sentinel.automation import outbox
from sentinel.account_lock_observation import LockSample
from sentinel.panel import attempt_store, review_store

TABLE = 'sentinel_operational_verification_receipts'
SCOPE = 'COLLECTOR:ACCOUNT'
PURPOSE = 'sentinel.account-collection-incidents/1'
LIMIT = 16
_LOCK = (1935959139, 1633903476)


class Episode(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    occurrence: UUID
    stage: Literal['COLLECT_JOB','COLLECT_ACCOUNT','PERSIST_ACCOUNT']
    reason: str = Field(pattern='^[A-Za-z][A-Za-z0-9_]{0,127}$')
    sqlstate: str | None = Field(pattern='^[0-9A-Z]{5}$')
    dependency: Literal['UNATTRIBUTED','PAPER_REVISION','ACCOUNT_EVIDENCE']
    first_seen: datetime
    last_seen: datetime
    occurrences: int = Field(ge=1, strict=True)
    lock_timeouts: int = Field(ge=0, strict=True)
    blocker: LockSample | None = None
    recovered_at: datetime | None

    @model_validator(mode='after')
    def clocks(self):
        clocks = [self.first_seen,self.last_seen]
        if self.recovered_at is not None:
            clocks.append(self.recovered_at)
        if any(t.utcoffset() != timedelta(0) for t in clocks) or clocks != sorted(clocks):
            raise ValueError('account collection occurrence times are invalid')
        return self


def _load(conn, context, *, verify_missing, lock=True):
    if lock:
        conn.execute('SELECT pg_advisory_xact_lock(%s,%s)', _LOCK)
    row = conn.execute(f'SELECT subject_sha256,envelope,signature,observed_at,valid_until FROM {TABLE}'
                       ' WHERE scope=%s'+(' FOR UPDATE' if lock else ''), (SCOPE+':'+context,)).fetchone()
    if row is None:
        if verify_missing and conn.execute("SELECT 1 FROM sentinel_alert_outbox WHERE event_type='ACCOUNT_STATUS_COLLECTION_FAILED'"
                        " AND payload->>'context_sha256'=%s LIMIT 1", (context,)).fetchone():
            raise ValueError('account collection history is missing')
        return []
    digest, body, signature, observed, until = row
    review_store.authenticate(body, signature, purpose=PURPOSE)
    if (set(body) != {'schema','scope','episodes','observed_at'} or body['schema'] != PURPOSE or body['scope'] != SCOPE+':'+context
            or hashlib.sha256(review_store.canonical(body)).hexdigest() != digest
            or datetime.fromisoformat(body['observed_at']) != observed or until != observed+timedelta(minutes=10)
            or not isinstance(body['episodes'], list) or not 0 < len(body['episodes']) <= LIMIT):
        raise ValueError('account collection history is malformed')
    episodes = [Episode.model_validate(e) for e in body['episodes']]
    if (len({e.occurrence for e in episodes}) != len(episodes)
            or any((e.recovered_at or e.last_seen) > observed for e in episodes)):
        raise ValueError('account collection occurrence identity is duplicated')
    return episodes


def read_history(conn):
    """Authenticate dated collector diagnostics in a read-only or physically restored database."""
    return _load(conn, attempt_store.context(conn), verify_missing=True, lock=False)


def _save(conn, context, episodes, now):
    body = dict(schema=PURPOSE, scope=SCOPE+':'+context, observed_at=now.isoformat(),
                episodes=[e.model_dump(mode='json') for e in episodes])
    digest = hashlib.sha256(review_store.canonical(body)).hexdigest()
    conn.execute(f'INSERT INTO {TABLE}(scope,subject_sha256,observed_at,valid_until,envelope,signature)'
        ' VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(scope) DO UPDATE SET subject_sha256=EXCLUDED.subject_sha256,'
        'observed_at=EXCLUDED.observed_at,valid_until=EXCLUDED.valid_until,envelope=EXCLUDED.envelope,'
        'signature=EXCLUDED.signature', (body['scope'],digest,now,now+timedelta(minutes=10),Jsonb(body),
                                        review_store.signature(body,purpose=PURPOSE)))


def record_failure(conn, *, stage, reason, sqlstate=None, dependency='UNATTRIBUTED', lock_timeouts=0, blocker=None):
    context = attempt_store.context(conn)
    episodes = _load(conn, context, verify_missing=True)
    now = conn.execute('SELECT clock_timestamp()').fetchone()[0]
    previous = next((e for e in episodes if e.recovered_at is None
        and (e.stage,e.reason,e.sqlstate,e.dependency) == (stage,reason,sqlstate,dependency)), None)
    if previous is not None:
        episodes.remove(previous)
        current = Episode(**{**previous.model_dump(), 'last_seen': now, 'occurrences': previous.occurrences+1,
                             'lock_timeouts': previous.lock_timeouts+lock_timeouts,
                             'blocker': blocker or previous.blocker})
    else:
        current = Episode(occurrence=uuid4(),stage=stage,reason=reason,sqlstate=sqlstate,dependency=dependency,
                          first_seen=now,last_seen=now,occurrences=1,lock_timeouts=lock_timeouts,
                          blocker=blocker,recovered_at=None)
    _save(conn, context, (episodes+[current])[-LIMIT:], now)
    outbox.enqueue(conn, idempotency_key='account-status-collection:v2:'+str(current.occurrence),
        event_type='ACCOUNT_STATUS_COLLECTION_FAILED', severity='WARN',
        payload=dict(occurrence=str(current.occurrence),reason=reason,stage=stage,sqlstate=sqlstate,
                     dependency=dependency,context_sha256=context))


def recover(conn, *, observed_at):
    """Only after the actual periodic observation commits, with its original clock."""
    conn.execute("SET LOCAL lock_timeout = '250ms'")
    if conn.execute('SELECT to_regclass(%s)', ('public.'+TABLE,)).fetchone()[0] is None:
        return
    if not conn.execute(f"SELECT 1 FROM {TABLE} WHERE scope LIKE %s AND envelope @? "
                        "'$.episodes[*] ? (@.recovered_at == null)' LIMIT 1", (SCOPE+':%',)).fetchone():
        return
    context = attempt_store.context(conn)
    episodes = _load(conn, context, verify_missing=False)
    if not any(e.recovered_at is None and e.last_seen <= observed_at for e in episodes):
        return
    closed = [Episode(**{**e.model_dump(), 'recovered_at': observed_at})
              if e.recovered_at is None and e.last_seen <= observed_at else e for e in episodes]
    _save(conn, context, closed, conn.execute('SELECT clock_timestamp()').fetchone()[0])
