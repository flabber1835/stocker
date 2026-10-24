"""Explicit mutation tracking for bounded execution-evidence verification.

Installation is caller-owned. Runtime reads never install or repair this schema.
The change counter is transactional: rolled-back source writes leave no gaps.
"""
from __future__ import annotations

import hashlib
import json


class EvidenceSchemaRefused(RuntimeError):
    pass


extension_tables = frozenset({
    'sentinel_execution_evidence_heads', 'sentinel_execution_evidence_changes',
    'sentinel_execution_evidence_coverage',
})

_GUARD = """
BEGIN
    IF TG_OP = 'TRUNCATE' OR pg_trigger_depth() < 2 OR TG_OP <> 'INSERT'
       AND TG_TABLE_NAME = 'sentinel_execution_evidence_changes' THEN
        RAISE EXCEPTION 'execution evidence tracking is producer-owned and append-only';
    END IF;
    RETURN NEW;
END
""".strip()

_APPEND = """
DECLARE next_sequence bigint;
BEGIN
    IF pg_trigger_depth() < 1 THEN
        RAISE EXCEPTION 'execution evidence changes require a source trigger';
    END IF;
    UPDATE sentinel_execution_evidence_heads SET head_seq=head_seq+1,
        reset_generation=reset_generation + CASE WHEN operation_value='TRUNCATE' THEN 1 ELSE 0 END
        WHERE domain=domain_value RETURNING head_seq INTO next_sequence;
    IF NOT FOUND THEN RAISE EXCEPTION 'execution evidence head is absent'; END IF;
    INSERT INTO sentinel_execution_evidence_changes(domain,seq,source,evidence_key,operation,detail)
        VALUES(domain_value,next_sequence,source_value,key_value,operation_value,detail_value);
END
""".strip()

_OBSERVATION = """
DECLARE before_value jsonb; after_value jsonb; evidence_key text;
BEGIN
    IF TG_OP='TRUNCATE' THEN
        PERFORM sentinel_execution_evidence_append('OBSERVATION',TG_TABLE_NAME,'*','TRUNCATE','{}'::jsonb);
        RETURN NULL;
    END IF;
    before_value=CASE WHEN TG_OP='INSERT' THEN NULL ELSE to_jsonb(OLD) END;
    after_value=CASE WHEN TG_OP='DELETE' THEN NULL ELSE to_jsonb(NEW) END;
    IF TG_TABLE_NAME='sentinel_observations' THEN
        IF TG_OP='UPDATE' AND before_value-'runtime_state'=after_value-'runtime_state' THEN RETURN NEW; END IF;
        evidence_key=COALESCE(before_value->>'seq',after_value->>'seq');
    ELSIF TG_TABLE_NAME='sentinel_observation_provenance' THEN
        evidence_key=COALESCE(before_value->>'observation_seq',after_value->>'observation_seq');
    ELSIF TG_TABLE_NAME='sentinel_processed_sessions' THEN
        IF COALESCE(before_value->>'cursor_name','') NOT LIKE 'broker-observation:v4:%'
           AND COALESCE(after_value->>'cursor_name','') NOT LIKE 'broker-observation:v4:%' THEN
            RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
        END IF;
        evidence_key=COALESCE(before_value->>'cursor_name',after_value->>'cursor_name');
    ELSE evidence_key='*binding*';
    END IF;
    IF TG_OP='UPDATE' AND before_value=after_value THEN RETURN NEW; END IF;
    PERFORM sentinel_execution_evidence_append('OBSERVATION',TG_TABLE_NAME,evidence_key,TG_OP,'{}'::jsonb);
    RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END
""".strip()

extension_functions = {
    'sentinel_execution_evidence_tracking_guard': _GUARD,
    'sentinel_execution_evidence_append': _APPEND,
    'sentinel_execution_observation_changed': _OBSERVATION,
}
_SOURCES = ('sentinel_observations', 'sentinel_observation_provenance',
            'sentinel_processed_sessions', 'sentinel_account_binding')
extension_triggers = frozenset(
    [(table, 'sentinel_execution_observation_changed') for table in _SOURCES]
    + [(table, 'sentinel_execution_observation_truncated') for table in _SOURCES]
    + [(table, 'sentinel_execution_evidence_tracking_guard') for table in (
        'sentinel_execution_evidence_heads', 'sentinel_execution_evidence_changes')]
    + [(table, 'sentinel_execution_evidence_tracking_truncate_guard') for table in (
        'sentinel_execution_evidence_heads', 'sentinel_execution_evidence_changes')]
)

DDL = (
    """CREATE TABLE sentinel_execution_evidence_heads (
        domain text PRIMARY KEY CHECK(domain IN ('OBSERVATION','MIRROR')),
        incarnation uuid NOT NULL DEFAULT gen_random_uuid(),
        head_seq bigint NOT NULL DEFAULT 0 CHECK(head_seq>=0),
        reset_generation bigint NOT NULL DEFAULT 0 CHECK(reset_generation>=0))""",
    "INSERT INTO sentinel_execution_evidence_heads(domain) VALUES('OBSERVATION'),('MIRROR')",
    """CREATE TABLE sentinel_execution_evidence_changes (
        domain text NOT NULL REFERENCES sentinel_execution_evidence_heads(domain),
        seq bigint NOT NULL CHECK(seq>0), source text NOT NULL, evidence_key text NOT NULL,
        operation text NOT NULL CHECK(operation IN ('INSERT','UPDATE','DELETE','TRUNCATE')),
        detail jsonb NOT NULL, changed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        PRIMARY KEY(domain,seq))""",
    """CREATE TABLE sentinel_execution_evidence_coverage (
        domain text PRIMARY KEY REFERENCES sentinel_execution_evidence_heads(domain),
        payload jsonb NOT NULL, hmac_sha256 text NOT NULL CHECK(hmac_sha256 ~ '^[a-f0-9]{64}$'),
        updated_at timestamptz NOT NULL DEFAULT clock_timestamp())""",
    "CREATE FUNCTION sentinel_execution_evidence_tracking_guard() RETURNS trigger LANGUAGE plpgsql AS $$"+_GUARD+"$$",
    "CREATE FUNCTION sentinel_execution_evidence_append(domain_value text,source_value text,key_value text,operation_value text,detail_value jsonb) RETURNS void LANGUAGE plpgsql AS $$"+_APPEND+"$$",
    "CREATE FUNCTION sentinel_execution_observation_changed() RETURNS trigger LANGUAGE plpgsql AS $$"+_OBSERVATION+"$$",
    *tuple(
        f'CREATE TRIGGER sentinel_execution_observation_changed AFTER INSERT OR UPDATE OR DELETE ON {table} '
        'FOR EACH ROW EXECUTE FUNCTION sentinel_execution_observation_changed()'
        for table in _SOURCES),
    *tuple(
        f'CREATE TRIGGER sentinel_execution_observation_truncated AFTER TRUNCATE ON {table} '
        'FOR EACH STATEMENT EXECUTE FUNCTION sentinel_execution_observation_changed()'
        for table in _SOURCES),
    *tuple(
        f'CREATE TRIGGER sentinel_execution_evidence_tracking_guard BEFORE INSERT OR UPDATE OR DELETE ON {table} '
        'FOR EACH ROW EXECUTE FUNCTION sentinel_execution_evidence_tracking_guard()'
        for table in ('sentinel_execution_evidence_heads','sentinel_execution_evidence_changes')),
    *tuple(
        f'CREATE TRIGGER sentinel_execution_evidence_tracking_truncate_guard BEFORE TRUNCATE ON {table} '
        'FOR EACH STATEMENT EXECUTE FUNCTION sentinel_execution_evidence_tracking_guard()'
        for table in ('sentinel_execution_evidence_heads','sentinel_execution_evidence_changes')),
)
CONTRACT_SHA256 = hashlib.sha256(json.dumps(DDL,separators=(',',':')).encode()).hexdigest()

def require_schema(conn, *, allow_absent=False):
    """SELECT-only comparison with the independently qualified exact catalog."""
    from sentinel.operational_catalog import OperationalCatalogRefused, require_extension
    try:
        return require_extension(conn,__name__,allow_absent=allow_absent)
    except OperationalCatalogRefused as exc:
        raise EvidenceSchemaRefused(str(exc)) from exc


def install(conn):
    """Explicit migration inside the caller's transaction; never commits."""
    if require_schema(conn,allow_absent=True):
        return
    for statement in DDL:
        conn.execute(statement)
    require_schema(conn)
