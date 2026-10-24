"""Owned read-only proofs of committed state, preserving borrowed work."""
from contextlib import contextmanager


@contextmanager
def proof_connection(conn):
    """Keep borrowed work intact; canonical status observes committed rows."""
    from psycopg.pq import TransactionStatus
    from sentinel.feed import readiness_scope
    borrowed = conn.info.transaction_status != TransactionStatus.IDLE
    with conn.transaction(force_rollback=True):
        pin = readiness_scope.capture(conn)
        statement_timeout = conn.execute('SHOW statement_timeout').fetchone()[0]
        lock_timeout = conn.execute('SHOW lock_timeout').fetchone()[0]
    borrowed = borrowed or pin is not None
    if borrowed:
        from sentinel.guarded_administration import fresh_connection_factory
        proof = fresh_connection_factory(conn)()
    else:
        proof = conn
    try:
        proof.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        if borrowed:
            proof.execute("SELECT set_config('statement_timeout',%s,true),set_config('lock_timeout',%s,true)",
                          (statement_timeout,lock_timeout))
        yield proof
        if pin is not None:
            with conn.transaction(force_rollback=True):
                readiness_scope.require_token(conn,pin)
    finally:
        try:
            proof.rollback()
        finally:
            if borrowed:
                proof.close()
