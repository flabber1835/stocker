"""Immutable ordinary-publication binding for operational snapshot jobs."""

DDL = [
    """CREATE TABLE IF NOT EXISTS sentinel_operational_snapshot_jobs (
        job_id UUID PRIMARY KEY REFERENCES sentinel_snapshot_jobs
    )""",
    """CREATE TABLE IF NOT EXISTS sentinel_operational_snapshot_validations (
        candidate_id UUID PRIMARY KEY REFERENCES sentinel_price_candidates,
        validation_sha256 TEXT NOT NULL REFERENCES sentinel_snapshot_evidence
    )""",
    """CREATE TABLE IF NOT EXISTS sentinel_operational_snapshots (
        publication_version BIGINT PRIMARY KEY REFERENCES sentinel_corpus_publications,
        job_id UUID NOT NULL UNIQUE REFERENCES sentinel_operational_snapshot_jobs,
        candidate_id UUID NOT NULL UNIQUE REFERENCES sentinel_price_candidates,
        validation_sha256 TEXT NOT NULL REFERENCES sentinel_snapshot_evidence
    )""",
    """CREATE OR REPLACE FUNCTION sentinel_operational_snapshot_binding()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE binding sentinel_operational_snapshots%ROWTYPE;
    BEGIN
        IF TG_TABLE_NAME='sentinel_snapshot_jobs' THEN
            IF NEW.state<>'PUBLISHED' OR NOT EXISTS (
                SELECT 1 FROM sentinel_operational_snapshot_jobs WHERE job_id=NEW.job_id)
            THEN RETURN NEW; END IF;
            SELECT * INTO binding FROM sentinel_operational_snapshots WHERE job_id=NEW.job_id;
        ELSE
            SELECT * INTO binding FROM sentinel_operational_snapshots WHERE job_id=NEW.job_id;
        END IF;
        IF binding.job_id IS NULL OR NOT EXISTS (
            SELECT 1 FROM sentinel_snapshot_jobs j
            JOIN sentinel_price_candidates c ON c.candidate_id=binding.candidate_id
            JOIN sentinel_corpus_publications p ON p.version=binding.publication_version
            WHERE j.job_id=binding.job_id AND j.state='PUBLISHED'
              AND j.publication_version=p.version AND j.candidate_id=c.candidate_id
              AND p.previous_version IS NOT DISTINCT FROM (j.request->>'expected_publication_version')::bigint
              AND p.window_start=c.window_start AND p.window_end=c.window_end
              AND p.evidence->'rolling_snapshot'->>'candidate_id'=c.candidate_id::text
              AND p.evidence->'rolling_snapshot'->>'snapshot_id'=c.snapshot_id
              AND p.evidence->'rolling_snapshot'->>'reference_sha256'=c.reference_sha256
              AND p.evidence->'rolling_snapshot'->>'validation_sha256'=binding.validation_sha256
              AND p.evidence->'rolling_snapshot'->>'job_id'=j.job_id::text
        ) THEN RAISE EXCEPTION 'operational snapshot binding is incomplete or inconsistent'; END IF;
        RETURN NEW;
    END $$""",
]
for _table in ("sentinel_operational_snapshot_jobs", "sentinel_operational_snapshots",
               "sentinel_operational_snapshot_validations"):
    DDL.extend([
        f"DROP TRIGGER IF EXISTS snapshot_immutable ON {_table}",
        f"CREATE TRIGGER snapshot_immutable BEFORE UPDATE OR DELETE ON {_table} "
        "FOR EACH ROW EXECUTE FUNCTION sentinel_snapshot_immutable()",
        f"DROP TRIGGER IF EXISTS snapshot_no_truncate ON {_table}",
        f"CREATE TRIGGER snapshot_no_truncate BEFORE TRUNCATE ON {_table} "
        "FOR EACH STATEMENT EXECUTE FUNCTION sentinel_snapshot_immutable()",
    ])
for _table, _event in (("sentinel_operational_snapshots", "INSERT"), ("sentinel_snapshot_jobs", "UPDATE")):
    DDL.extend([
        f"DROP TRIGGER IF EXISTS operational_snapshot_binding ON {_table}",
        f"CREATE CONSTRAINT TRIGGER operational_snapshot_binding AFTER {_event} ON {_table} "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION sentinel_operational_snapshot_binding()",
    ])
