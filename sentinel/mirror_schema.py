"""Explicit indexed correction dependencies for the informational PAPER mirror."""
from __future__ import annotations

import hashlib
import json

from sentinel.execution import evidence_schema

extension_tables=frozenset({'sentinel_paper_mirror_dependencies'})
source_tables=frozenset({
    'sentinel_actions','sentinel_action_observations','sentinel_bars',
    'sentinel_bar_split_repairs','sentinel_defensive_bars','sentinel_corpus_anomalies',
    'sentinel_corpus_publications','feed_ingest_runs','sentinel_processed_sessions',
    'sentinel_execution_plans','sentinel_action_history','sentinel_action_coverage',
})

_CHANGED="""
DECLARE before_value jsonb; after_value jsonb; coordinates jsonb; plan_key text;
BEGIN
    IF TG_OP='TRUNCATE' THEN
        PERFORM sentinel_execution_evidence_append('MIRROR',TG_TABLE_NAME,'*','TRUNCATE','{}'::jsonb);
        RETURN NULL;
    END IF;
    before_value=CASE WHEN TG_OP='INSERT' THEN NULL ELSE to_jsonb(OLD) END;
    after_value=CASE WHEN TG_OP='DELETE' THEN NULL ELSE to_jsonb(NEW) END;
    IF TG_OP='UPDATE' AND before_value=after_value THEN RETURN NEW; END IF;
    IF TG_TABLE_NAME='sentinel_processed_sessions' THEN
        IF COALESCE(before_value->>'cursor_name','') NOT LIKE 'informational-paper-mirror:v1:%'
           AND COALESCE(after_value->>'cursor_name','') NOT LIKE 'informational-paper-mirror:v1:%' THEN
            RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
        END IF;
        plan_key=COALESCE(before_value->>'cursor_name',after_value->>'cursor_name');
        coordinates=jsonb_build_object('kind','legacy');
    ELSIF TG_TABLE_NAME='sentinel_paper_mirror_dependencies' THEN
        plan_key=COALESCE(before_value->>'plan_id',after_value->>'plan_id');
        coordinates=jsonb_build_object('kind','projection');
    ELSIF TG_TABLE_NAME='sentinel_execution_plans' THEN
        plan_key=COALESCE(before_value->>'plan_id',after_value->>'plan_id');
        IF TG_OP='UPDATE' AND before_value-'superseded_by'=after_value-'superseded_by' THEN RETURN NEW; END IF;
        IF NOT EXISTS(SELECT 1 FROM sentinel_paper_mirror_dependencies WHERE plan_id=plan_key) THEN
            RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
        END IF;
        coordinates=jsonb_build_object('kind','plan');
    ELSIF TG_TABLE_NAME='sentinel_corpus_publications' THEN
        plan_key=COALESCE(before_value->>'version',after_value->>'version');
        coordinates=jsonb_build_object('kind','publication','before',before_value,'after',after_value);
    ELSIF TG_TABLE_NAME='sentinel_action_history' THEN
        plan_key=COALESCE(before_value->>'session',after_value->>'session');
        coordinates=jsonb_build_object('kind','retained_history','session',plan_key);
    ELSIF TG_TABLE_NAME='sentinel_action_coverage' THEN
        plan_key=COALESCE(before_value->>'publication_version',after_value->>'publication_version');
        coordinates=jsonb_build_object('kind','retained_coverage','publication_version',plan_key);
    ELSIF TG_TABLE_NAME='feed_ingest_runs' THEN
        plan_key=COALESCE(before_value->>'run_id',after_value->>'run_id');
        IF NOT EXISTS(SELECT 1 FROM sentinel_corpus_publications WHERE run_id::text=plan_key)
           OR TG_OP='UPDATE' AND before_value->>'status'=after_value->>'status' THEN
            RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
        END IF;
        coordinates=jsonb_build_object('kind','unknown');
    ELSE
        IF TG_TABLE_NAME='sentinel_bars' AND TG_OP='UPDATE'
           AND before_value->'split_ratio'=after_value->'split_ratio'
           AND before_value->'security_id'=after_value->'security_id'
           AND before_value->'ticker'=after_value->'ticker'
           AND before_value->'session'=after_value->'session'
           AND before_value->'last_written_run_id'=after_value->'last_written_run_id' THEN RETURN NEW; END IF;
        coordinates=jsonb_build_object('kind','coordinate',
            'before',CASE WHEN before_value IS NULL THEN NULL ELSE jsonb_build_object(
                'security_id',before_value->>'security_id','ticker',before_value->>'ticker',
                'contraticker',before_value->>'contraticker','session',before_value->>'session',
                'run_id',before_value->>'last_written_run_id') END,
            'after',CASE WHEN after_value IS NULL THEN NULL ELSE jsonb_build_object(
                'security_id',after_value->>'security_id','ticker',after_value->>'ticker',
                'contraticker',after_value->>'contraticker','session',after_value->>'session',
                'run_id',after_value->>'last_written_run_id') END);
        plan_key='coordinate';
        IF NOT EXISTS(SELECT 1 FROM sentinel_paper_mirror_dependencies d WHERE
            (COALESCE(before_value->>'security_id','')=ANY(d.security_ids)
             OR COALESCE(after_value->>'security_id','')=ANY(d.security_ids)
             OR upper(COALESCE(before_value->>'ticker',''))=ANY(d.symbols)
             OR upper(COALESCE(after_value->>'ticker',''))=ANY(d.symbols)
             OR upper(COALESCE(before_value->>'contraticker',''))=ANY(d.symbols)
             OR upper(COALESCE(after_value->>'contraticker',''))=ANY(d.symbols))
            AND (((before_value->>'session')::date<=d.effective_session
                  AND (TG_TABLE_NAME='sentinel_defensive_bars' OR (before_value->>'session')::date>=d.raw_start))
                 OR ((after_value->>'session')::date<=d.effective_session
                  AND (TG_TABLE_NAME='sentinel_defensive_bars' OR (after_value->>'session')::date>=d.raw_start)))) THEN
            RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
        END IF;
    END IF;
    PERFORM sentinel_execution_evidence_append('MIRROR',TG_TABLE_NAME,plan_key,TG_OP,coordinates);
    RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
END
""".strip()

extension_functions={'sentinel_paper_mirror_changed':_CHANGED}
_WATCHED=tuple(sorted(source_tables|extension_tables))
extension_triggers=frozenset((table,name) for table in _WATCHED for name in (
    'sentinel_paper_mirror_changed','sentinel_paper_mirror_truncated'))
DDL=(
    """CREATE TABLE sentinel_paper_mirror_dependencies (
        plan_id text PRIMARY KEY, decision_session date NOT NULL, effective_session date NOT NULL, raw_start date NOT NULL,
        security_ids text[] NOT NULL, symbols text[] NOT NULL,
        pending_sha256 text NOT NULL CHECK(pending_sha256 ~ '^[a-f0-9]{64}$'),
        payload jsonb NOT NULL, hmac_sha256 text NOT NULL CHECK(hmac_sha256 ~ '^[a-f0-9]{64}$'),
        CHECK(decision_session<effective_session))""",
    'CREATE INDEX sentinel_paper_mirror_dependency_sessions ON sentinel_paper_mirror_dependencies(effective_session,decision_session,plan_id)',
    'CREATE INDEX sentinel_paper_mirror_dependency_ids ON sentinel_paper_mirror_dependencies USING gin(security_ids)',
    'CREATE INDEX sentinel_paper_mirror_dependency_symbols ON sentinel_paper_mirror_dependencies USING gin(symbols)',
    "CREATE INDEX sentinel_paper_mirror_due_unchecked ON sentinel_paper_mirror_dependencies(effective_session,plan_id) WHERE payload->>'status' IS NULL",
    'CREATE FUNCTION sentinel_paper_mirror_changed() RETURNS trigger LANGUAGE plpgsql AS $$'+_CHANGED+'$$',
    *tuple(f'CREATE TRIGGER sentinel_paper_mirror_changed AFTER INSERT OR UPDATE OR DELETE ON {table} '
        'FOR EACH ROW EXECUTE FUNCTION sentinel_paper_mirror_changed()' for table in _WATCHED),
    *tuple(f'CREATE TRIGGER sentinel_paper_mirror_truncated AFTER TRUNCATE ON {table} '
        'FOR EACH STATEMENT EXECUTE FUNCTION sentinel_paper_mirror_changed()' for table in _WATCHED),
)
CONTRACT_SHA256=hashlib.sha256(json.dumps(DDL,separators=(',',':')).encode()).hexdigest()


def require_schema(conn, *, allow_absent=False):
    from sentinel.operational_catalog import require_extension
    return require_extension(conn,__name__,allow_absent=allow_absent)


def install(conn):
    """Explicit caller-owned migration; no commit, bootstrap or history edits."""
    if require_schema(conn,allow_absent=True):
        return
    evidence_schema.require_schema(conn)
    for statement in DDL:
        conn.execute(statement)
    require_schema(conn)
