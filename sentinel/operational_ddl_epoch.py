"""Independent durable DDL witness for authenticated operational projections.

Install this component last, while application writers are quiescent. A completed
disable/change/enable of a source trigger changes the witness even when the final
catalog is identical. Runtime validation only reads the exact pinned catalog.
Arbitrary privileged bypass of both this audit and the source guards is outside
the supported database writer contract.
"""
from __future__ import annotations

import hashlib
import json


extension_tables = frozenset({'sentinel_operational_ddl_epoch'})
extension_event_triggers = frozenset({'sentinel_operational_evidence_ddl_changed'})
extension_triggers = frozenset({
    ('sentinel_operational_ddl_epoch', 'sentinel_operational_ddl_epoch_guard'),
    ('sentinel_operational_ddl_epoch', 'sentinel_operational_ddl_epoch_no_truncate'),
})

_GUARD = """
BEGIN
    IF TG_OP<>'UPDATE' THEN
        RAISE EXCEPTION 'operational DDL epoch is audit-owned and cannot be reset';
    END IF;
    -- PostgreSQL refuses this call outside an event-trigger execution context.
    -- Nested row triggers retain that context; pg_trigger_depth alone would not
    -- distinguish a direct client UPDATE from an independently observed DDL.
    PERFORM 1 FROM pg_event_trigger_ddl_commands();
    IF NEW.id<>OLD.id OR NEW.incarnation<>OLD.incarnation OR NEW.epoch<>OLD.epoch+1 THEN
        RAISE EXCEPTION 'operational DDL epoch must advance exactly once';
    END IF;
    RETURN NEW;
END
""".strip()

_CHANGED = """
BEGIN
    -- Conservatively invalidate on every public-schema DDL command. This also
    -- covers ALTER TABLE ... DISABLE/ENABLE TRIGGER and function replacement.
    IF EXISTS(SELECT 1 FROM pg_event_trigger_ddl_commands() WHERE schema_name='public') THEN
        UPDATE public.sentinel_operational_ddl_epoch SET epoch=epoch+1 WHERE id=1;
        IF NOT FOUND THEN RAISE EXCEPTION 'operational DDL epoch is absent'; END IF;
    END IF;
END
""".strip()

extension_functions = {
    'sentinel_operational_ddl_epoch_guard': _GUARD,
    'sentinel_operational_evidence_ddl_changed': _CHANGED,
}
DDL = (
    """CREATE TABLE sentinel_operational_ddl_epoch (
        id integer PRIMARY KEY CHECK(id=1),
        incarnation uuid NOT NULL DEFAULT gen_random_uuid(),
        epoch bigint NOT NULL DEFAULT 0 CHECK(epoch>=0))""",
    'INSERT INTO sentinel_operational_ddl_epoch(id) VALUES(1)',
    'CREATE FUNCTION sentinel_operational_ddl_epoch_guard() RETURNS trigger LANGUAGE plpgsql AS $$'+_GUARD+'$$',
    'CREATE FUNCTION sentinel_operational_evidence_ddl_changed() RETURNS event_trigger LANGUAGE plpgsql AS $$'+_CHANGED+'$$',
    'CREATE TRIGGER sentinel_operational_ddl_epoch_guard BEFORE INSERT OR UPDATE OR DELETE '
    'ON sentinel_operational_ddl_epoch FOR EACH ROW EXECUTE FUNCTION sentinel_operational_ddl_epoch_guard()',
    'CREATE TRIGGER sentinel_operational_ddl_epoch_no_truncate BEFORE TRUNCATE '
    'ON sentinel_operational_ddl_epoch FOR EACH STATEMENT EXECUTE FUNCTION sentinel_operational_ddl_epoch_guard()',
    'CREATE EVENT TRIGGER sentinel_operational_evidence_ddl_changed ON ddl_command_end '
    'EXECUTE FUNCTION sentinel_operational_evidence_ddl_changed()',
)
CONTRACT_SHA256 = hashlib.sha256(json.dumps(DDL,separators=(',',':')).encode()).hexdigest()


def require_schema(conn, *, allow_absent=False):
    from sentinel.operational_catalog import require_extension
    return require_extension(conn,__name__,allow_absent=allow_absent)


def install(conn):
    """Caller-owned explicit installation; no commit, rollback or auto-repair."""
    if require_schema(conn,allow_absent=True):
        return
    for statement in DDL:
        conn.execute(statement)
    require_schema(conn)


def current(conn):
    """Return the exact independent witness after validating its live guards."""
    require_schema(conn)
    row=conn.execute('SELECT incarnation::text,epoch FROM sentinel_operational_ddl_epoch WHERE id=1').fetchone()
    if row is None:
        from sentinel.operational_catalog import OperationalCatalogRefused
        raise OperationalCatalogRefused('OPERATIONAL_DDL_EPOCH_ABSENT')
    return str(row[0]),int(row[1])
