"""Database-local resource admission; no shared financial or readiness proof."""
from contextlib import contextmanager

# Distinct from corpus publication and account/strategy ownership namespaces.
LOCK_KEY = 0x534E545343414E31
WAIT_SECONDS = 120


def occupied(conn):
    """A current native resource holder/waiter, solely for discretionary reads."""
    from sentinel.execution.journal import WRITER_LOCK_KEY
    return conn.execute("""
        SELECT EXISTS (SELECT FROM pg_catalog.pg_locks
            WHERE locktype='advisory' AND mode='ExclusiveLock' AND objsubid=1
              AND database=(SELECT oid FROM pg_catalog.pg_database WHERE datname=current_database())
              AND pid<>pg_backend_pid()
              AND ((classid=%s AND objid=%s) OR (granted AND classid=0 AND objid=%s)))
        """, (LOCK_KEY >> 32, LOCK_KEY & 0xffffffff, WRITER_LOCK_KEY)).fetchone()[0]


@contextmanager
def admitted(conn, *, wait_seconds=WAIT_SECONDS):
    """The caller owns this idle proof connection, never a borrowed transaction."""
    from psycopg.pq import TransactionStatus
    if conn.info.transaction_status != TransactionStatus.IDLE:
        raise ValueError('snapshot admission requires an owned idle connection')
    if not isinstance(wait_seconds, (int, float)) or not 0 < wait_seconds <= WAIT_SECONDS:
        raise ValueError('snapshot admission wait bound invalid')
    acquired = False
    failed = False
    try:
        # The native wait consumes the unchanged outer worker deadline. These
        # settings apply only to admission, not to any subsequent data query.
        millis = str(max(1, int(wait_seconds*1000)))+'ms'
        conn.execute("SELECT set_config('statement_timeout',%s,true),"
                     "set_config('lock_timeout',%s,true)", (millis, millis))
        conn.execute('SELECT pg_advisory_lock(%s)', (LOCK_KEY,)).fetchone()
        acquired = True
        # Session admission survives; timeout settings and the pre-wait snapshot
        # do not. The actual proof starts its fresh MVCC snapshot afterwards.
        conn.rollback()
        yield
    except BaseException:
        failed = True
        raise
    finally:
        try:
            conn.rollback()
            if acquired:
                row = conn.execute('SELECT pg_advisory_unlock(%s)', (LOCK_KEY,)).fetchone()
                if row != (True,):
                    raise ValueError('snapshot admission ownership lost')
                conn.rollback()
        except Exception:
            # A dead backend releases session locks itself. Preserve the actual
            # proof failure; cleanup may never turn a successful proof positive.
            if not failed:
                raise
