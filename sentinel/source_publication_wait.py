"""Finite proof of an owned atomic publisher; never financial readiness.

Call only after the caller has caught the typed CorpusLockUnavailable refusal.
This module performs one metadata query on its own read-only connection. It
does not inspect a portfolio or roll back the caller's financial transaction.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sentinel.feed import calendar, rolling_jobs, store
from sentinel.feed.publication import CORPUS_LOCK_KEY
from sentinel.feed.rolling_contract import digest


PROOF_SQL = """SELECT j.request,j.request_sha256,j.state,j.created_at,j.deadline,
    j.lease_until,a.xact_start,a.state,clock_timestamp()
    FROM sentinel_snapshot_jobs j
    JOIN sentinel_operational_snapshot_jobs o USING(job_id)
    JOIN sentinel_snapshot_workers w ON w.job_id=j.job_id AND w.owner=j.owner
    JOIN pg_stat_activity a ON a.backend_xid::text=j.xmax::text
        AND a.datid=(SELECT oid FROM pg_database WHERE datname=current_database())
    WHERE j.owner IS NOT NULL AND j.fence>0 AND j.xmax::text<>'0'
        AND EXISTS (SELECT 1 FROM pg_locks l WHERE l.pid=a.pid
            AND l.locktype='advisory' AND l.granted AND l.mode='ExclusiveLock'
            AND l.objsubid=1 AND ((l.classid::bigint << 32)|l.objid::bigint)=%s)
    ORDER BY j.created_at DESC LIMIT 2"""


@dataclass(frozen=True)
class PublicationWaitProof:
    decision_session: str
    deadline: datetime
    publisher_deadline: datetime
    observed_at: datetime


def deadline_from_record(record, *, now):
    """Validate the original immutable request and writer admission clocks.

    A committed lease can look old while this exact atomic transaction holds
    the corpus lock. Its original job deadline and following open still bind.
    """
    try:
        raw, sha, state, created, deadline, lease_until, started, backend_state, sampled = record
        if (state not in {'ACQUIRING', 'STAGING', 'VALIDATING', 'READY'}
                or backend_state not in {'active', 'idle in transaction'}
                or any(not isinstance(value, datetime) or value.utcoffset() is None
                       for value in (created, deadline, lease_until, started, sampled, now))
                or abs((sampled - now).total_seconds()) > 5
                or not created <= started <= lease_until <= deadline
                or not created <= sampled < deadline or digest(raw) != sha):
            return None
        request = rolling_jobs.PreparationRequest.model_validate(raw)
        decision = str(request.window.end)
        if (decision != calendar.latest_closed_session(now)
                or created < calendar.session_window(decision)[1]):
            return None
        return min(deadline, calendar.session_window(calendar.next_session(decision))[0]) - timedelta(microseconds=1)
    except (AttributeError, TypeError, ValueError):
        return None


def observe(database_url, *, decision_session=None, now=None):
    """Return a current proof or None; unreadable proof preserves the refusal.

    The caller retains the exact exception-type gate. A fresh owned connection
    avoids touching a possibly aborted or financially dirty caller connection.
    """
    conn, result = None, None
    try:
        conn = store.connect(database_url, connect_timeout=3, statement_timeout_ms=3000)
        conn.execute('BEGIN TRANSACTION READ ONLY')
        records = conn.execute(PROOF_SQL, (CORPUS_LOCK_KEY,)).fetchall()
        sampled_now = datetime.now(timezone.utc) if now is None else now
        if len(records) == 1:
            deadline = deadline_from_record(records[0], now=sampled_now)
            if deadline is not None and deadline > sampled_now:
                decision = str(rolling_jobs.PreparationRequest.model_validate(records[0][0]).window.end)
                if decision_session is None or decision == str(decision_session):
                    result = PublicationWaitProof(
                        decision_session=decision, deadline=deadline,
                        publisher_deadline=records[0][4], observed_at=sampled_now)
    except Exception:
        # This is optional explanatory evidence. Failure must never relabel the
        # original typed refusal or grant a quieter availability classification.
        result = None
    finally:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                result = None
            try:
                conn.close()
            except Exception:
                result = None
    return result
