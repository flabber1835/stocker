"""Explicit cleanup of only extensions installed by named private PG fixtures."""
from psycopg import sql


def cleanup(conn):
    from sentinel import mirror_schema, operational_ddl_epoch
    from sentinel.execution import evidence_schema
    conn.rollback()
    for name in sorted(operational_ddl_epoch.extension_event_triggers):
        conn.execute(sql.SQL('DROP EVENT TRIGGER IF EXISTS {}').format(sql.Identifier(name)))
    for module in (operational_ddl_epoch,mirror_schema,evidence_schema):
        rows=conn.execute('SELECT p.proname,pg_get_function_identity_arguments(p.oid) '
            "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' "
            'AND p.proname=ANY(%s)',(sorted(module.extension_functions),)).fetchall()
        for name,arguments in rows:
            # Both function name and identity arguments come from this private
            # fixture's catalog; no production connection reaches this helper.
            conn.execute(sql.SQL('DROP FUNCTION public.{}({}) CASCADE').format(
                sql.Identifier(name),sql.SQL(arguments)))
    conn.commit()
