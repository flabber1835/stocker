"""Separately bounded GET-only account/fill collection; no push credentials."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import signal
from threading import Event
import time
from typing import Literal

from sentinel import supervisor_io

HEARTBEAT = Path('/tmp/sentinel-execution-collector-heartbeat')
DEADLINE_SECONDS = 30
CollectionKind = Literal['ACCOUNT', 'FILL', 'ISSUER']
DiagnosticStage = Literal['COLLECT_JOB', 'FAILURE_RECORD']


class _FailureDiagnostics:
    """Six bounded diagnostic slots; never collection or notification authority."""

    def __init__(self) -> None:
        self._last: dict[tuple[CollectionKind, DiagnosticStage], tuple[str, int | None, str | None]] = {}

    def failure(self, kind: CollectionKind, stage: DiagnosticStage, error: BaseException) -> bool:
        try:
            if kind not in {'ACCOUNT', 'FILL', 'ISSUER'} or stage not in {'COLLECT_JOB', 'FAILURE_RECORD'}:
                return False
            observed_at = datetime.now(timezone.utc)
            monotonic_at = time.monotonic()
            diagnostic = supervisor_io._validate_diagnostic(supervisor_io.error_diagnostic(error))
            if (observed_at.utcoffset() != timedelta(0)
                    or type(monotonic_at) not in {int, float}
                    or not math.isfinite(monotonic_at) or monotonic_at < 0):
                return False
            slot = (kind, stage)
            cause = (diagnostic['exception_type'], diagnostic['errno'], diagnostic['sqlstate'])
            if self._last.get(slot) == cause:
                return False
            record = dict(schema='sentinel.execution-collector-diagnostic/1', kind=kind,
                stage=stage, observed_at=observed_at.isoformat(), monotonic_at=monotonic_at,
                error=diagnostic)
            encoded = json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False)
            if len(encoded.encode('utf-8'))+1 > supervisor_io.MAX_RECORD_BYTES:
                return False
            if supervisor_io._pipe_report(encoded) is not True:
                return False
            self._last[slot] = cause
            return True
        except Exception:
            return False

    def collected(self, kind: CollectionKind, result: object) -> None:
        positive = (kind in {'ACCOUNT', 'FILL'} and type(result) is str and result == 'COLLECTED'
                    or kind == 'ISSUER' and type(result) is dict
                    and type(result.get('status')) is str and result['status'] == 'REFRESHED')
        if positive:
            for stage in ('COLLECT_JOB', 'FAILURE_RECORD'):
                self._last.pop((kind, stage), None)


def record_stall(kind, reason):
    from sentinel.feed import store
    from sentinel.automation import outbox
    conn = store.connect(os.environ['SENTINEL_DATABASE_URL'],connect_timeout=3,statement_timeout_ms=2000)
    try:
        prefix = 'account-status' if kind == 'ACCOUNT' else 'fill-notification'
        outbox.enqueue(conn,idempotency_key=prefix+'-collection:'+reason,
            event_type='ACCOUNT_STATUS_COLLECTION_FAILED' if kind == 'ACCOUNT' else 'FILL_NOTIFICATION_COLLECTION_FAILED',
            severity='WARN',payload={'reason':reason})
    finally:
        conn.rollback();conn.close()


def collect_once(kind, *, reader=None, config=None, connection_factory=None):
    """Existing execution collectors keep their binding and native receipt rules."""
    from sentinel.config import SentinelConfig
    from sentinel.feed import store
    from sentinel.automation import outbox
    from sentinel.execution import account_status, fill_notifications
    config = config or SentinelConfig.from_env()
    config.trading_endpoint  # Refuse unknown origins before any collector I/O.
    factory = connection_factory or store.connect
    conn = factory(config.database_url,connect_timeout=3,statement_timeout_ms=2000)
    try:
        if kind == 'ISSUER':
            from sentinel.execution import issuer_refresh
            from sentinel.feed.issuer_refresh import CONTACT_ENV
            return issuer_refresh.collect(conn, email=os.environ.get(CONTACT_ENV, ''))
        module = {'ACCOUNT':account_status,'FILL':fill_notifications}[kind]
        try:
            asyncio.run(module.collect(conn,config=config,reader=reader))
            return 'COLLECTED'
        except Exception as exc:
            conn.rollback()
            typed = kind == 'FILL' and isinstance(exc,fill_notifications.FillNotificationRefused)
            reason = str(exc) if typed else type(exc).__name__
            prefix = 'account-status' if kind == 'ACCOUNT' else 'fill-notification'
            outbox.enqueue(conn,idempotency_key=prefix+'-collection:'+reason,
                event_type='ACCOUNT_STATUS_COLLECTION_FAILED' if kind == 'ACCOUNT' else 'FILL_NOTIFICATION_COLLECTION_FAILED',
                severity='CRITICAL' if typed else 'WARN',payload={'reason':reason})
            return 'REFUSED'
    finally:
        conn.rollback(); conn.close()


def run(*, stopped=None, runner=supervisor_io.run, clock=time.monotonic):
    from sentinel import local_paper
    from sentinel.execution import account_status, fill_notifications
    from sentinel.execution import issuer_refresh
    from sentinel.feed.issuer_refresh import CONTACT_ENV
    from sentinel.config import trading_endpoint, DEFAULT_BASE_URL
    from sentinel.trading_environment import TradingEnvironment
    if os.environ.get('SENTINEL_WEB_PUSH_VAPID_PRIVATE_KEY'):
        raise ValueError('execution collector must not hold push signing credentials')
    stopped = stopped or Event()
    for signum in (signal.SIGTERM,signal.SIGINT):
        signal.signal(signum,lambda *_:stopped.set())
    due = {'ACCOUNT':float('-inf'),'FILL':float('-inf'),'ISSUER':float('-inf')}
    diagnostics = _FailureDiagnostics()
    try:
        while not stopped.is_set():
            live = trading_endpoint(os.environ.get('ALPACA_BASE_URL', DEFAULT_BASE_URL)).environment is TradingEnvironment.LIVE
            for kind, enabled, interval in (
                    ('ACCOUNT',live or local_paper.enabled(),account_status.POLL_SECONDS),
                    ('FILL',bool(os.environ.get(fill_notifications.SINCE_ENV)),fill_notifications.POLL_SECONDS),
                    ('ISSUER',(live or local_paper.enabled()) and bool(os.environ.get(CONTACT_ENV)),3600)):
                if not enabled or stopped.is_set() or clock() < due[kind]:
                    continue
                due[kind] = clock()+interval
                try:
                    result = runner(collect_once,kind,
                        timeout=issuer_refresh.DEADLINE_SECONDS if kind == 'ISSUER' else DEADLINE_SECONDS,
                        start_method='spawn')
                    diagnostics.collected(kind, result)
                    if kind == 'ISSUER' and isinstance(result,dict):
                        retry = result.get('retry_after_seconds')
                        if type(retry) is int and 60 <= retry <= 86400:
                            due[kind] = clock()+retry
                except Exception as exc:
                    # No dependency response or credential is emitted. Existing
                    # account freshness expires; no invented observation replaces it.
                    diagnostics.failure(kind, 'COLLECT_JOB', exc)
                    supervisor_io.report('execution collector unavailable: '+type(exc).__name__)
                    if kind != 'ISSUER':
                        try:
                            runner(record_stall,kind,type(exc).__name__,timeout=5,start_method='spawn')
                        except Exception as recording_error:
                            diagnostics.failure(kind, 'FAILURE_RECORD', recording_error)
                            supervisor_io.report('execution collection failure receipt unavailable')
                HEARTBEAT.write_text(datetime.now(timezone.utc).isoformat(),encoding='ascii')
            HEARTBEAT.write_text(datetime.now(timezone.utc).isoformat(),encoding='ascii')
            stopped.wait(2)
    finally:
        HEARTBEAT.unlink(missing_ok=True)
    return 0


def health():
    try:
        stamp = datetime.fromisoformat(HEARTBEAT.read_text(encoding='ascii'))
        return 0 if timedelta(0) <= datetime.now(timezone.utc)-stamp <= timedelta(seconds=75) else 1
    except (OSError,ValueError):
        return 1


if __name__ == '__main__':
    import sys
    raise SystemExit(health() if sys.argv[1:] == ['--health'] else run())
