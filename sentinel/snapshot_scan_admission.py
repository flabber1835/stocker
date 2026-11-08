"""Database-local resource admission; no shared financial or readiness proof."""
from contextlib import contextmanager

# Distinct from corpus publication and account/strategy ownership namespaces.
LOCK_KEY = 0x534E545343414E31
WAIT_SECONDS = 120


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
