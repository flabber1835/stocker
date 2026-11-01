"""Separately bounded GET-only account/fill collection; no push credentials."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import signal
from threading import Event
import time

from sentinel import supervisor_io

HEARTBEAT = Path('/tmp/sentinel-execution-collector-heartbeat')
DEADLINE_SECONDS = 30


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
    config.assert_paper()
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
    if os.environ.get('SENTINEL_WEB_PUSH_VAPID_PRIVATE_KEY'):
        raise ValueError('execution collector must not hold push signing credentials')
    stopped = stopped or Event()
    for signum in (signal.SIGTERM,signal.SIGINT):
        signal.signal(signum,lambda *_:stopped.set())
    due = {'ACCOUNT':float('-inf'),'FILL':float('-inf'),'ISSUER':float('-inf')}
    try:
        while not stopped.is_set():
            for kind, enabled, interval in (
                    ('ACCOUNT',local_paper.enabled(),account_status.POLL_SECONDS),
                    ('FILL',bool(os.environ.get(fill_notifications.SINCE_ENV)),fill_notifications.POLL_SECONDS),
                    ('ISSUER',local_paper.enabled() and bool(os.environ.get(CONTACT_ENV)),3600)):
                if not enabled or stopped.is_set() or clock() < due[kind]:
                    continue
                due[kind] = clock()+interval
                try:
                    result = runner(collect_once,kind,
                        timeout=issuer_refresh.DEADLINE_SECONDS if kind == 'ISSUER' else DEADLINE_SECONDS,
                        start_method='spawn')
                    if kind == 'ISSUER' and isinstance(result,dict):
                        retry = result.get('retry_after_seconds')
                        if type(retry) is int and 60 <= retry <= 86400:
                            due[kind] = clock()+retry
                except Exception as exc:
                    # No dependency response or credential is emitted. Existing
                    # account freshness expires; no invented observation replaces it.
                    supervisor_io.report('execution collector unavailable: '+type(exc).__name__)
                    if kind != 'ISSUER':
                        try:
                            runner(record_stall,kind,type(exc).__name__,timeout=5,start_method='spawn')
                        except Exception:
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
