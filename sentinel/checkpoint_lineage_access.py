"""Separately authenticated checkpoint access path; never installed by reads."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import uuid

SCHEMA = 'sentinel.checkpoint-lineage-access/1'
CURSOR = 'checkpoint-lineage-access:v1'
INDEX = 'sentinel_checkpoint_lineage_suspects_idx'
ROW_TRIGGER = 'sentinel_checkpoint_lineage_installation_guard'
TRUNCATE_TRIGGER = 'sentinel_checkpoint_lineage_installation_no_truncate'
FUNCTION = 'sentinel_checkpoint_lineage_installation_guard'
NAME_PREDICATE = ("(cursor_name LIKE 'shadow-%' OR cursor_name LIKE 'rolling-%' "
                  "OR cursor_name LIKE 'catchup%')")
JSON_PREDICATE = (f'CASE WHEN {NAME_PREDICATE} THEN FALSE ELSE '
                  "state ?| ARRAY['wealth_core','strategy_identity'] END")
_EXCLUDED = ('cursor_name=ANY(%(allowed_names)s) OR cursor_name LIKE %(session_pattern)s '
             'OR cursor_name LIKE %(input_pattern)s OR cursor_name LIKE %(authority_pattern)s')
_ELIGIBLE = f'(CASE WHEN {_EXCLUDED} THEN FALSE ELSE TRUE END)'
_NAME_BRANCH = ('SELECT cursor_name FROM sentinel_processed_sessions WHERE '
                f"{NAME_PREDICATE.replace('%', '%%')} AND {_ELIGIBLE}")
_JSON_BRANCH = ('SELECT cursor_name FROM sentinel_processed_sessions WHERE '
                f"({JSON_PREDICATE.replace('%', '%%')}) AND {_ELIGIBLE}")
# The ordered witness keeps the sparse B-tree useful after writes. Bare LIMIT
# can favor an early-match JSON scan even when the healthy case has no match.
QUERY = (f'SELECT cursor_name FROM (({_NAME_BRANCH} LIMIT 1) UNION ALL '
         f'({_JSON_BRANCH} ORDER BY cursor_name LIMIT 1)) suspects LIMIT 1')
# Exact pre-index predecessor guard. Its CASE, including NULL behavior, is not
# weakened while the candidate's read-only preflight precedes migration.
ORIGINAL_QUERY = (
    'SELECT cursor_name FROM sentinel_processed_sessions WHERE CASE WHEN '
    'cursor_name=ANY(%s) OR cursor_name LIKE %s OR cursor_name LIKE %s OR cursor_name LIKE %s THEN FALSE ELSE '
    "(cursor_name LIKE 'shadow-%%' OR cursor_name LIKE 'rolling-%%' OR cursor_name LIKE 'catchup%%'"
    " OR state ? 'wealth_core' OR state ? 'strategy_identity') END LIMIT 1")
_BODY = """
BEGIN
    IF TG_OP='TRUNCATE' THEN
        RAISE EXCEPTION 'checkpoint lineage installation authority cannot be truncated';
    END IF;
    IF (TG_OP IN ('UPDATE','DELETE') AND OLD.cursor_name='checkpoint-lineage-access:v1')
       OR (TG_OP='UPDATE' AND NEW.cursor_name='checkpoint-lineage-access:v1') THEN
        RAISE EXCEPTION 'checkpoint lineage installation authority is immutable';
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END
"""

extension_tables = frozenset()
extension_index_pairs = frozenset({('sentinel_processed_sessions', INDEX)})
extension_functions = frozenset({FUNCTION})
extension_triggers = frozenset({('sentinel_processed_sessions', ROW_TRIGGER),
                                ('sentinel_processed_sessions', TRUNCATE_TRIGGER)})
DDL = (
    f'CREATE INDEX {INDEX} ON sentinel_processed_sessions(cursor_name) WHERE ({JSON_PREDICATE})',
    f'CREATE FUNCTION {FUNCTION}() RETURNS trigger LANGUAGE plpgsql AS $lineage${_BODY}$lineage$',
    f'CREATE TRIGGER {ROW_TRIGGER} BEFORE UPDATE OR DELETE ON sentinel_processed_sessions '
    f'FOR EACH ROW EXECUTE FUNCTION {FUNCTION}()',
    f'CREATE TRIGGER {TRUNCATE_TRIGGER} BEFORE TRUNCATE ON sentinel_processed_sessions '
    f'FOR EACH STATEMENT EXECUTE FUNCTION {FUNCTION}()',
)


class AccessPathRefused(RuntimeError):
    pass


def _require(condition, reason):
    if not condition:
        raise AccessPathRefused(reason)


def _contract():
    from sentinel.operational_catalog import canonical
    return hashlib.sha256(canonical(list(DDL))).hexdigest()


def _signature(value):
    from sentinel.feed.publication import _receipt_hmac
    return _receipt_hmac({'purpose': SCHEMA, 'installation': value})


def installation(conn, *, required=False):
    """Authenticate the independent marker and distinguish clean absence."""
    exists = conn.execute("SELECT to_regclass('public.sentinel_processed_sessions')").fetchone()[0]
    row = (conn.execute('SELECT session,state FROM sentinel_processed_sessions WHERE cursor_name=%s',
                        (CURSOR,)).fetchone() if exists is not None else None)
    if row is None:
        owned = conn.execute(
            'SELECT to_regclass(%s) IS NOT NULL OR EXISTS('
            'SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace '
            "WHERE n.nspname='public' AND p.proname=%s) OR EXISTS("
            'SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid '
            'JOIN pg_namespace n ON n.oid=c.relnamespace '
            "WHERE n.nspname='public' AND t.tgname=ANY(%s))",
            ('public.'+INDEX, FUNCTION, [ROW_TRIGGER, TRUNCATE_TRIGGER])).fetchone()[0]
        _require(not owned, 'CHECKPOINT_LINEAGE_ACCESS_MARKER_LOST_OR_ORPHANED')
        _require(not required, 'CHECKPOINT_LINEAGE_ACCESS_ABSENT')
        return None
    raw = row[1]
    _require(isinstance(raw, dict) and set(raw) == {'installation', 'hmac_sha256'},
             'CHECKPOINT_LINEAGE_ACCESS_MALFORMED')
    value = raw['installation']
    _require(isinstance(value, dict) and set(value) == {
        'schema', 'authority_effect', 'installation_id', 'at', 'system_identifier', 'contract_sha256'},
        'CHECKPOINT_LINEAGE_ACCESS_MALFORMED')
    _require(value['schema'] == SCHEMA and value['authority_effect'] == 'NONE'
             and value['contract_sha256'] == _contract(),
             'CHECKPOINT_LINEAGE_ACCESS_CONTRACT_CHANGED')
    try:
        instant = datetime.fromisoformat(value['at'])
        identifier = str(uuid.UUID(value['installation_id']))
    except (ValueError, TypeError, KeyError) as exc:
        raise AccessPathRefused('CHECKPOINT_LINEAGE_ACCESS_MALFORMED') from exc
    _require(instant.utcoffset() == timedelta(0) and str(row[0]) == instant.date().isoformat()
             and identifier == value['installation_id'], 'CHECKPOINT_LINEAGE_ACCESS_CLOCK_CHANGED')
    _require(hmac.compare_digest(str(raw['hmac_sha256']), _signature(value)),
             'CHECKPOINT_LINEAGE_ACCESS_AUTHENTICATION_FAILED')
    system = conn.execute('SELECT system_identifier::text FROM pg_control_system()').fetchone()[0]
    _require(value['system_identifier'] == str(system), 'CHECKPOINT_LINEAGE_ACCESS_DATABASE_CHANGED')
    from sentinel.operational_catalog import require_extension
    require_extension(conn, __name__)
    return value


def require_schema(conn, *, allow_absent=False):
    return installation(conn, required=not allow_absent) is not None


def find_foreign(conn, *, allowed_names, session_pattern, input_pattern, authority_pattern):
    """One statement snapshot; indexed negative discovery after exact validation."""
    if require_schema(conn, allow_absent=True):
        return conn.execute(QUERY, dict(allowed_names=allowed_names,
            session_pattern=session_pattern, input_pattern=input_pattern,
            authority_pattern=authority_pattern)).fetchone()
    return conn.execute(ORIGINAL_QUERY,
        (allowed_names, session_pattern, input_pattern, authority_pattern)).fetchone()


def install(conn):
    """Caller owns migration, financial-writer exclusion, quiescence and commit."""
    if require_schema(conn, allow_absent=True):
        return
    from sentinel.operational_ddl_handoff import transfer
    from sentinel.operational_catalog import canonical
    with transfer(conn, expected_advance=2, label='checkpoint lineage migration', refusal=AccessPathRefused):
        for statement in DDL:
            conn.execute(statement)
        at, system = conn.execute('SELECT clock_timestamp(),system_identifier::text '
                                  'FROM pg_control_system()').fetchone()
        at = at.astimezone(timezone.utc)
        value = dict(schema=SCHEMA, authority_effect='NONE', installation_id=str(uuid.uuid4()),
                     at=at.isoformat(), system_identifier=str(system), contract_sha256=_contract())
        conn.execute('INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES (%s,%s,%s::jsonb)',
                     (CURSOR, at.date(), canonical(dict(installation=value,
                       hmac_sha256=_signature(value))).decode('ascii')))
        require_schema(conn)
