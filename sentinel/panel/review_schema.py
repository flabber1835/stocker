"""Explicit optional presentation schema; never installed by an HTTP read."""
from __future__ import annotations

STATE = 'sentinel_dashboard_review_state'
EVENTS = 'sentinel_dashboard_review_events'
extension_tables = frozenset({STATE, EVENTS})
_FUNCTION = 'sentinel_dashboard_review_history_guard'
_BODY = """
BEGIN
    RAISE EXCEPTION 'dashboard review history is append-only';
END
""".strip()
extension_functions = {_FUNCTION: _BODY}
extension_triggers = frozenset({(EVENTS, _FUNCTION), (EVENTS, _FUNCTION + '_truncate')})
DDL = (
    f"""CREATE TABLE {STATE} (
        scope_sha256 text PRIMARY KEY CHECK (scope_sha256 ~ '^[a-f0-9]{{64}}$'),
        payload jsonb NOT NULL CHECK (jsonb_typeof(payload)='object'),
        signature text NOT NULL CHECK (signature ~ '^[a-f0-9]{{64}}$'),
        updated_at timestamptz NOT NULL DEFAULT clock_timestamp())""",
    f"""CREATE TABLE {EVENTS} (
        scope_sha256 text NOT NULL REFERENCES {STATE}(scope_sha256),
        sequence bigint NOT NULL CHECK (sequence>0),
        event_key text NOT NULL CHECK (length(event_key) BETWEEN 1 AND 200),
        kind text NOT NULL CHECK (kind IN ('STARTED','FAILED','RECOVERED','REVIEW','ACKNOWLEDGED')),
        at timestamptz NOT NULL,
        payload jsonb NOT NULL CHECK (jsonb_typeof(payload)='object'),
        signature text NOT NULL CHECK (signature ~ '^[a-f0-9]{{64}}$'),
        PRIMARY KEY (scope_sha256,sequence), UNIQUE (scope_sha256,event_key))""",
    f'CREATE FUNCTION {_FUNCTION}() RETURNS trigger LANGUAGE plpgsql AS $$'+_BODY+'$$',
    f'CREATE TRIGGER {_FUNCTION} BEFORE UPDATE OR DELETE ON {EVENTS} '
    f'FOR EACH ROW EXECUTE FUNCTION {_FUNCTION}()',
    f'CREATE TRIGGER {_FUNCTION}_truncate BEFORE TRUNCATE ON {EVENTS} '
    f'FOR EACH STATEMENT EXECUTE FUNCTION {_FUNCTION}()',
)


def require_schema(conn, *, allow_absent=False):
    """Optional to trading; its absence can never establish dashboard green."""
    from sentinel.operational_catalog import OperationalCatalogRefused, require_extension
    present = conn.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relname=ANY(%s)", (sorted(extension_tables),)).fetchone()[0]
    if not present and allow_absent:
        orphan = conn.execute("SELECT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='public' AND p.proname=%s) OR EXISTS(SELECT 1 FROM pg_trigger "
            "WHERE tgname=ANY(%s))", (_FUNCTION, sorted(name for _, name in extension_triggers))).fetchone()[0]
        if orphan:
            raise OperationalCatalogRefused('DASHBOARD_REVIEW_ORPHANED')
        return False
    return require_extension(conn, __name__, allow_absent=False)


def install(conn):
    """Caller owns the fenced migration and commit; no financial data writes."""
    if require_schema(conn, allow_absent=True):
        return
    from sentinel import deployment_fence
    deployment_fence.require(conn)
    for statement in DDL:
        conn.execute(statement)
    require_schema(conn)


def install_quiescent(conn):
    """Explicit installation phase only; preserve the financial schema marker."""
    from sentinel import operational_schema, deployment_fence
    with operational_schema.migration_transaction(conn):
        with operational_schema._financial_writer(conn):
            deployment_fence.require(conn)
            row = conn.execute('SELECT enabled,kill_switch_engaged '
                               'FROM sentinel_automation_control WHERE id=1').fetchone()
            if row != (False, True):
                raise operational_schema.OperationalSchemaRefused('DASHBOARD_INSTALL_REQUIRES_FENCE')
            from sentinel.panel import review_migration
            review_migration.install(conn)
