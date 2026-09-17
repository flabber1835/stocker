"""Narrow retirement of bulk payloads; immutable identities remain intact."""

DDL = [
    """CREATE TABLE IF NOT EXISTS sentinel_snapshot_retirements (
        candidate_id UUID PRIMARY KEY REFERENCES sentinel_price_candidates,
        retired_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp())""",
    """CREATE TABLE IF NOT EXISTS sentinel_snapshot_workers (
        owner UUID PRIMARY KEY,
        job_id UUID NOT NULL REFERENCES sentinel_snapshot_jobs)""",
    """CREATE TABLE IF NOT EXISTS sentinel_snapshot_maintenance (
        id BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK(id),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        diagnostic JSONB NOT NULL)""",
    "ALTER TABLE sentinel_snapshot_evidence ALTER COLUMN payload DROP NOT NULL",
    "ALTER TABLE sentinel_snapshot_evidence ADD COLUMN IF NOT EXISTS restored_bytes TEXT CHECK(restored_bytes IS NULL)",
    """CREATE OR REPLACE FUNCTION sentinel_retention_locks() RETURNS void LANGUAGE plpgsql AS $$
    BEGIN
      IF (SELECT count(DISTINCT objid) FROM pg_locks WHERE locktype='advisory'
          AND pid=pg_backend_pid() AND granted AND mode='ExclusiveLock'
          AND ((classid::bigint << 32) | objid::bigint) IN (1579621904,1579663541)) <> 2 THEN
        RAISE EXCEPTION 'retirement requires behavioral and corpus writer locks';
      END IF;
    END $$""",
    """CREATE OR REPLACE FUNCTION sentinel_snapshot_pins(target UUID) RETURNS TEXT[] LANGUAGE plpgsql AS $$
    DECLARE reasons TEXT[] := '{}'; checkpoint JSONB; current_version BIGINT;
    BEGIN
      SELECT max(version) INTO current_version FROM sentinel_corpus_publications;
      IF EXISTS(SELECT 1 FROM sentinel_operational_snapshots WHERE candidate_id=target
                AND publication_version=current_version) THEN reasons:=array_append(reasons,'CURRENT_PUBLICATION'); END IF;
      IF EXISTS(SELECT 1 FROM sentinel_snapshot_comparisons WHERE candidate_id=target
                AND version=(SELECT max(version) FROM sentinel_snapshot_comparisons))
        THEN reasons:=array_append(reasons,'CURRENT_COMPARISON'); END IF;
      IF EXISTS(SELECT 1 FROM sentinel_snapshot_jobs j WHERE candidate_id=target
                AND state NOT IN ('REFUSED','ABORTED','PUBLISHED')
                AND NOT EXISTS(SELECT 1 FROM sentinel_snapshot_comparisons c WHERE c.job_id=j.job_id))
        THEN reasons:=array_append(reasons,'PREPARATION_JOB'); END IF;
      IF NOT EXISTS(SELECT 1 FROM sentinel_snapshot_jobs WHERE candidate_id=target)
        THEN reasons:=array_append(reasons,'UNOWNED_CANDIDATE'); END IF;
      IF EXISTS(SELECT 1 FROM sentinel_operational_snapshots s WHERE candidate_id=target
                AND NOT EXISTS(SELECT 1 FROM sentinel_action_coverage a WHERE a.publication_version=s.publication_version))
        THEN reasons:=array_append(reasons,'ACTION_ARCHIVE_UNAVAILABLE'); END IF;
      IF to_regclass('sentinel_processed_sessions') IS NOT NULL THEN
        EXECUTE 'SELECT state FROM sentinel_processed_sessions WHERE cursor_name IN
          (''rolling-daily-checkpoint:v1'',''rolling-cold-start:v1'')
          ORDER BY CASE cursor_name WHEN ''rolling-daily-checkpoint:v1'' THEN 0 ELSE 1 END LIMIT 1'
          INTO checkpoint;
        IF checkpoint IS NOT NULL THEN
          IF checkpoint->'checkpoint'->'snapshot'->>'candidate_id' IS NULL THEN
            reasons:=array_append(reasons,'UNKNOWN_CHECKPOINT_REFERENCE');
          ELSIF checkpoint->'checkpoint'->'snapshot'->>'candidate_id'=target::text THEN
            reasons:=array_append(reasons,'RESTART_CHECKPOINT');
          END IF;
        END IF;
      END IF;
      RETURN reasons;
    END $$""",
    """CREATE OR REPLACE FUNCTION sentinel_snapshot_retire_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      PERFORM sentinel_retention_locks();
      PERFORM 1 FROM sentinel_snapshot_jobs WHERE candidate_id=NEW.candidate_id FOR UPDATE;
      PERFORM 1 FROM sentinel_price_candidates WHERE candidate_id=NEW.candidate_id FOR UPDATE;
      IF cardinality(sentinel_snapshot_pins(NEW.candidate_id))<>0 THEN
        RAISE EXCEPTION 'snapshot has live dependencies: %',sentinel_snapshot_pins(NEW.candidate_id);
      END IF;
      RETURN NEW;
    END $$""",
    """CREATE OR REPLACE FUNCTION sentinel_snapshot_payload_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='DELETE' AND EXISTS(SELECT 1 FROM sentinel_snapshot_retirements WHERE candidate_id=OLD.candidate_id) THEN
        PERFORM sentinel_retention_locks();
        RETURN OLD;
      END IF;
      RAISE EXCEPTION 'snapshot evidence is immutable';
    END $$""",
    """CREATE OR REPLACE FUNCTION sentinel_snapshot_evidence_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP<>'UPDATE' OR NEW.evidence_sha256<>OLD.evidence_sha256 THEN
        RAISE EXCEPTION 'snapshot evidence is immutable';
      END IF;
      IF OLD.payload IS NULL AND NEW.payload IS NOT NULL AND NEW.restored_bytes IS NOT NULL
          AND NEW.restored_bytes::jsonb=NEW.payload
          AND encode(sha256(convert_to(NEW.restored_bytes,'UTF8')),'hex')=OLD.evidence_sha256 THEN
        NEW.restored_bytes:=NULL;
        RETURN NEW;
      END IF;
      PERFORM sentinel_retention_locks();
      IF NEW.payload IS NOT NULL OR NEW.restored_bytes IS NOT NULL OR EXISTS(
        SELECT 1 FROM sentinel_price_candidates c WHERE
          (c.reference_sha256=OLD.evidence_sha256 OR c.source_evidence_sha256=OLD.evidence_sha256)
          AND NOT EXISTS(SELECT 1 FROM sentinel_snapshot_retirements r WHERE r.candidate_id=c.candidate_id))
        OR EXISTS(SELECT 1 FROM sentinel_snapshot_validations WHERE validation_sha256=OLD.evidence_sha256)
        OR EXISTS(SELECT 1 FROM sentinel_operational_snapshot_validations WHERE validation_sha256=OLD.evidence_sha256)
        OR EXISTS(SELECT 1 FROM sentinel_snapshot_comparisons WHERE producer_sha256=OLD.evidence_sha256
                    OR validation_sha256=OLD.evidence_sha256)
        OR EXISTS(SELECT 1 FROM sentinel_operational_snapshots WHERE validation_sha256=OLD.evidence_sha256)
      THEN RAISE EXCEPTION 'snapshot evidence still has live dependencies'; END IF;
      RETURN NEW;
    END $$""",
    """CREATE OR REPLACE FUNCTION sentinel_snapshot_live_job() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.candidate_id IS NOT NULL THEN
        PERFORM 1 FROM sentinel_price_candidates WHERE candidate_id=NEW.candidate_id FOR KEY SHARE;
        IF EXISTS(SELECT 1 FROM sentinel_snapshot_retirements WHERE candidate_id=NEW.candidate_id) THEN
          RAISE EXCEPTION 'job candidate has retired';
        END IF;
      END IF;
      RETURN NEW;
    END $$""",
    """CREATE OR REPLACE FUNCTION sentinel_snapshot_live_candidate() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      PERFORM 1 FROM sentinel_snapshot_evidence WHERE evidence_sha256 IN
        (NEW.reference_sha256,NEW.source_evidence_sha256) FOR SHARE;
      IF EXISTS(SELECT 1 FROM sentinel_snapshot_evidence WHERE evidence_sha256 IN
        (NEW.reference_sha256,NEW.source_evidence_sha256) AND payload IS NULL) THEN
        RAISE EXCEPTION 'candidate evidence payload is retired';
      END IF;
      RETURN NEW;
    END $$""",
]
for table in ("sentinel_snapshot_retirements", "sentinel_snapshot_workers"):
    for name, event, scope in (("snapshot_immutable", "UPDATE OR DELETE", "ROW"),
                               ("snapshot_no_truncate", "TRUNCATE", "STATEMENT")):
        DDL.extend([f"DROP TRIGGER IF EXISTS {name} ON {table}",
                    f"CREATE TRIGGER {name} BEFORE {event} ON {table} FOR EACH {scope} "
                    "EXECUTE FUNCTION sentinel_snapshot_immutable()"])
for table, name, event, function in (
    ("sentinel_snapshot_retirements", "retire_guard", "INSERT", "sentinel_snapshot_retire_guard"),
    ("sentinel_snapshot_bars", "snapshot_immutable", "UPDATE OR DELETE", "sentinel_snapshot_payload_guard"),
    ("sentinel_snapshot_benchmarks", "snapshot_immutable", "UPDATE OR DELETE", "sentinel_snapshot_payload_guard"),
    ("sentinel_snapshot_evidence", "snapshot_immutable", "UPDATE OR DELETE", "sentinel_snapshot_evidence_guard"),
    ("sentinel_snapshot_jobs", "snapshot_live_job", "INSERT OR UPDATE", "sentinel_snapshot_live_job"),
    ("sentinel_price_candidates", "snapshot_live_candidate", "INSERT", "sentinel_snapshot_live_candidate"),
):
    DDL.extend([f"DROP TRIGGER IF EXISTS {name} ON {table}",
                f"CREATE TRIGGER {name} BEFORE {event} ON {table} FOR EACH ROW EXECUTE FUNCTION {function}()"])
