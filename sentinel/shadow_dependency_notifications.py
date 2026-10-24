"""Bounded dependency diagnostics; notification history is the existing outbox."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import re

from sentinel import supervisor_io

WARNING = 'SHADOW_DEPENDENCY_UNAVAILABLE'
RECOVERED = 'SHADOW_DEPENDENCY_RECOVERED'
PREFIX = 'SENTINEL_SHADOW_DEPENDENCY='
STAGES = frozenset({
    'ACQUISITION_LOCK', 'SOURCE_PREFLIGHT', 'SOURCE_REFERENCES',
    'PRICE_ACQUISITION', 'CANDIDATE_BUILD', 'CANDIDATE_VALIDATION',
    'SOURCE_CORROBORATION', 'PUBLICATION', 'SHADOW_ADVANCE',
})
CAUSES = frozenset({
    'CORPUS_LOCK_BUSY', 'WRITER_LOCK_BUSY', 'DATABASE_UNAVAILABLE',
    'WORKER_BUDGET_EXHAUSTED', 'BACKUP_WRITE_FENCED', 'DEPENDENCY_UNAVAILABLE',
})
_HASH = re.compile(r'^[0-9a-f]{64}$')
_OBSERVATION = re.compile(r'^[A-Za-z0-9][A-Za-z0-9.-]{0,63}$')
_TYPE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$')


@dataclass(frozen=True)
class FailureContext:
    stage: str
    observed_at: datetime


def _utc(value=None):
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError('dependency event requires explicit UTC')
    return value


def capture_stage(exc: BaseException, stage: str, *, now=None) -> None:
    """Attach original phase before rollback/cleanup; never change its outcome."""
    try:
        if stage not in STAGES:
            raise ValueError('unknown dependency stage')
        if not isinstance(getattr(exc, '_sentinel_dependency_context', None), FailureContext):
            exc._sentinel_dependency_context = FailureContext(stage, _utc(now))
            if _cause(exc)[1] is not None:
                # Cleanup may raise an independent terminal error afterward.
                # Keep this original diagnostic without traversing __context__.
                supervisor_io.report(PREFIX + json.dumps(warning_payload(exc, now=now), sort_keys=True))
    except Exception:
        pass


def _chain(exc):
    # Match the existing reviewed walk; never follow incidental __context__ or
    # walk through an integrity decision to an older availability exception.
    from sentinel.shadow_worker import _availability_cause
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        yield exc
        exc = _availability_cause(exc)


def _cause(exc):
    from sentinel import backup_guard
    from sentinel.dependency_availability import database_unavailable
    from sentinel.execution.journal import WriterLockUnavailable
    from sentinel.feed.publication import CorpusLockUnavailable
    from sentinel.feed.rolling_jobs import JobDeadlineExceeded
    for current in _chain(exc):
        if isinstance(current, CorpusLockUnavailable):
            return 'CORPUS_LOCK_BUSY', current
        if isinstance(current, WriterLockUnavailable):
            return 'WRITER_LOCK_BUSY', current
        if database_unavailable(current):
            return 'DATABASE_UNAVAILABLE', current
        if isinstance(current, JobDeadlineExceeded):
            return 'WORKER_BUDGET_EXHAUSTED', current
        if (isinstance(current, backup_guard.BackupWriteFenced)
                and not isinstance(current, backup_guard.BackupConfigurationRefused)):
            return 'BACKUP_WRITE_FENCED', current
    return 'DEPENDENCY_UNAVAILABLE', None


def _exception_type(original):
    """Name reviewed classes, never arbitrary exception class attributes."""
    from sentinel import backup_guard, backup_runtime_authority
    from sentinel.execution.journal import WriterLockUnavailable
    from sentinel.feed.publication import CorpusLockUnavailable
    from sentinel.feed.rolling_jobs import JobDeadlineExceeded
    reviewed = (CorpusLockUnavailable, WriterLockUnavailable, JobDeadlineExceeded,
                backup_guard.BackupWriteFenced, backup_guard.BackupUnavailable,
                backup_runtime_authority.BackupRuntimeUnavailable,
                backup_runtime_authority.BackupHorizonExceeded)
    for candidate in reviewed:
        if type(original) is candidate:
            return candidate.__module__ + '.' + candidate.__qualname__
    # psycopg's official SQLSTATE lookup is the source of allowed class names.
    import psycopg
    if type(original) in (psycopg.OperationalError, psycopg.InterfaceError):
        return type(original).__module__ + '.' + type(original).__qualname__
    sqlstate = getattr(original, 'sqlstate', None)
    if isinstance(sqlstate, str) and re.fullmatch(r'[0-9A-Z]{5}', sqlstate):
        try:
            candidate = psycopg.errors.lookup(sqlstate)
        except KeyError:
            candidate = None
        if type(original) is candidate:
            return candidate.__module__ + '.' + candidate.__qualname__
    return 'UNAVAILABLE'


def _runtime():
    commit = os.environ.get('SENTINEL_GIT_COMMIT', '')
    image = os.environ.get('SENTINEL_RUNTIME_IMAGE_DIGEST', '')
    if (not re.fullmatch(r'[0-9a-f]{40}', commit)
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', image)
            or os.environ.get('SENTINEL_IMAGE_SOURCE_REVISION') != commit):
        raise ValueError('dependency notification runtime identity is unavailable')
    return {'git_commit': commit, 'image_digest': image}


def warning_key(session):
    return f'shadow-dependency:{session}:unavailable'


def _session(value):
    from sentinel.feed import calendar
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('dependency session is unavailable')
    calendar.session_window(value)
    return value


def warning_payload(exc, config=None, *, now=None):
    from sentinel.feed import calendar
    instant = _utc(now)
    context = next((getattr(item, '_sentinel_dependency_context', None)
                    for item in _chain(exc)
                    if isinstance(getattr(item, '_sentinel_dependency_context', None), FailureContext)), None)
    stage = context.stage if context is not None else 'SHADOW_ADVANCE'
    event_at = context.observed_at if context is not None else instant
    if stage not in STAGES or not event_at <= instant:
        raise ValueError('dependency diagnostic context changed')
    cause, original = _cause(exc)
    observation = getattr(config, 'observation_id', None) or os.environ.get(
        'SENTINEL_SHADOW_OBSERVATION_ID', 'primary')
    if not isinstance(observation, str) or not _OBSERVATION.fullmatch(observation):
        raise ValueError('dependency observation is unavailable')
    name = _exception_type(original)
    payload = {
        'cause_code': cause, 'operation_stage': stage, 'exception_type': name,
        'observed_at': event_at.isoformat(),
        'decision_session': calendar.latest_closed_session(event_at),
        'observation_id': observation,
        **_runtime(),
    }
    sqlstate = getattr(original, 'sqlstate', None)
    if cause == 'DATABASE_UNAVAILABLE' and isinstance(sqlstate, str) and re.fullmatch(r'[0-9A-Z]{5}', sqlstate):
        payload['sqlstate'] = sqlstate
    return payload


def _existing_warning(conn, session):
    from sentinel.automation import outbox
    row = conn.execute('SELECT alert_id FROM sentinel_alert_outbox WHERE idempotency_key=%s',
                       (warning_key(session),)).fetchone()
    if row is None:
        return None
    alert = outbox.load_alert(conn, row[0])
    if (alert.event_type != WARNING or alert.severity != 'WARN'
            or alert.payload.get('decision_session') != session):
        raise ValueError('dependency warning identity changed')
    return alert


def enqueue_warning(conn, payload):
    """Retain the first immutable payload, including a legacy generic warning."""
    from sentinel.automation import outbox
    session = _session(payload['decision_session'])
    # Serialize notification-only insertion. This is neither the financial
    # writer lock nor a new state registry; enqueue commits and releases it.
    conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (warning_key(session),))
    retained = _existing_warning(conn, session)
    if retained is not None:
        conn.commit()
        return retained
    return outbox.enqueue(conn, idempotency_key=warning_key(session),
                          event_type=WARNING, severity='WARN', payload=payload)


def _write_warning(payload):
    from sentinel.config import SentinelConfig
    from sentinel.feed import store
    conn = store.connect(SentinelConfig.from_env().database_url,
                         connect_timeout=1, statement_timeout_ms=750)
    try:
        enqueue_warning(conn, payload)
    finally:
        conn.close()


def report_failure(exc, config=None, *, now=None):
    """Log independently of a finite outbox attempt; never raise to the worker."""
    try:
        payload = warning_payload(exc, config, now=now)
        supervisor_io.report(PREFIX + json.dumps(payload, sort_keys=True))
        supervisor_io.run(_write_warning, payload, timeout=1.0)
    except Exception as failure:
        supervisor_io.report('WARNING: dependency diagnostic publication unavailable: '
                             + type(failure).__name__)


def fallback_warning(*, now=None):
    """Supervisor fallback has no original cause or stage to invent."""
    from sentinel.feed import calendar
    instant = _utc(now)
    return {'decision_session': calendar.latest_closed_session(instant),
            'state': 'DEPENDENCY_RETRY_PENDING',
            'detail': 'Strategy update delayed; dependency details unavailable. The update will retry.'}


def recovery_key(alert_id):
    return 'shadow-dependency-recovered:' + alert_id


def _verified_result(conn, config, result, instant):
    """Bind canonical worker success to its committed prospective authority."""
    from sentinel import rolling_authority
    from sentinel.feed import calendar, rolling_go_inputs
    from sentinel.feed.rolling_contract import digest
    if (not isinstance(result, dict) or result.get('shadow_verdict') != 'SHADOW_GO'
            or result.get('verification') != 'VERIFIED'
            or result.get('session') != calendar.latest_closed_session(instant)
            or result.get('live_frontier') != result.get('session')
            or result.get('sessions_lag') != 0
            or not all(isinstance(result.get(key), str) and _HASH.fullmatch(result[key])
                       for key in ('record_sha256', 'state_sha256', 'runtime_authority_sha256',
                                   'runtime_identity_sha256'))):
        return False
    values = rolling_authority.latest(conn, config.observation_id)
    if not values or isinstance(values[0], rolling_authority.ReconstructionReceipt):
        return False
    value = values[0]
    current = rolling_go_inputs.current(conn)
    return bool(
        value.observation_id == config.observation_id and value.session == result['session']
        and value.record_sha256 == result['record_sha256']
        and value.state_sha256 == result['state_sha256']
        and value.runtime_sha256 == result['runtime_identity_sha256']
        and digest(value.model_dump(by_alias=True)) == result['runtime_authority_sha256']
        and current is not None and value.publication_sha256 == digest(current.to_dict()))


def enqueue_recoveries(conn, config, result, *, now=None):
    """Only previously delivered warnings may earn one verified recovery notice."""
    from sentinel.automation import outbox
    instant = _utc(now)
    runtime = _runtime()
    if (not _OBSERVATION.fullmatch(config.observation_id)
            or not _verified_result(conn, config, result, instant)):
        conn.rollback()
        return []
    rows = conn.execute(
        "SELECT a.alert_id FROM sentinel_alert_outbox a WHERE a.event_type=%s"
        " AND a.severity='WARN' AND a.state='DELIVERED'"
        " AND a.idempotency_key=%s AND a.payload->>'decision_session'=%s"
        " AND (a.payload->>'observation_id'=%s OR"
        "      (a.payload->>'observation_id' IS NULL AND %s='primary'))"
        " AND a.delivered_at IS NOT NULL AND a.delivered_at<=%s"
        " AND EXISTS(SELECT 1 FROM sentinel_web_push_deliveries d"
        " WHERE d.alert_id=a.alert_id AND d.state='DELIVERED'"
        " AND d.delivered_at>=a.created_at AND d.delivered_at<=%s)"
        " AND NOT EXISTS(SELECT 1 FROM sentinel_alert_outbox r WHERE r.idempotency_key=%s||a.alert_id)"
        " ORDER BY a.created_at,a.alert_id LIMIT 1",
        (WARNING, warning_key(result['session']), result['session'],
         config.observation_id, config.observation_id,
         instant, instant, 'shadow-dependency-recovered:')).fetchall()
    recovered = []
    for (alert_id,) in rows:
        warning = outbox.load_alert(conn, alert_id)
        payload = dict(warning.payload)
        try:
            session = _session(payload.get('decision_session'))
            if (warning.idempotency_key != warning_key(session)
                    or session != result['session'] or warning.created_at >= instant):
                continue
            observation = payload.get('observation_id')
            if observation is None:
                # Historical generic keys named no observation; only the
                # canonical primary can unambiguously own that old warning.
                if config.observation_id != 'primary' or set(payload) != {'decision_session', 'state', 'detail'}:
                    continue
                original = warning.created_at
            else:
                if observation != config.observation_id:
                    continue
                if (payload.get('cause_code') not in CAUSES or payload.get('operation_stage') not in STAGES
                        or not isinstance(payload.get('exception_type'), str)
                        or not _TYPE.fullmatch(payload['exception_type'])
                        or not re.fullmatch(r'[0-9a-f]{40}', payload.get('git_commit', ''))
                        or not re.fullmatch(r'sha256:[0-9a-f]{64}', payload.get('image_digest', ''))):
                    continue
                original = _utc(datetime.fromisoformat(payload['observed_at']))
            if original > warning.created_at or original >= instant:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        recovery = {
            'decision_session': session, 'observation_id': config.observation_id,
            'warning_alert_id': warning.alert_id,
            'warning_observed_at': original.isoformat(), 'recovered_at': instant.isoformat(),
            'observed_at': instant.isoformat(), **runtime,
            'verified_session': result['session'], 'record_sha256': result['record_sha256'],
            'runtime_authority_sha256': result['runtime_authority_sha256'],
        }
        key = recovery_key(warning.alert_id)
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (key,))
        if conn.execute('SELECT alert_id FROM sentinel_alert_outbox WHERE idempotency_key=%s',
                        (key,)).fetchone() is not None:
            conn.commit()
            continue
        recovered.append(outbox.enqueue(conn, idempotency_key=key,
                                        event_type=RECOVERED, severity='INFO', payload=recovery))
    conn.rollback()
    return recovered


def _write_recoveries(config, result, instant):
    from sentinel.feed import store
    conn = store.connect(config.database_url, connect_timeout=1, statement_timeout_ms=750)
    try:
        enqueue_recoveries(conn, config, result, now=instant)
    finally:
        conn.close()


def report_recovery(config, result, *, now=None):
    """Successful economics cannot become a failure because its notice failed."""
    try:
        supervisor_io.run(_write_recoveries, config, result, _utc(now), timeout=1.0)
    except Exception as failure:
        supervisor_io.report('WARNING: verified dependency recovery notification unavailable: '
                             + type(failure).__name__)
