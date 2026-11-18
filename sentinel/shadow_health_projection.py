"""Bounded health hints; never financial or broker admission authority."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sentinel.feed import calendar, publication, store

MAX_BYTES = 65536
SCHEMA = 'sentinel.shadow-health-projection/2'


class Projection(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    schema_id: str = Field(pattern=r'^sentinel\.shadow-health-projection/2$')
    config_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    inventory_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    session: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    record_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    runtime_authority_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    waiting_session: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    calendar_identity: str = Field(min_length=1, max_length=128)
    valid_from: str = Field(min_length=20, max_length=40)
    current_until: str = Field(min_length=20, max_length=40)
    valid_until: str = Field(min_length=20, max_length=40)

    @model_validator(mode='after')
    def causal_interval(self):
        begin, current, end = map(_utc, (self.valid_from, self.current_until, self.valid_until))
        if (not begin < current < end or begin.date().isoformat() != self.session
                or current.date().isoformat() != self.waiting_session
                or self.waiting_session <= self.session
                or end.date().isoformat() <= self.waiting_session
                or not self.calendar_identity.startswith('XNYS/exchange_calendars ')):
            raise ValueError('shadow health causal interval changed')
        return self


def _utc(value):
    instant = datetime.fromisoformat(value)
    if instant.utcoffset() != timedelta(0):
        raise ValueError('shadow health causal interval requires UTC')
    return instant


def _now():
    return datetime.now(timezone.utc)


def _calendar_bounds(session):
    """Resolve once in the verified producer, never in a disposable reader."""
    following = calendar.next_session(session)
    after_following = calendar.next_session(following)
    _opened, begin = calendar.session_window(session)
    _opened, current = calendar.session_window(following)
    end, _closed = calendar.session_window(after_following)
    return dict(waiting_session=following, calendar_identity=calendar.calendar_version(),
        valid_from=begin.astimezone(timezone.utc).isoformat(),
        current_until=current.astimezone(timezone.utc).isoformat(),
        valid_until=end.astimezone(timezone.utc).isoformat())


def _temporal_health(projection, instant):
    if instant.utcoffset() is None:
        raise ValueError('shadow health clock requires a timezone')
    instant = instant.astimezone(timezone.utc)
    begin, current, end = map(_utc, (
        projection.valid_from, projection.current_until, projection.valid_until))
    if instant < begin or instant >= end:
        raise ValueError('shadow health projection missed its causal session boundary')
    if instant < current:
        return {'service_health': 'HEALTHY_ATTESTED', 'target_session': projection.session}
    return {'service_health': 'HEALTHY_WAITING', 'target_session': projection.waiting_session}


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


def _inventory_rows(conn):
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
        "FROM sentinel_processed_sessions WHERE cursor_name LIKE ANY(%s) "
        "ORDER BY cursor_name LIMIT 10001",
        (['shadow-%', 'rolling-%', 'catchup%', 'formation-%',
          'runtime-admission:%'],)
    ).fetchall()
    pubs = conn.execute(
        "SELECT version,tableoid::text,xmin::text,ctid::text "
        "FROM sentinel_corpus_publications ORDER BY version LIMIT 10001"
    ).fetchall()
    if len(rows) > 10000 or len(pubs) > 10000:
        raise ValueError('shadow health inventory exceeds bound')
    return relation, rows, pubs


def _inventory(conn):
    relation, rows, pubs = _inventory_rows(conn)
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
    """Called under the canonical writer lock after full financial verification."""
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
        runtime_authority_sha256=result['runtime_authority_sha256'],
        **_calendar_bounds(value.session)).model_dump()
    _write({'projection': payload, 'hmac_sha256': _signature(payload)}, path())


class ProjectionRenewalRequired(ValueError):
    """Negative auxiliary evidence; only the canonical producer can renew it."""

    def __init__(self, reason: str, *, session: str | None = None, binding: str | None = None):
        self.reason = reason
        self.session = session
        self.binding = binding
        super().__init__('shadow health projection ' + reason)


def health(config, *, fallback, target=None, now=None, observe_close_wait=False):
    """Reobserve row versions and causal age without reading retained payloads."""
    if not getattr(config, 'operational_source_only', False):
        return fallback(config)
    source = target if target is not None else path()
    conn = store.connect(config.database_url, connect_timeout=1, statement_timeout_ms=750)
    try:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        relation, rows, pubs = _inventory_rows(conn)
        if any(row[0] == 'rolling-cold-start:v1' for row in rows):
            projection = _signed_projection(config, source)
            if projection.inventory_sha256 == _digest([relation, rows, pubs]):
                return _temporal_health(projection, now if now is not None else _now())
            if (observe_close_wait and len(pubs) >= 2
                    and projection.inventory_sha256 == _digest([relation, rows, pubs[:-1]])):
                wait = _publication_wait(conn, projection, pubs[-2][0], pubs[-1][0], now)
                if wait is not None:
                    return wait
            raise ProjectionRenewalRequired('binding changed', session=projection.session, binding='inventory')
    finally:
        conn.rollback()
        conn.close()
    if source.exists():
        raise ValueError('retained health projection origin is absent')
    return fallback(config)


def _publication_wait(conn, projection, previous, version, now):
    """Classify one appended operational close while the signed prefix is intact."""
    if version != previous + 1:
        return None
    row = conn.execute("""
        SELECT j.created_at, p.published_at, j.updated_at, j.deadline, p.window_start, p.evidence,
               prior.evidence->%s->>'receipt_sha256'
        FROM sentinel_corpus_publications p
        JOIN sentinel_corpus_publications prior ON prior.version=p.previous_version
        JOIN sentinel_operational_snapshots b ON b.publication_version=p.version
        JOIN sentinel_snapshot_jobs j ON j.job_id=b.job_id AND j.candidate_id=b.candidate_id
        JOIN sentinel_operational_snapshot_validations v ON v.candidate_id=b.candidate_id
        JOIN sentinel_publication_validation_receipts r ON r.publication_version=p.version
        WHERE p.version=%s AND prior.version=%s AND prior.window_end=%s AND p.window_end=%s
          AND j.state='PUBLISHED' AND j.publication_version=p.version
          AND NOT (p.evidence ? 'operational_recovery')
          AND p.run_id IS NULL AND p.window_start IS NOT NULL AND octet_length(p.evidence::text)<=65536
          AND r.receipt_sha256=p.evidence->%s->>'receipt_sha256'
          AND r.receipt_hmac_sha256=p.evidence->%s->>'receipt_hmac_sha256'
          AND v.validation_sha256=b.validation_sha256
          AND p.evidence->'rolling_snapshot'->>'candidate_id'=b.candidate_id::text
          AND p.evidence->'rolling_snapshot'->>'job_id'=b.job_id::text
          AND p.evidence->'rolling_snapshot'->>'validation_sha256'=b.validation_sha256
        """, (publication.RECEIPT_EVIDENCE_KEY, version, previous, projection.session, projection.waiting_session,
              publication.RECEIPT_EVIDENCE_KEY, publication.RECEIPT_EVIDENCE_KEY)).fetchone()
    instant = now if now is not None else _now()
    if row is None or _temporal_health(projection, instant)['service_health'] != 'HEALTHY_WAITING':
        return None
    created, published, completed, deadline, start, evidence, prior_receipt = row
    expires = min(deadline, _utc(projection.valid_until))
    if not _utc(projection.current_until) <= created <= published <= completed <= instant < expires:
        return None
    receipt = evidence.pop(publication.RECEIPT_EVIDENCE_KEY)
    if (not prior_receipt or receipt.get('previous_receipt_sha256') != prior_receipt
            or receipt.get('schema') != publication.RECEIPT_SCHEMA):
        return None
    body = publication._receipt_body(version=version, previous_version=previous, run_id=None,
        published_at=published, window_start=start, window_end=projection.waiting_session,
        evidence=evidence, origin_run_status=None, previous_receipt_sha256=prior_receipt)
    if (receipt['receipt_sha256'] != publication._receipt_digest(body)
            or not hmac.compare_digest(receipt['receipt_hmac_sha256'], publication._receipt_hmac(body))):
        return None
    return {'service_health': 'CLOSE_PUBLICATION_PENDING', 'target_session': projection.waiting_session,
            'valid_until': expires}


def _authenticated_projection(config, inventory, source):
    projection = _signed_projection(config, source)
    if projection.inventory_sha256 != inventory:
        raise ProjectionRenewalRequired('binding changed', session=projection.session, binding='inventory')
    return projection


def _signed_projection(config, source):
    try:
        with source.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
    except FileNotFoundError as exc:
        raise ProjectionRenewalRequired('missing') from exc
    if len(raw) > MAX_BYTES:
        raise ValueError('shadow health projection exceeds bound')
    wrapped = json.loads(raw)
    if not isinstance(wrapped, dict) or set(wrapped) != {'projection', 'hmac_sha256'}:
        raise ValueError('shadow health projection shape changed')
    payload = wrapped['projection']
    if not hmac.compare_digest(str(wrapped['hmac_sha256']), _signature(payload)):
        raise ValueError('shadow health projection authentication failed')
    projection = Projection.model_validate(payload)
    if projection.config_sha256 != _config(config):
        raise ProjectionRenewalRequired('binding changed', session=projection.session, binding='config')
    return projection


_SCHEDULING_RELATIONS = (
    'sentinel_processed_sessions', 'sentinel_corpus_publications',
    'sentinel_operational_snapshots', 'sentinel_snapshot_jobs',
    'sentinel_price_candidates', 'sentinel_candidate_layouts',
    'sentinel_candidate_blocks', 'sentinel_normalized_blocks',
    'sentinel_snapshot_bars', 'sentinel_snapshot_benchmarks',
    'sentinel_snapshot_evidence', 'sentinel_snapshot_validations',
    'sentinel_operational_snapshot_validations', 'sentinel_snapshot_retirements',
    'sentinel_readiness_snapshots',
)


def scheduling_subject(config, source):
    """Observe only metadata for a supervisor's optional unchanged-poll hint."""
    from sentinel import operational_ddl_epoch

    conn = store.connect(config.database_url, connect_timeout=1, statement_timeout_ms=750)
    try:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        inventory, has_origin = _inventory(conn)
        if not has_origin:
            return None
        projection = _authenticated_projection(config, inventory, source)
        if _temporal_health(projection, _now())['service_health'] != 'HEALTHY_ATTESTED':
            return None
        ddl = operational_ddl_epoch.current(conn)
        setup = conn.execute("SELECT pg_postmaster_start_time(),xmin::text,ctid::text "
            "FROM sentinel_processed_sessions WHERE cursor_name='operational-schema:v1'").fetchone()
        physical = conn.execute(
            'SELECT relname,oid,pg_relation_filenode(oid),reltoastrelid,'
            ' pg_relation_filenode(reltoastrelid) FROM pg_class '
            "WHERE relnamespace='public'::regnamespace AND relname=ANY(%s) ORDER BY relname",
            (list(_SCHEDULING_RELATIONS),)).fetchall()
        if setup is None or len(physical) != len(_SCHEDULING_RELATIONS):
            return None
        binding = conn.execute('''
            SELECT c.candidate_id, jsonb_array_length(c.session_axis),
                   ARRAY[c.reference_sha256,c.source_evidence_sha256,s.validation_sha256,v.validation_sha256],
                   ARRAY[s.xmin::text,s.ctid::text,j.xmin::text,j.ctid::text,
                         c.xmin::text,c.ctid::text,l.xmin::text,l.ctid::text,
                         v.xmin::text,v.ctid::text,o.xmin::text,o.ctid::text]
              FROM (SELECT version,window_end FROM sentinel_corpus_publications
                    ORDER BY version DESC LIMIT 1) p
              JOIN sentinel_operational_snapshots s ON s.publication_version=p.version
              JOIN sentinel_snapshot_jobs j USING(job_id)
              JOIN sentinel_price_candidates c ON c.candidate_id=s.candidate_id
              JOIN sentinel_candidate_layouts l ON l.candidate_id=c.candidate_id
              JOIN sentinel_snapshot_validations v ON v.candidate_id=c.candidate_id
              JOIN sentinel_operational_snapshot_validations o ON o.candidate_id=c.candidate_id
             WHERE p.window_end=%s AND j.state='PUBLISHED' AND l.snapshot_id=c.snapshot_id
               AND o.validation_sha256=s.validation_sha256
               AND NOT EXISTS (SELECT 1 FROM sentinel_snapshot_retirements r
                               WHERE r.candidate_id=c.candidate_id)
            ''', (projection.session,)).fetchone()
        if binding is None:
            return None
        candidate, sessions, evidence_ids, _ = binding
        evidence = conn.execute('''
            SELECT evidence_sha256,xmin::text,ctid::text
            FROM sentinel_snapshot_evidence WHERE evidence_sha256=ANY(%s)
              AND (canonical_payload IS NOT NULL OR payload IS NOT NULL)
            ORDER BY evidence_sha256
            ''', (evidence_ids,)).fetchall()
        blocks = conn.execute('''
            SELECT c.kind,c.session,c.block_sha256,c.xmin::text,c.ctid::text,b.xmin::text,b.ctid::text
            FROM sentinel_candidate_blocks c JOIN sentinel_normalized_blocks b USING(block_sha256)
            WHERE c.candidate_id=%s AND b.canonical_payload IS NOT NULL
            ORDER BY c.kind,c.session LIMIT 853
            ''', (candidate,)).fetchall()
        if len(evidence) != len(set(evidence_ids)) or len(blocks) != 2 * sessions:
            return None
        verdict = conn.execute('''
            SELECT snapshot_id,computed_at,ready,xmin::text,ctid::text
            FROM sentinel_readiness_snapshots ORDER BY computed_at DESC,snapshot_id DESC LIMIT 1
            ''').fetchone()
        subject = _digest([projection.model_dump(), ddl, setup, physical, binding, evidence, blocks])
        return subject, verdict
    finally:
        conn.rollback()
        conn.close()
