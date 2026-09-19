"""Reviewed PostgreSQL availability states shared by broker-free workers."""


def database_unavailable(exc: BaseException) -> bool:
    sqlstate = str(getattr(exc, 'sqlstate', '') or '')
    if sqlstate:
        return (sqlstate.startswith(('08', '40', '53'))
                or sqlstate in {'55P03', '57014', '57P01', '57P02', '57P03'})
    return (type(exc).__module__.startswith(('psycopg', 'psycopg2'))
            and type(exc).__name__ in {'OperationalError', 'InterfaceError'})
