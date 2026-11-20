"""Fenced, transaction-owned transfer across the released acquisition guard upgrade."""
from sentinel import coverage_recovery_catalog as catalog, deployment_fence, operational_ddl_handoff
from sentinel import operational_schema
from sentinel.chain_progress_recovery import RecoveryRefused
from sentinel.execution import evidence_projection as coverage, evidence_schema
from sentinel.feed import runtime_schema


def require_predecessor(conn):
    try:
        catalog.require(conn, expected=catalog.POST_COMPACTION)
    except RecoveryRefused as exc:
        raise runtime_schema._refuse(str(exc)) from exc
    existing = conn.execute(
        "SELECT 1 FROM unnest(%s::text[]) AS t(name) WHERE to_regprocedure('public.'||name) IS NOT NULL",
        (list(catalog.ACQUISITION_FUNCTIONS),)).fetchone()
    if existing:
        raise runtime_schema._refuse('unexpected acquisition function on predecessor')


def require_successor(conn):
    try:
        catalog.require(conn, expected=catalog.ACQUISITION_UPGRADE)
    except RecoveryRefused as exc:
        raise runtime_schema._refuse(str(exc)) from exc


def _apply_guard_ddl(conn):
    signatures = (*catalog.ACQUISITION_FUNCTIONS, 'sentinel_acquisition_delete_guard()',
                  'sentinel_acquisition_price_delete_guard()')
    prefixes = tuple('CREATE OR REPLACE FUNCTION '+name for name in signatures)
    trigger = 'CREATE TRIGGER acquisition_binding_insert_guard '
    for statement in runtime_schema.DDL:
        if statement.startswith((*prefixes, trigger)):
            conn.execute(statement)


def migrate_if_protected(conn):
    """Caller holds financial and feed writer locks and owns commit/rollback."""
    operational = operational_schema.require_schema(conn, allow_absent=True)
    if not operational:
        if evidence_schema.require_schema(conn, allow_absent=True):
            raise runtime_schema._refuse('execution tracking has no authenticated installation')
        binding_table = conn.execute("SELECT to_regclass('public.sentinel_account_binding')").fetchone()[0]
        if binding_table is None or coverage.binding(conn) is None:
            return False
    try:
        require_successor(conn)
    except runtime_schema.FeedSchemaRefused:
        pass
    else:
        if operational:
            for domain in operational_ddl_handoff.DOMAINS:
                coverage.load(conn, domain)
        return True
    conn.execute('LOCK TABLE public.sentinel_automation_control, public.sentinel_automation_lease IN SHARE MODE')
    deployment_fence.require(conn)
    # PostgreSQL attributes four function definitions to public. Creating the
    # trigger has no schema_name in pg_event_trigger_ddl_commands().
    with operational_ddl_handoff.transfer(conn, expected_advance=4, label='acquisition guards',
            refusal=runtime_schema.FeedSchemaRefused):
        require_predecessor(conn)
        _apply_guard_ddl(conn)
        require_successor(conn)
    return True
