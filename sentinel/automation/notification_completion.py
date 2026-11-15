"""Append-only completion of exact notification source rows."""

TABLE = 'sentinel_notification_completions'
FUNCTION = 'sentinel_notification_completions_immutable'
TRUNCATE = 'sentinel_notification_completions_no_truncate'
extension_tables = frozenset({TABLE})
extension_functions = frozenset({FUNCTION})
extension_triggers = frozenset({(TABLE, FUNCTION), (TABLE, TRUNCATE)})

DDL = (
    f"""CREATE TABLE {TABLE} (
        source text NOT NULL CHECK (source IN ('CYCLE','CONTROL')),
        seq bigint NOT NULL CHECK (seq > 0),
        relation_oid oid NOT NULL,
        file_oid oid NOT NULL,
        tuple_xmin text NOT NULL CHECK (tuple_xmin ~ '^[0-9]+$'),
        tuple_location tid NOT NULL,
        alert_key text REFERENCES sentinel_alert_outbox(idempotency_key),
        CHECK (source='CYCLE' OR alert_key IS NOT NULL),
        PRIMARY KEY (source,seq,relation_oid,file_oid,tuple_xmin,tuple_location))""",
    f"""CREATE FUNCTION {FUNCTION}() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'notification completions are append-only';
    END
    $$""",
    f'CREATE TRIGGER {FUNCTION} BEFORE UPDATE OR DELETE ON {TABLE} '
    f'FOR EACH ROW EXECUTE FUNCTION {FUNCTION}()',
    f'CREATE TRIGGER {TRUNCATE} BEFORE TRUNCATE ON {TABLE} '
    f'FOR EACH STATEMENT EXECUTE FUNCTION {FUNCTION}()',
)


def require_schema(conn, *, allow_absent=False):
    from sentinel.operational_catalog import OperationalCatalogRefused, require_extension

    if allow_absent:
        present, orphan = conn.execute(
            'SELECT to_regclass(%s) IS NOT NULL, to_regprocedure(%s) IS NOT NULL '
            'OR EXISTS(SELECT 1 FROM pg_trigger WHERE tgname=ANY(%s))',
            ('public.'+TABLE, 'public.'+FUNCTION+'()', [FUNCTION, TRUNCATE])).fetchone()
        if not present:
            if orphan:
                raise OperationalCatalogRefused('NOTIFICATION_COMPLETION_ORPHANED')
            return False
    return require_extension(conn, __name__)


def install(conn):
    """Caller holds the quiescent operational writer and migration transaction."""
    from sentinel.operational_catalog import OperationalCatalogRefused
    from sentinel.operational_ddl_handoff import transfer

    if require_schema(conn, allow_absent=True):
        return
    # PostgreSQL's CREATE TRIGGER records do not name a schema. The existing
    # public-schema epoch witness advances once for the table and once for
    # the function. The exact extension catalog checks both triggers.
    with transfer(conn, expected_advance=2, label='notification completion installation',
                  refusal=OperationalCatalogRefused):
        for statement in DDL:
            conn.execute(statement)
        require_schema(conn)
