"""Bounded signed operational snapshots; never financial execution authority.

Connection-owning callers supply their existing read/publication transaction.
These helpers never commit, roll back, migrate, collect sources or start work.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timedelta
import hashlib
import hmac
import json
import os
import re

from pydantic import TypeAdapter
from psycopg.types.json import Jsonb

from sentinel.panel import model, operational_schema as schema, read_projection
from sentinel.panel import review_store

SCHEMA = 'sentinel.operational-dashboard/1'
SCOPE = 'DASHBOARD'
PURPOSE = 'sentinel.operational-dashboard-snapshot/1'
MAX_BYTES = 256 * 1024
MAX_SECONDS = 30
_PANEL = TypeAdapter(model.Panel)
_FIELDS = frozenset({'schema', 'scope', 'context_sha256', 'subjects',
                     'generated_at', 'valid_until', 'panel'})
_DIGEST = re.compile('[a-f0-9]{64}')


class SnapshotUnavailable(ValueError):
    """A controlled refusal code without source/driver/configuration contents."""


@dataclass(frozen=True)
class Snapshot:
    panel: model.Panel
    subjects: dict[str, str]
    context_sha256: str
    generated_at: datetime
    valid_until: datetime


def _require(value, code):
    if not value:
        raise SnapshotUnavailable(code)


def _utc(value):
    return isinstance(value, datetime) and value.utcoffset() == timedelta(0)


def _digest(value):
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


def _subjects(value):
    return (isinstance(value, dict) and set(value) == {'SHADOW', 'PAPER'}
            and all(_digest(item) for item in value.values()))


def _canonical(value):
    try:
        encoded = review_store.canonical(value)
    except (ValueError, TypeError, OverflowError):
        raise SnapshotUnavailable('SNAPSHOT_ENCODING_INVALID') from None
    _require(len(encoded) <= MAX_BYTES, 'SNAPSHOT_SIZE_EXCEEDED')
    return encoded


def context(conn, database_url):
    """Bind physical incarnation, exact runtime/configuration and bound account."""
    physical = conn.execute('SELECT system_identifier::text,current_database(),'
                            'pg_postmaster_start_time() FROM pg_control_system()').fetchone()
    _require(physical is not None, 'SNAPSHOT_PHYSICAL_SCOPE_MISSING')
    environment = {key: os.environ.get(key, '') for key in sorted(read_projection.SUBJECT_ENV)}
    for key in ('ALPACA_BASE_URL', 'SENTINEL_PUBLIC_ORIGIN',
                'SENTINEL_WEB_PUSH_VAPID_PUBLIC_KEY'):
        environment[key] = os.environ.get(key, '')
    environment['SENTINEL_STATE_DIR'] = os.environ.get('SENTINEL_STATE_DIR', '/var/lib/sentinel')
    material = {'database': database_url, 'physical': [str(item) for item in physical],
                'account': review_store.scope(conn), 'environment': environment,
                'producer': conn.execute(f'SELECT owner_id::text FROM {schema.OWNER} '
                                         'WHERE id=1').fetchone()}
    return hashlib.sha256(review_store.canonical(material)).hexdigest()


def subjects(conn, database_url):
    """Bind native subjects and exact financial receipt versions independently.

    A newly negative receipt can replace a positive one for an unchanged native
    subject. Receipt signature and physical row version must invalidate that old
    display too; these tokens are invalidation hints, never financial authority.
    """
    schema.require_schema(conn)
    facts = read_projection._subject_facts(conn)
    result = {}
    for scope in ('SHADOW', 'PAPER'):
        native = read_projection._subject(conn, database_url, scope, facts=facts)
        receipt = conn.execute(f'SELECT signature,xmin::text,ctid::text FROM {schema.RECEIPTS} '
                               'WHERE scope=%s', (scope,)).fetchone()
        result[scope] = hashlib.sha256(review_store.canonical([native, receipt])).hexdigest()
    return result


def original_boundary(panel):
    """Bound collection without renewing any underlying evidence deadline.

    An already expired row remains an observed negative fact. A future boundary
    can change its effective verdict and must end this snapshot first.
    """
    from sentinel.panel.presentation import _row_boundary, dashboard_health
    bounds = [panel.now + timedelta(seconds=MAX_SECONDS)]
    for row in panel.rows:
        boundary = _row_boundary(row)
        if boundary is not None and boundary > panel.now:
            bounds.append(boundary)
        if row.paper_plan is not None and row.paper_plan.execute_at > panel.now:
            bounds.append(row.paper_plan.execute_at)
    health_boundary = dashboard_health(panel).get('valid_until')
    if health_boundary is not None:
        boundary = datetime.fromisoformat(health_boundary)
        if boundary > panel.now:
            bounds.append(boundary)
    return min(bounds)


def _validate_panel(raw):
    _require(isinstance(raw, dict) and set(raw) == {item.name for item in fields(model.Panel)},
             'SNAPSHOT_PANEL_SHAPE_INVALID')
    rows = raw.get('rows')
    _require(isinstance(rows, list) and len(rows) <= 128, 'SNAPSHOT_ROWS_INVALID')
    _require(type(raw.get('local_paper_mode')) is bool, 'SNAPSHOT_PANEL_FLAGS_INVALID')
    _require(raw.get('observation_current') is True
             and raw.get('observation_changed_scopes') == []
             and raw.get('observation_revalidated_keys') == []
             and raw.get('observation_valid_until') is None,
             'SNAPSHOT_CONSUMER_STATE_REFUSED')
    expected = {item.name for item in fields(model.Row)}
    _require(all(isinstance(row, dict) and set(row) == expected for row in rows),
             'SNAPSHOT_ROW_SHAPE_INVALID')
    _require(len({row.get('key') for row in rows if isinstance(row.get('key'), str)}) == len(rows),
             'SNAPSHOT_ROW_KEYS_INVALID')
    for row in rows:
        _require(all(isinstance(row.get(key), str) for key in ('key', 'label', 'value', 'detail'))
                 and 0 < len(row['key']) <= 100 and isinstance(row.get('status'), str)
                 and row['status'] in {
                     model.OK, model.WARN, model.FAIL, model.UNKNOWN, model.PENDING}
                 and type(row.get('required_current')) is bool, 'SNAPSHOT_ROW_INVALID')
        recovery = row.get('recovery')
        if recovery is not None:
            _require(isinstance(recovery, dict)
                     and set(recovery) == {item.name for item in fields(model.RecoveryEvidence)}
                     and type(recovery.get('automatic')) is bool
                     and type(recovery.get('operator_required')) is bool
                     and all(recovery.get(key) is None or type(recovery[key]) is int
                             for key in ('attempt', 'maximum_attempts')),
                     'SNAPSHOT_RECOVERY_INVALID')
    try:
        panel = _PANEL.validate_json(json.dumps(raw, allow_nan=False))
    except (ValueError, TypeError, OverflowError):
        raise SnapshotUnavailable('SNAPSHOT_PANEL_INVALID') from None
    _require(_utc(panel.now), 'SNAPSHOT_PANEL_CLOCK_INVALID')
    for row in panel.rows:
        _require(all(value is None or _utc(value) for value in (row.as_of, row.valid_until)),
                 'SNAPSHOT_ROW_CLOCK_INVALID')
        _require(row.freshness is None or row.freshness >= timedelta(0),
                 'SNAPSHOT_ROW_FRESHNESS_INVALID')
        if row.recovery is not None:
            _require(all(value is None or _utc(value) for value in (
                row.recovery.next_attempt_at, row.recovery.deadline)), 'SNAPSHOT_RECOVERY_CLOCK_INVALID')
        # Reuse the financial wire guard for its special alignment invariants.
        if row.paper_alignment is not None:
            from sentinel.panel.observer_codec import row_from_observation
            from dataclasses import asdict
            try:
                row_from_observation(asdict(row))
            except (ValueError, TypeError, OverflowError):
                raise SnapshotUnavailable('SNAPSHOT_ALIGNMENT_INVALID') from None
    return panel


def encode(panel, *, context_sha256, subjects, valid_until=None):
    _require(_digest(context_sha256) and _subjects(subjects), 'SNAPSHOT_SCOPE_INVALID')
    _require(_utc(panel.now), 'SNAPSHOT_PANEL_CLOCK_INVALID')
    try:
        raw = _PANEL.dump_python(panel, mode='json', warnings='error')
    except (ValueError, TypeError, OverflowError):
        raise SnapshotUnavailable('SNAPSHOT_PANEL_INVALID') from None
    panel = _validate_panel(raw)
    boundary = original_boundary(panel)
    expiry = valid_until if valid_until is not None else boundary
    _require(_utc(expiry) and panel.now < expiry <= boundary, 'SNAPSHOT_EXPIRY_INVALID')
    value = dict(schema=SCHEMA, scope=SCOPE, context_sha256=context_sha256,
                 subjects=dict(subjects), generated_at=panel.now.isoformat(),
                 valid_until=expiry.isoformat(), panel=raw)
    _canonical(value)
    return value, review_store.signature(value, purpose=PURPOSE)


def decode(value, signature, *, context_sha256, now):
    _canonical(value)
    _require(isinstance(value, dict) and set(value) == _FIELDS
             and value['schema'] == SCHEMA and value['scope'] == SCOPE
             and _digest(context_sha256) and value['context_sha256'] == context_sha256
             and _subjects(value['subjects']), 'SNAPSHOT_SCOPE_INVALID')
    _require(_digest(signature) and hmac.compare_digest(signature,
        review_store.signature(value, purpose=PURPOSE)), 'SNAPSHOT_AUTHENTICATION_FAILED')
    try:
        generated = datetime.fromisoformat(value['generated_at'])
        expiry = datetime.fromisoformat(value['valid_until'])
    except (ValueError, TypeError):
        raise SnapshotUnavailable('SNAPSHOT_CLOCK_INVALID') from None
    _require(all(_utc(item) for item in (now, generated, expiry))
             and generated <= now < expiry
             and timedelta(0) < expiry-generated <= timedelta(seconds=MAX_SECONDS),
             'SNAPSHOT_EXPIRED_OR_CLOCK_INVALID')
    panel = _validate_panel(value['panel'])
    _require(panel.now == generated and expiry <= original_boundary(panel),
             'SNAPSHOT_ORIGINAL_BOUNDARY_CHANGED')
    return Snapshot(panel, dict(value['subjects']), context_sha256, generated, expiry)


def read_owned(conn, *, context_sha256, now, lock=False):
    """Read only, without changing the caller's transaction or any evidence."""
    row = conn.execute(f'SELECT subject_sha256,observed_at,valid_until,envelope,signature '
        f'FROM {schema.RECEIPTS} WHERE scope=%s'+(' FOR SHARE' if lock else ''), (SCOPE,)).fetchone()
    _require(row is not None, 'SNAPSHOT_MISSING')
    value, signed = row[3], row[4]
    _require(isinstance(value, dict) and row[0] == context_sha256
             and _utc(row[1]) and _utc(row[2])
             and row[1].isoformat() == value.get('generated_at')
             and row[2].isoformat() == value.get('valid_until'), 'SNAPSHOT_METADATA_CHANGED')
    return decode(value, signed, context_sha256=context_sha256, now=now)


def publish_owned(conn, *, owner_id, value, signature, context_sha256, subjects, now):
    """Fence and publish in the caller's transaction, never commit either half."""
    current = decode(value, signature, context_sha256=context_sha256, now=now)
    _require(_subjects(subjects) and current.subjects == subjects, 'SNAPSHOT_SUBJECT_CHANGED')
    owner = conn.execute(f'SELECT owner_id FROM {schema.OWNER} WHERE id=1 AND owner_id=%s '
        'AND expires_at>clock_timestamp() FOR UPDATE', (owner_id,)).fetchone()
    _require(owner is not None, 'SNAPSHOT_OWNER_LOST')
    conn.execute(f'INSERT INTO {schema.RECEIPTS} '
        '(scope,subject_sha256,observed_at,valid_until,envelope,signature) VALUES (%s,%s,%s,%s,%s,%s) '
        'ON CONFLICT (scope) DO UPDATE SET subject_sha256=EXCLUDED.subject_sha256,'
        'observed_at=EXCLUDED.observed_at,valid_until=EXCLUDED.valid_until,'
        'envelope=EXCLUDED.envelope,signature=EXCLUDED.signature',
        (SCOPE, context_sha256, current.generated_at, current.valid_until, Jsonb(value), signature))
