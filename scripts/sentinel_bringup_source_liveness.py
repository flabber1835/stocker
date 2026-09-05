#!/usr/bin/env python3
"""Cheap read-only source/local-state liveness for non-authoritative bring-up.

This module deliberately does not perform the certified SEP CDC double-read,
TICKERS refresh, historical identity validation, corpus mutation, or recovery.
Those remain owned by the supported GO lifecycle.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Mapping, Optional

MARKER = "SENTINEL_BRINGUP_SOURCE_LIVENESS="

# Keep this probe intentionally small and bounded. It checks that the production
# database can be opened READ ONLY, that durable cursor rows are at least
# structurally sane, and that a tiny settled SPY SEP window can be read from the
# configured Sharadar source. It never asks for TICKERS and never runs the
# mutation/identity authority machinery.
_CODE = r'''
import datetime as dt
import hashlib
import json
import os

MARKER = 'SENTINEL_BRINGUP_SOURCE_LIVENESS='
state = {'phase': 'RUNTIME_IMPORT', 'emitted': False}


def emit(value):
    state['emitted'] = True
    print(MARKER + json.dumps(value, sort_keys=True), flush=True)


def controlled_detail(exc):
    raw = str(exc).strip()
    if not raw:
        return {}
    digest = hashlib.sha256(raw.encode('utf-8', errors='replace')).hexdigest()
    lowered = raw.lower()
    prohibited = ('http://', 'https://', 'api_key', 'api-key', 'password',
                  'authorization', 'postgres://', 'postgresql://', 'apca-api-')
    value = {'detail_sha256': digest}
    if any(item in lowered for item in prohibited) or '\n' in raw or '\r' in raw:
        return value
    if len(raw) > 420:
        raw = raw[:365] + ' ... [sha256:%s]' % digest[:16]
    value['detail'] = raw
    return value


def refuse(code, exc=None, **extra):
    value = {'status': 'REFUSED', 'reason_code': code}
    if exc is not None:
        value.update(controlled_detail(exc))
    value.update(extra)
    emit(value)


def parse_cursor(row, *, name, current_version):
    if row is None:
        return name + '_MISSING'
    session, raw = row
    if isinstance(raw, dict):
        state_value = raw
    else:
        try:
            state_value = json.loads(str(raw))
        except (TypeError, ValueError):
            return name + '_MALFORMED'
    required = {'kind', 'processed_through', 'publication_version'}
    if not isinstance(state_value, dict) or set(state_value) != required:
        return name + '_MALFORMED'
    try:
        through = dt.date.fromisoformat(str(state_value['processed_through']))
        row_date = session if isinstance(session, dt.date) else dt.date.fromisoformat(str(session))
        version = int(state_value['publication_version'])
    except (TypeError, ValueError):
        return name + '_MALFORMED'
    if row_date != through:
        return name + '_MALFORMED'
    if current_version is not None and version > current_version:
        return name + '_AHEAD_OF_PUBLICATION'
    return None


def execute():
    state['phase'] = 'RUNTIME_IMPORT'
    from sentinel.feed import calendar, maintenance_impl as maintenance, recent_reconciliation, sharadar, store
    from sentinel.shadow_runtime import publication_not_before

    c = None
    try:
        state['phase'] = 'DATABASE_CONNECT'
        c = store.connect(os.environ['SENTINEL_DATABASE_URL'])
        state['phase'] = 'READ_ONLY_TRANSACTION'
        with c.cursor() as cur:
            cur.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            cur.execute('SHOW transaction_read_only')
            if str(cur.fetchone()[0]).lower() not in {'on', 'true'}:
                raise RuntimeError('read-only transaction could not be established')
            cur.execute("SELECT to_regclass('public.sentinel_corpus_publications')")
            publication_table = cur.fetchone()[0]
            cur.execute("SELECT to_regclass('public.sentinel_processed_sessions')")
            cursor_table = cur.fetchone()[0]

        local_followup = []
        current_version = None
        if publication_table is None:
            local_followup.append('CORPUS_SCHEMA_NOT_INSTALLED')
        else:
            with c.cursor() as cur:
                cur.execute('SELECT max(version) FROM sentinel_corpus_publications')
                row = cur.fetchone()
            if row is None or row[0] is None:
                local_followup.append('CORPUS_PUBLICATION_MISSING')
            else:
                current_version = int(row[0])

        if cursor_table is None:
            local_followup.append('CURSOR_SCHEMA_NOT_INSTALLED')
        else:
            for name in (
                maintenance.SEP_CURSOR_NAME,
                maintenance.ACTIONS_CURSOR_NAME,
                recent_reconciliation.CURSOR_NAME,
            ):
                with c.cursor() as cur:
                    cur.execute(
                        'SELECT session,state FROM sentinel_processed_sessions WHERE cursor_name=%s',
                        (name,))
                    row = cur.fetchone()
                problem = parse_cursor(row, name=name, current_version=current_version)
                if problem is not None:
                    local_followup.append(problem)

        target_raw = calendar.latest_closed_session()
        target = dt.date.fromisoformat(str(target_raw))
        source_final = dt.datetime.now(dt.timezone.utc) >= publication_not_before(target_raw)

        # A small, settled, single-ticker window proves transport/protocol
        # liveness without doing CDC reconciliation or identity work.
        state['phase'] = 'SOURCE_LIVENESS'
        lo = target - dt.timedelta(days=14)
        rows = list(sharadar.fetch_table(
            sharadar.SEP,
            {'ticker': 'SPY', 'date.gte': lo.isoformat(), 'date.lte': target.isoformat()},
        ))
        if not rows:
            refuse('SHARADAR_LIVENESS_EMPTY')
        elif local_followup:
            emit({
                'status': 'RECOVERY_REQUIRED',
                'reason_code': 'LOCAL_DATA_PREPARATION_REQUIRED',
                'local_followup': sorted(set(local_followup)),
                'source_rows': len(rows),
            })
        elif not source_final:
            emit({
                'status': 'DEFERRED',
                'reason_code': 'SHARADAR_SOURCE_NOT_FINAL',
                'source_rows': len(rows),
            })
        else:
            emit({
                'status': 'PASS',
                'reason_code': 'SHARADAR_LIVENESS_OK',
                'source_rows': len(rows),
            })
    except Exception as exc:
        name = type(exc).__name__
        if state['phase'] == 'DATABASE_CONNECT':
            code = 'DATABASE_CONNECT_UNAVAILABLE'
        elif state['phase'] == 'READ_ONLY_TRANSACTION':
            code = 'DATABASE_READONLY_UNAVAILABLE'
        elif state['phase'] == 'SOURCE_LIVENESS':
            code = 'SHARADAR_LIVENESS_UNAVAILABLE'
        else:
            code = 'BRINGUP_LIVENESS_UNAVAILABLE'
        refuse(code, exc, error_type=name, failure_phase=state['phase'])
    finally:
        if c is not None:
            try:
                c.rollback()
            finally:
                c.close()


try:
    execute()
except BaseException as exc:
    if not state['emitted']:
        refuse('BRINGUP_LIVENESS_RUNTIME_FAILURE', exc,
               error_type=type(exc).__name__, failure_phase=state['phase'])
'''.strip()


def payload(completed) -> Optional[Mapping[str, object]]:
    matches = []
    for line in (completed.stdout or "").splitlines():
        if not line.startswith(MARKER):
            continue
        try:
            value = json.loads(line[len(MARKER):])
        except ValueError:
            return None
        if not isinstance(value, dict):
            return None
        matches.append(value)
    return matches[0] if len(matches) == 1 else None


def safe_detail(value: object) -> Optional[str]:
    detail = str(value or "").strip()
    if not detail:
        return None
    lowered = detail.lower()
    prohibited = (
        "http://", "https://", "api_key", "api-key", "password", "authorization",
        "postgres://", "postgresql://", "apca-api-",
    )
    if any(item in lowered for item in prohibited) or re.search(r"[\r\n\x00]", detail):
        return None
    if len(detail) <= 500:
        return detail
    digest = hashlib.sha256(detail.encode("utf-8", errors="replace")).hexdigest()[:16]
    return detail[:445] + " ... [sha256:%s]" % digest
