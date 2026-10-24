"""Explicit operational projections; installation is caller-owned and quiescent.

Runtime validation is catalog-only. Revisions are invalidation facts, never
financial readiness. Separate rows keep PAPER changes out of shadow subjects.
"""
from __future__ import annotations

from sentinel.retained_input_namespaces import PAPER_CURSOR_NAMES, PAPER_CURSOR_PREFIXES

REVISION = 'sentinel_operational_read_revisions'
RECEIPTS = 'sentinel_operational_verification_receipts'
OWNER = 'sentinel_operational_verification_owner'
PRIORITY = 'sentinel_alert_delivery_priority'
extension_tables = frozenset({REVISION, RECEIPTS, OWNER, PRIORITY})

BOTH_DEPENDENCIES = (
    'sentinel_corpus_publications', 'sentinel_rollout_state',
    'sentinel_execution_plans',
)
PAPER_DEPENDENCIES = (
    'sentinel_account_binding', 'sentinel_observations', 'sentinel_commands',
    'sentinel_execution_authority_state', 'sentinel_signed_execution_certificates',
    'sentinel_execution_certificate_revocations', 'sentinel_execution_key_revocations',
    'sentinel_automation_cycle_events',
)
PROJECTED_PAPER_DEPENDENCIES = {
    'sentinel_automation_control': ('enabled','generation','kill_switch_engaged','deployment_id','broker',
        'broker_account_id','takeover_epoch','certificate_sha256','rollout_mode','rollout_version',
        'config_sha256','authority_verdict','authority_detail','enabled_at','disabled_at'),
    'sentinel_automation_cycles': ('cycle_id','state','decision_session','effective_session','deployment_id',
        'broker','broker_account_id','takeover_epoch','control_generation','certificate_sha256','rollout_mode',
        'rollout_version','config_sha256','decision_close_at','prepare_at','execution_open_at','execute_at',
        'execution_close_at','historical_state_only','plan_id','data_version','publication_fingerprint',
        'state_fingerprint','plan_fingerprint','last_clean_reconciliation_id','attempt_count','failure_code',
        'failure_detail','diagnostic','created_at','completed_at'),
    'sentinel_execution_certificate_lifecycle': ('certificate_sha256','status'),
}

_GUARD_BODY = """
BEGIN
    IF TG_OP <> 'UPDATE' OR pg_trigger_depth() < 2
       OR NEW.scope <> OLD.scope OR NEW.incarnation <> OLD.incarnation
       OR NEW.revision <> OLD.revision + 1 THEN
        RAISE EXCEPTION 'operational revision may only advance from its dependency trigger';
    END IF;
    RETURN NEW;
END
"""
_BUMP_BODY = """
BEGIN
    UPDATE public.sentinel_operational_read_revisions SET revision=revision+1
        WHERE scope='PAPER';
    IF NOT FOUND THEN RAISE EXCEPTION 'operational PAPER revision is missing'; END IF;
    IF TG_ARGV[0] = 'BOTH' THEN
        UPDATE public.sentinel_operational_read_revisions SET revision=revision+1
            WHERE scope='SHADOW';
    END IF;
    IF NOT FOUND THEN RAISE EXCEPTION 'operational revision state is missing'; END IF;
    RETURN NULL;
END
"""
_names = ','.join("'"+name.replace("'", "''")+"'" for name in sorted(PAPER_CURSOR_NAMES))
_prefixes = ','.join("'"+name.replace("'", "''")+"%'" for name in sorted(PAPER_CURSOR_PREFIXES))
_CURSOR_BODY = f"""
DECLARE shadow_changed boolean := false;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        shadow_changed := OLD.cursor_name <> ALL(ARRAY[{_names}]::text[])
            AND NOT (OLD.cursor_name LIKE ANY(ARRAY[{_prefixes}]::text[]));
    END IF;
    IF TG_OP <> 'DELETE' THEN
        shadow_changed := shadow_changed OR (NEW.cursor_name <> ALL(ARRAY[{_names}]::text[])
            AND NOT (NEW.cursor_name LIKE ANY(ARRAY[{_prefixes}]::text[])));
    END IF;
    UPDATE public.sentinel_operational_read_revisions SET revision=revision+1 WHERE scope='PAPER';
    IF NOT FOUND THEN RAISE EXCEPTION 'operational PAPER revision is missing'; END IF;
    IF shadow_changed THEN
        UPDATE public.sentinel_operational_read_revisions SET revision=revision+1 WHERE scope='SHADOW';
        IF NOT FOUND THEN RAISE EXCEPTION 'operational shadow revision is missing'; END IF;
    END IF;
    RETURN NULL;
END
"""
_PROJECTED_BODY = """
DECLARE field text; changed boolean := false;
BEGIN
    IF TG_OP='UPDATE' THEN
        FOREACH field IN ARRAY string_to_array(TG_ARGV[0],',') LOOP
            IF (to_jsonb(OLD)->field) IS DISTINCT FROM (to_jsonb(NEW)->field) THEN
                changed := true;
                EXIT;
            END IF;
        END LOOP;
        IF NOT changed THEN RETURN NULL; END IF;
    END IF;
    UPDATE public.sentinel_operational_read_revisions SET revision=revision+1 WHERE scope='PAPER';
    IF NOT FOUND THEN RAISE EXCEPTION 'operational PAPER revision is missing'; END IF;
    RETURN NULL;
END
"""
_ACCOUNT_BODY = """
DECLARE previous public.sentinel_broker_account_evidence%ROWTYPE;
BEGIN
    SELECT * INTO previous FROM public.sentinel_broker_account_evidence
        ORDER BY observed_at DESC,seq DESC LIMIT 1;
    IF FOUND AND NEW.observed_at>=previous.observed_at
       AND NEW.observed_at-previous.observed_at<=interval '10 minutes'
       AND (NEW.observed_at AT TIME ZONE 'America/New_York')::date
           =(previous.observed_at AT TIME ZONE 'America/New_York')::date
       AND (to_jsonb(NEW)-'seq'-'observed_at')
           IS NOT DISTINCT FROM (to_jsonb(previous)-'seq'-'observed_at') THEN
        RETURN NEW;
    END IF;
    UPDATE public.sentinel_operational_read_revisions SET revision=revision+1 WHERE scope='PAPER';
    IF NOT FOUND THEN RAISE EXCEPTION 'operational PAPER revision is missing'; END IF;
    RETURN NEW;
END
"""
_FUNCTIONS = {
    'sentinel_operational_revision_guard': _GUARD_BODY,
    'sentinel_operational_revision_bump': _BUMP_BODY,
    'sentinel_operational_cursor_bump': _CURSOR_BODY,
    'sentinel_operational_projected_paper_bump': _PROJECTED_BODY,
    'sentinel_operational_account_insert_bump': _ACCOUNT_BODY,
}
extension_functions = frozenset(_FUNCTIONS)
_TRIGGERS = {
    'sentinel_operational_revision_guard': (REVISION, 'sentinel_operational_revision_guard', 31, ()),
    'sentinel_operational_revision_truncate_guard': (REVISION, 'sentinel_operational_revision_guard', 34, ()),
    'sentinel_operational_cursor_revision': ('sentinel_processed_sessions', 'sentinel_operational_cursor_bump', 29, ()),
    'sentinel_operational_cursor_truncate': ('sentinel_processed_sessions', 'sentinel_operational_revision_bump', 32, ('BOTH',)),
    'op_read_broker_account_evidence': ('sentinel_broker_account_evidence', 'sentinel_operational_account_insert_bump', 7, ()),
    'op_mutation_broker_account_evidence': ('sentinel_broker_account_evidence', 'sentinel_operational_revision_bump', 56, ('PAPER',)),
}
for _table in BOTH_DEPENDENCIES + PAPER_DEPENDENCIES:
    _TRIGGERS['op_read_'+_table.removeprefix('sentinel_')] = (
        _table, 'sentinel_operational_revision_bump', 60,
        ('BOTH' if _table in BOTH_DEPENDENCIES else 'PAPER',))
for _table, _fields in PROJECTED_PAPER_DEPENDENCIES.items():
    _TRIGGERS['op_read_'+_table.removeprefix('sentinel_')] = (
        _table, 'sentinel_operational_projected_paper_bump', 29, (','.join(_fields),))
    _TRIGGERS['op_truncate_'+_table.removeprefix('sentinel_')] = (
        _table, 'sentinel_operational_revision_bump', 32, ('PAPER',))
extension_triggers = frozenset((value[0], name) for name, value in _TRIGGERS.items())

DDL = (
    f"CREATE TABLE {REVISION} (scope TEXT PRIMARY KEY, incarnation UUID NOT NULL, revision BIGINT NOT NULL CHECK (revision >= 0))",
    f"INSERT INTO {REVISION} VALUES ('SHADOW',gen_random_uuid(),0),('PAPER',gen_random_uuid(),0)",
    f"CREATE TABLE {RECEIPTS} (scope TEXT PRIMARY KEY, subject_sha256 TEXT NOT NULL, observed_at TIMESTAMPTZ NOT NULL, valid_until TIMESTAMPTZ NOT NULL, envelope JSONB NOT NULL, signature TEXT NOT NULL)",
    f"CREATE TABLE {OWNER} (id INTEGER PRIMARY KEY CHECK (id=1), owner_id UUID NOT NULL, expires_at TIMESTAMPTZ NOT NULL)",
    f"CREATE TABLE {PRIORITY} (id INTEGER PRIMARY KEY CHECK (id=1), critical_streak INTEGER NOT NULL CHECK (critical_streak >= 0 AND critical_streak <= 3))",
    f"INSERT INTO {PRIORITY} VALUES (1,0)",
    *(f"CREATE FUNCTION {name}() RETURNS trigger LANGUAGE plpgsql AS $operational${body}$operational$"
      for name, body in _FUNCTIONS.items()),
    f"CREATE TRIGGER sentinel_operational_revision_guard BEFORE INSERT OR UPDATE OR DELETE ON {REVISION} FOR EACH ROW EXECUTE FUNCTION sentinel_operational_revision_guard()",
    f"CREATE TRIGGER sentinel_operational_revision_truncate_guard BEFORE TRUNCATE ON {REVISION} FOR EACH STATEMENT EXECUTE FUNCTION sentinel_operational_revision_guard()",
    "CREATE TRIGGER sentinel_operational_cursor_revision AFTER INSERT OR UPDATE OR DELETE ON sentinel_processed_sessions FOR EACH ROW EXECUTE FUNCTION sentinel_operational_cursor_bump()",
    "CREATE TRIGGER sentinel_operational_cursor_truncate AFTER TRUNCATE ON sentinel_processed_sessions FOR EACH STATEMENT EXECUTE FUNCTION sentinel_operational_revision_bump('BOTH')",
    *(f"CREATE TRIGGER {name} AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION {function}('{args[0]}')"
      for name, (table, function, kind, args) in _TRIGGERS.items() if kind == 60),
    *(f"CREATE TRIGGER {name} BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION {function}()"
      for name, (table, function, kind, args) in _TRIGGERS.items() if kind == 7),
    *(f"CREATE TRIGGER {name} AFTER UPDATE OR DELETE OR TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION {function}('{args[0]}')"
      for name, (table, function, kind, args) in _TRIGGERS.items() if kind == 56),
    *(f"CREATE TRIGGER {name} AFTER INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION {function}('{args[0]}')"
      for name, (table, function, kind, args) in _TRIGGERS.items() if kind == 29 and name.startswith('op_read_')),
    *(f"CREATE TRIGGER {name} AFTER TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION {function}('{args[0]}')"
      for name, (table, function, kind, args) in _TRIGGERS.items() if name.startswith('op_truncate_')),
)

class OperationalReadSchemaRefused(ValueError):
    pass


def require_schema(conn, *, allow_absent=False):
    """Catalog-only exact pinned contract; partial installs cannot fall back."""
    from sentinel.operational_catalog import require_extension
    active = require_extension(conn, __name__, allow_absent=allow_absent)
    if not active:
        return False
    revisions = conn.execute(f"SELECT scope,revision FROM {REVISION} ORDER BY scope").fetchall()
    if ([r[0] for r in revisions] != ['PAPER','SHADOW']
            or any(type(r[1]) is not int or r[1] < 0 for r in revisions)):
        raise OperationalReadSchemaRefused('operational revision state missing or malformed')
    row = conn.execute(f'SELECT critical_streak FROM {PRIORITY} WHERE id=1').fetchone()
    if row is None or type(row[0]) is not int or not 0 <= row[0] <= 3:
        raise OperationalReadSchemaRefused('operational priority state missing or malformed')
    return True


def install(conn):
    """Explicit caller-owned transaction; never commits, rolls back or repairs."""
    if require_schema(conn, allow_absent=True):
        return
    for statement in DDL:
        conn.execute(statement)
    require_schema(conn)
