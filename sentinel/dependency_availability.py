"""Reviewed PostgreSQL availability states shared by broker-free workers."""


def local_contention(exc: BaseException) -> bool:
    """Only failed lock acquisitions, never missing ownership or integrity."""
    from sentinel.execution.journal import WriterLockUnavailable
    from sentinel.feed.publication import CorpusLockUnavailable
    return isinstance(exc, (WriterLockUnavailable, CorpusLockUnavailable))


def database_unavailable(exc: BaseException) -> bool:
    sqlstate = str(getattr(exc, 'sqlstate', '') or '')
    if sqlstate:
        return (sqlstate.startswith(('08', '40', '53'))
                or sqlstate in {'55P03', '57014', '57P01', '57P02', '57P03'})
    from psycopg import InterfaceError, OperationalError
    return isinstance(exc, (OperationalError, InterfaceError)) or (
        type(exc).__module__.startswith('psycopg2')
        and type(exc).__name__ in {'OperationalError', 'InterfaceError'})
