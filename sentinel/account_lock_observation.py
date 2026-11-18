"""Best-effort snapshot of actual PostgreSQL blockers of an account publication."""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import Future
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sentinel import supervisor_io


class LockSample(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    observed_at: datetime
    waiter: Literal['ACCOUNT_EVIDENCE_INSERT']
    blocker_count: int = Field(ge=1, strict=True)
    blocker_state: Literal['ACTIVE', 'IDLE_IN_TRANSACTION', 'UNATTRIBUTED']
    blocker_last_statement: Literal['REVISION_ROW_LOCK', 'PROCESSED_SESSION_WRITE',
                                    'ACCOUNT_EVIDENCE_INSERT', 'UNATTRIBUTED']


# Classify inside PostgreSQL. The process never fetches query text, grant
# details, backend IDs, parameters or any connection's application name.
_SAMPLE = r"""
WITH waiter AS (
  SELECT pg_catalog.pg_blocking_pids(pid) AS blockers
  FROM pg_catalog.pg_stat_activity
  WHERE pid=%s AND datname=current_database() AND usename=current_user
    AND backend_start <= %s AND wait_event_type='Lock'
    AND query ~* '^\s*INSERT INTO sentinel_broker_account_evidence\s'
), observed AS (
  SELECT DISTINCT blocker FROM waiter, unnest(blockers) AS blocker
)
SELECT clock_timestamp(), count(*),
  CASE WHEN count(*)=1 THEN max(CASE a.state WHEN 'active' THEN 'ACTIVE'
      WHEN 'idle in transaction' THEN 'IDLE_IN_TRANSACTION' END) END,
  CASE WHEN count(*)=1 THEN max(CASE
      WHEN a.query ~* '^\s*SELECT (1|revision) FROM sentinel_operational_read_revisions WHERE .* FOR UPDATE'
        THEN 'REVISION_ROW_LOCK'
      WHEN a.query ~* '^\s*(INSERT INTO|UPDATE) sentinel_processed_sessions\s'
        THEN 'PROCESSED_SESSION_WRITE'
      WHEN a.query ~* '^\s*INSERT INTO sentinel_broker_account_evidence\s'
        THEN 'ACCOUNT_EVIDENCE_INSERT' END) END
FROM observed LEFT JOIN pg_catalog.pg_stat_activity a
  ON a.pid=observed.blocker AND a.datname=current_database() AND a.usename=current_user
HAVING count(*)>0
"""


def start(conn, *, observed_at):
    """Return a future that is only ever inspected if already complete."""
    import psycopg

    result = Future()
    dsn, password, backend = conn.info.dsn, conn.info.password, conn.info.backend_pid

    def read():
        sample = None
        try:
            deadline = time.monotonic() + 2
            with psycopg.connect(dsn, password=password or None, connect_timeout=2, autocommit=True,
                    options='-c default_transaction_read_only=on -c statement_timeout=250') as observer:
                while time.monotonic() < deadline:
                    row = observer.execute(_SAMPLE, (backend, observed_at)).fetchone()
                    if row:
                        stamp, count, state, statement = row
                        sample = LockSample(observed_at=stamp, waiter='ACCOUNT_EVIDENCE_INSERT',
                            blocker_count=count, blocker_state=state or 'UNATTRIBUTED',
                            blocker_last_statement=statement or 'UNATTRIBUTED')
                        break
                    time.sleep(.05)
        except Exception:
            pass  # Diagnostic visibility cannot grant, revoke or delay publication.
        result.set_result(sample)
        if sample is not None:
            supervisor_io._pipe_report(json.dumps(dict(schema='sentinel.account-lock-observation/1',
                **sample.model_dump(mode='json')), separators=(',', ':')))

    threading.Thread(target=read, name='account-lock-observer', daemon=True).start()
    return result
