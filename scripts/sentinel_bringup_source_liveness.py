#!/usr/bin/env python3
"""Read-only inspection of the authenticated, locally published operational frontier."""
from __future__ import annotations

from pathlib import Path
import sys
from typing import Mapping, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sentinel_probe_output as probe_output

MARKER = "SENTINEL_BRINGUP_SOURCE_LIVENESS="

# Both operator commands inspect the same authenticated, locally published frontier.
_CODE = r'''
import hashlib
import json
import os
phase = 'RUNTIME_IMPORT_UNAVAILABLE'

def inspect():
    global phase
    from sentinel.feed import operational_snapshot, rolling_go_inputs, store
    phase = 'DATABASE_CONNECT_UNAVAILABLE'
    with store.connect(os.environ['SENTINEL_DATABASE_URL']) as conn:
        phase = 'DATABASE_READONLY_UNAVAILABLE'
        with conn.cursor() as cur:
            cur.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            cur.execute('SHOW transaction_read_only')
            if str(cur.fetchone()[0]).lower() != 'on':
                raise RuntimeError('read-only transaction required')
            cur.execute("SELECT to_regclass('public.sentinel_corpus_publications')")
            if cur.fetchone()[0] is None:
                return dict(status='RECOVERY_REQUIRED', reason_code='CORPUS_SCHEMA_NOT_INSTALLED')
        phase = 'ROLLING_PUBLICATION_UNVERIFIED'
        held = rolling_go_inputs.current(conn)
        if held is None or not rolling_go_inputs.is_rolling(held):
            return dict(status='RECOVERY_REQUIRED', reason_code='ROLLING_PUBLICATION_REQUIRED')
        operational_snapshot.require_alpaca_openfigi(conn, held)
        frontier = operational_snapshot.source_final_session()
        if held.window_end > frontier:
            raise RuntimeError('publication is ahead of its source-final frontier')
        if held.window_end < frontier:
            return dict(status='RECOVERY_REQUIRED', reason_code='ROLLING_PUBLICATION_BEHIND')
        return dict(status='PASS', reason_code='ROLLING_PUBLICATION_CURRENT')

try:
    result = inspect()
except Exception as exc:
    result = dict(status='REFUSED', reason_code=phase,
                  error_type=type(exc).__name__, detail_sha256=hashlib.sha256(str(exc).encode()).hexdigest())
print('SENTINEL_BRINGUP_SOURCE_LIVENESS=' + json.dumps(result, sort_keys=True), flush=True)
'''.strip()


def payload(completed) -> Optional[Mapping[str, object]]:
    return probe_output.payload(completed, marker=MARKER)


def safe_detail(value: object) -> Optional[str]:
    return probe_output.safe_detail(value)
