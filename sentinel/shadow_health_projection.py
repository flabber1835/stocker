"""Bounded health hints; never financial or broker admission authority."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile

from pydantic import BaseModel, ConfigDict, Field

from sentinel.feed import calendar, publication, store

MAX_BYTES = 65536
SCHEMA = 'sentinel.shadow-health-projection/1'


class Projection(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    schema_id: str = Field(pattern=r'^sentinel\.shadow-health-projection/1$')
    config_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    inventory_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    session: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    record_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    runtime_authority_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


def path():
    return Path(os.environ.get('SENTINEL_STATE_DIR', '/var/lib/sentinel')) / 'shadow-health-projection.json'


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def _config(config):
    from sentinel.shadow_budget import DEADLINE_ENV
    # Hash private configuration; never persist credentials or their values.
    env = {key: value for key, value in os.environ.items()
           if key.startswith('SENTINEL_') and key != DEADLINE_ENV}
    return _digest({'config': asdict(config), 'environment': env})


def _inventory(conn):
    relation = conn.execute(
        "SELECT system_identifier::text,current_database(),"
        "'sentinel_processed_sessions'::regclass::oid::text,"
        "pg_relation_filenode('sentinel_processed_sessions')::text,"
        "'sentinel_corpus_publications'::regclass::oid::text,"
        "pg_relation_filenode('sentinel_corpus_publications')::text,"
        "floor(pg_snapshot_xmax(pg_current_snapshot())::text::numeric / 4294967296)::bigint "
        "FROM pg_control_system()"
    ).fetchone()
    rows = conn.execute(
        "SELECT cursor_name,session,tableoid::text,xmin::text,ctid::text "
        "FROM sentinel_processed_sessions ORDER BY cursor_name LIMIT 10001"
    ).fetchall()
    pubs = conn.execute(
        "SELECT version,tableoid::text,xmin::text,ctid::text "
        "FROM sentinel_corpus_publications ORDER BY version LIMIT 10001"
    ).fetchall()
    if len(rows) > 10000 or len(pubs) > 10000:
        raise ValueError('shadow health inventory exceeds bound')
    return _digest([relation, rows, pubs]), any(row[0] == 'rolling-cold-start:v1' for row in rows)


def _signature(payload):
    return publication._receipt_hmac({'purpose': SCHEMA, 'health_projection': payload})


def _write(value, target):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    if len(raw) > MAX_BYTES:
        raise ValueError('shadow health projection exceeds bound')
    target.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.shadow-health-', delete=False) as stream:
            name = stream.name
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, target)
        name = None
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if name is not None:
            Path(name).unlink(missing_ok=True)


def publish(config, result, conn):
    """Called under the canonical writer lock after full verification/retention."""
    if not config.operational_source_only:
        return
    if result.get('shadow_verdict') != 'SHADOW_GO' or result.get('verification') != 'VERIFIED':
        raise ValueError('unverified shadow cannot publish a health projection')
    from sentinel import rolling_authority
    from sentinel.execution.journal import WRITER_LOCK_KEY
    held = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype='advisory' "
        "AND pid=pg_backend_pid() AND database=(SELECT oid FROM pg_database WHERE datname=current_database()) "
        "AND classid=%s AND objid=%s AND objsubid=1 AND mode='ExclusiveLock' AND granted)",
        (WRITER_LOCK_KEY >> 32, WRITER_LOCK_KEY & 0xffffffff)).fetchone()[0]
    if not held:
        raise ValueError('health projection requires the canonical writer lock')
    values = rolling_authority.latest(conn, config.observation_id)
    if not values or isinstance(values[0], rolling_authority.ReconstructionReceipt):
        raise ValueError('prospective authority is absent')
    value = values[0]
    from sentinel.feed.rolling_contract import digest
    if (value.session != result['session'] or value.record_sha256 != result['record_sha256']
            or value.state_sha256 != result['state_sha256']
            or digest(value.model_dump(by_alias=True)) != result['runtime_authority_sha256']):
        raise ValueError('worker result changed before health projection')
    inventory, has_origin = _inventory(conn)
    if not has_origin:
        raise ValueError('health projection requires committed origin')
    payload = Projection(schema_id=SCHEMA, config_sha256=_config(config),
        inventory_sha256=inventory, session=value.session, record_sha256=value.record_sha256,
        runtime_authority_sha256=result['runtime_authority_sha256']).model_dump()
    _write({'projection': payload, 'hmac_sha256': _signature(payload)}, path())


def health(config, *, fallback, target=None, now=None):
    """Reobserve row versions and causal age without reading retained payloads."""
    if not getattr(config, 'operational_source_only', False):
        return fallback(config)
    conn = store.connect(config.database_url, connect_timeout=1, statement_timeout_ms=750)
    try:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        inventory, has_origin = _inventory(conn)
    finally:
        conn.rollback()
        conn.close()
    source = target if target is not None else path()
    if not has_origin:
        if source.exists():
            raise ValueError('retained health projection origin is absent')
        return fallback(config)
    with source.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('shadow health projection exceeds bound')
    wrapped = json.loads(raw)
    if not isinstance(wrapped, dict) or set(wrapped) != {'projection', 'hmac_sha256'}:
        raise ValueError('shadow health projection shape changed')
    payload = wrapped['projection']
    if not hmac.compare_digest(str(wrapped['hmac_sha256']), _signature(payload)):
        raise ValueError('shadow health projection authentication failed')
    projection = Projection.model_validate(payload)
    if projection.config_sha256 != _config(config) or projection.inventory_sha256 != inventory:
        raise ValueError('shadow health projection binding changed')
    instant = now or datetime.now(timezone.utc)
    latest = calendar.latest_closed_session(instant)
    if projection.session == latest:
        return {'service_health': 'HEALTHY_ATTESTED', 'target_session': latest}
    if calendar.next_session(projection.session) == latest:
        opened, _ = calendar.session_window(calendar.next_session(latest))
        if instant < opened.astimezone(timezone.utc):
            return {'service_health': 'HEALTHY_WAITING', 'target_session': latest}
    raise ValueError('shadow health projection missed its causal session boundary')
