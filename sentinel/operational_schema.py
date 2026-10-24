"""Explicit operational extension installation; runtime checks are read-only.

The original behavioral/feed catalogs remain independent witnesses. Only exact
validated extension objects are removed from their historical comparison view.
An immutable authenticated marker prevents lost projections from masquerading
as a never-migrated predecessor.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import importlib
import json
import uuid

SCHEMA = 'sentinel.operational-schema/1'
CURSOR = 'operational-schema:v1'
COMPONENTS = (
    'sentinel.execution.evidence_schema',
    'sentinel.mirror_schema',
    'sentinel.panel.operational_schema',
    'sentinel.feed.normalized_layout',
    'sentinel.feed.generation_admission',
    'sentinel.operational_ddl_epoch',
)
_LOCK = (1397706832, 1330660145)
_FUNCTION = 'sentinel_operational_installation_guard'
_TRIGGER = 'sentinel_operational_installation_guard'
_TRUNCATE_TRIGGER = 'sentinel_operational_installation_no_truncate'
_BODY = """
BEGIN
    IF TG_OP='TRUNCATE' THEN
        RAISE EXCEPTION 'operational installation authority cannot be truncated';
    END IF;
    IF (TG_OP IN ('UPDATE','DELETE') AND OLD.cursor_name='operational-schema:v1')
       OR (TG_OP='UPDATE' AND NEW.cursor_name='operational-schema:v1') THEN
        RAISE EXCEPTION 'operational installation authority is immutable';
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END
"""
DDL = (
    f'CREATE FUNCTION {_FUNCTION}() RETURNS trigger LANGUAGE plpgsql AS $operational${_BODY}$operational$',
    f'CREATE TRIGGER {_TRIGGER} BEFORE UPDATE OR DELETE ON sentinel_processed_sessions '
    f'FOR EACH ROW EXECUTE FUNCTION {_FUNCTION}()',
    f'CREATE TRIGGER {_TRUNCATE_TRIGGER} BEFORE TRUNCATE ON sentinel_processed_sessions '
    f'FOR EACH STATEMENT EXECUTE FUNCTION {_FUNCTION}()',
)


extension_tables = frozenset()
extension_triggers = frozenset({
    ('sentinel_processed_sessions', _TRIGGER),
    ('sentinel_processed_sessions', _TRUNCATE_TRIGGER),
})
extension_functions = frozenset({_FUNCTION})


class OperationalSchemaRefused(RuntimeError):
    """The operational extension is absent, partial, changed or unowned."""


def _require(value, reason):
    if not value:
        raise OperationalSchemaRefused(reason)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def components():
    return tuple(importlib.import_module(name) for name in COMPONENTS)


def contracts():
    return {module.__name__: hashlib.sha256(_canonical(list(module.DDL))).hexdigest()
            for module in (*components(), importlib.import_module(__name__))}


def _signature(value):
    from sentinel.feed.publication import _receipt_hmac
    return _receipt_hmac({'purpose': SCHEMA, 'installation': value})


def _function_contract(conn):
    # Pin WHEN predicates, signatures, security settings and full definitions,
    # rather than merely recognizing names and trigger event flags.
    from sentinel.operational_catalog import require_extension
    require_extension(conn, __name__)


def installation(conn, *, required=False):
    """Authenticate existing installation metadata without creating anything."""
    exists = conn.execute("SELECT to_regclass('public.sentinel_processed_sessions')").fetchone()[0]
    if exists is None:
        _require(not required, 'OPERATIONAL_INSTALLATION_ABSENT')
        return None
    row = conn.execute(
        'SELECT session,state FROM sentinel_processed_sessions WHERE cursor_name=%s',
        (CURSOR,)).fetchone()
    if row is None:
        authority = conn.execute(
            'SELECT to_regclass(%s) IS NOT NULL OR to_regprocedure(%s) IS NOT NULL OR EXISTS('
            'SELECT 1 FROM pg_trigger WHERE tgname=ANY(%s))',
            ('public.sentinel_operational_ddl_epoch', 'public.'+_FUNCTION+'()',
             [_TRIGGER,_TRUNCATE_TRIGGER])).fetchone()[0]
        _require(not authority, 'OPERATIONAL_INSTALLATION_MARKER_LOST')
        _require(not required, 'OPERATIONAL_INSTALLATION_ABSENT')
        return None
    raw = row[1]
    _require(isinstance(raw, dict) and set(raw) == {'installation', 'hmac_sha256'},
             'OPERATIONAL_INSTALLATION_MALFORMED')
    value = raw['installation']
    _require(isinstance(value, dict) and set(value) == {
        'schema', 'installation_id', 'at', 'system_identifier', 'contracts'},
        'OPERATIONAL_INSTALLATION_MALFORMED')
    _require(value['schema'] == SCHEMA and value['contracts'] == contracts(),
             'OPERATIONAL_INSTALLATION_CONTRACT_CHANGED')
    try:
        instant = datetime.fromisoformat(value['at'])
        installation_id = str(uuid.UUID(value['installation_id']))
    except (ValueError, TypeError, KeyError) as exc:
        raise OperationalSchemaRefused('OPERATIONAL_INSTALLATION_MALFORMED') from exc
    _require(instant.tzinfo is not None and str(row[0]) == instant.date().isoformat()
             and installation_id == value['installation_id'],
             'OPERATIONAL_INSTALLATION_CLOCK_CHANGED')
    _require(hmac.compare_digest(str(raw['hmac_sha256']), _signature(value)),
             'OPERATIONAL_INSTALLATION_AUTHENTICATION_FAILED')
    system = conn.execute('SELECT system_identifier::text FROM pg_control_system()').fetchone()[0]
    _require(str(system) == value['system_identifier'], 'OPERATIONAL_INSTALLATION_DATABASE_CHANGED')
    _function_contract(conn)
    return value


def require_schema(conn, *, allow_absent=False):
    """Require every exact component after the installation boundary exists."""
    value = installation(conn, required=not allow_absent)
    if value is None:
        return False
    for module in components():
        _require(module.require_schema(conn, allow_absent=False) is not False,
                 'OPERATIONAL_COMPONENT_ABSENT: '+module.__name__)
    return True


def legacy_catalog(conn, catalog):
    """Validated historical view; unknown objects and edits are never hidden."""
    relations, columns, constraints, indexes, triggers = catalog
    modules = components()
    names = lambda module: set(module.extension_tables) | set(getattr(module, 'extension_views', ()))
    present = any(names(module) & set(relations) for module in modules)
    marker_possible = 'sentinel_processed_sessions' in relations
    marker = installation(conn, required=False) if marker_possible else None
    if not present and marker is None:
        return catalog
    excluded_tables = set()
    excluded_triggers = {('sentinel_processed_sessions', _TRIGGER),
                         ('sentinel_processed_sessions', _TRUNCATE_TRIGGER)} if marker else set()
    for module in modules:
        active = bool(names(module) & set(relations))
        if marker or active:
            _require(module.require_schema(conn, allow_absent=False) is not False,
                     'OPERATIONAL_COMPONENT_ABSENT: '+module.__name__)
            excluded_tables.update(names(module))
            excluded_triggers.update(getattr(module, 'extension_trigger_pairs', module.extension_triggers))
    def without_extensions(mapping):
        return {name: value for name, value in mapping.items() if name not in excluded_tables}
    filtered_triggers = {
        name: {key: value for key, value in values.items() if (name, key) not in excluded_triggers}
        for name, values in triggers.items() if name not in excluded_tables}
    return (*(without_extensions(item) for item in (relations, columns, constraints, indexes)),
            filtered_triggers)


def require_idle_connection(conn):
    """A connection-owning operation cannot discard somebody else's work."""
    from psycopg.pq import TransactionStatus
    _require(conn.info.transaction_status == TransactionStatus.IDLE,
             'OPERATIONAL_OPERATION_REQUIRES_IDLE_CONNECTION')


@contextmanager
def migration_transaction(conn):
    """Own one explicit migration transaction; ordinary reads never enter it."""
    require_idle_connection(conn)
    try:
        conn.execute("SET LOCAL lock_timeout='2000ms'")
        conn.execute("SET LOCAL statement_timeout='120000ms'")
        row = conn.execute('SELECT pg_try_advisory_xact_lock(%s,%s)', _LOCK).fetchone()
        _require(row and row[0], 'OPERATIONAL_MIGRATION_ALREADY_OWNED')
        yield
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


@contextmanager
def _financial_writer(conn):
    # PostgreSQL transaction/session advisory requests for the same key conflict.
    # This owner does not enter writer_lock(), whose historical context manager
    # commits on exit: the migration transaction alone owns this commit boundary.
    from sentinel.execution.journal import WRITER_LOCK_KEY
    row = conn.execute('SELECT pg_try_advisory_xact_lock(%s)', (WRITER_LOCK_KEY,)).fetchone()
    _require(row and row[0], 'OPERATIONAL_MIGRATION_FINANCIAL_WRITER_BUSY')
    yield


def install_quiescent(conn):
    """Explicit additive extension install under the existing single writer.

    The delivery coordinator must first drain and stop application roles. This
    independent database boundary also refuses admitted financial/source work.
    Existing lease/control/book rows are preserved rather than reset.
    """
    with migration_transaction(conn):
        with _financial_writer(conn):
            current = installation(conn, required=False)
            if current is not None:
                require_schema(conn)
                return current
            uncertain = conn.execute(
                "SELECT COUNT(*) FROM sentinel_commands WHERE state IN "
                "('SEND_PENDING','UNKNOWN','ACKNOWLEDGED','PARTIALLY_FILLED','CANCEL_PENDING')"
            ).fetchone()[0]
            active_jobs = conn.execute(
                "SELECT COUNT(*) FROM sentinel_snapshot_jobs WHERE state NOT IN "
                "('PUBLISHED','REFUSED','ABORTED') AND reason<>'COMPARISON_ONLY'"
            ).fetchone()[0]
            active_cycles = conn.execute(
                "SELECT COUNT(*) FROM sentinel_automation_cycles WHERE state NOT IN "
                "('WAITING_OPEN','SUCCEEDED','MISSED_STATE_ONLY','SUPERSEDED','BLOCKED')"
            ).fetchone()[0]
            _require(not uncertain and not active_jobs and not active_cycles,
                     'OPERATIONAL_MIGRATION_REQUIRES_QUIESCENCE')
            for module in components():
                module.install(conn)
            for statement in DDL:
                conn.execute(statement)
            system = conn.execute('SELECT system_identifier::text FROM pg_control_system()').fetchone()[0]
            at = conn.execute('SELECT clock_timestamp()').fetchone()[0]
            value = {'schema': SCHEMA, 'installation_id': str(uuid.uuid4()),
                     'at': at.isoformat(), 'system_identifier': str(system),
                     'contracts': contracts()}
            conn.execute(
                'INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES (%s,%s,%s::jsonb)',
                (CURSOR, at.date(), _canonical({'installation': value,
                    'hmac_sha256': _signature(value)}).decode('ascii')))
            require_schema(conn)
            return value
