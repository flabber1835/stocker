"""Logged job coordination and immutable source-completion checkpoints."""

DDL = [
    """CREATE TABLE IF NOT EXISTS sentinel_snapshot_jobs (
        job_id UUID PRIMARY KEY,
        request_sha256 TEXT NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
        request JSONB NOT NULL CHECK (jsonb_typeof(request)='object'),
        created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        deadline TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        phase_started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        last_progress_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        state TEXT NOT NULL CHECK (state IN ('ACQUIRING','WAIT_SOURCE','STAGING',
            'VALIDATING','READY','RETRY_WAIT','INTERRUPTED','REFUSED','ABORTED','PUBLISHED')),
        resume_state TEXT NOT NULL CHECK (resume_state IN ('ACQUIRING','STAGING','VALIDATING','READY')),
        reason TEXT NOT NULL CHECK (reason ~ '^[A-Z][A-Z0-9_]{0,95}$'),
        owner UUID,
        fence BIGINT NOT NULL DEFAULT 0 CHECK (fence>=0),
        lease_until TIMESTAMPTZ,
        next_retry TIMESTAMPTZ,
        rows_done BIGINT NOT NULL DEFAULT 0 CHECK (rows_done>=0),
        bytes_done BIGINT NOT NULL DEFAULT 0 CHECK (bytes_done>=0),
        candidate_id UUID REFERENCES sentinel_price_candidates,
        publication_version BIGINT REFERENCES sentinel_corpus_publications,
        CHECK (deadline>created_at),
        CHECK ((owner IS NULL) = (lease_until IS NULL)),
        CHECK (lease_until<=deadline),
        CHECK ((state='PUBLISHED') = (publication_version IS NOT NULL)))""",
    """CREATE UNIQUE INDEX IF NOT EXISTS sentinel_snapshot_jobs_active_request
        ON sentinel_snapshot_jobs(request_sha256)
        WHERE state NOT IN ('REFUSED','ABORTED','PUBLISHED')""",
    r"""CREATE TABLE IF NOT EXISTS sentinel_snapshot_job_components (
        job_id UUID NOT NULL REFERENCES sentinel_snapshot_jobs,
        component TEXT NOT NULL CHECK (component ~ '^(SEP|SFP|ACTIONS|TICKERS)(\.[0-9]{4}-[0-9]{2}-[0-9]{2}\.[0-9]{4}-[0-9]{2}-[0-9]{2})?$'),
        generation_sha256 TEXT NOT NULL CHECK (generation_sha256 ~ '^[0-9a-f]{64}$'),
        artifact_sha256 TEXT NOT NULL CHECK (artifact_sha256 ~ '^[0-9a-f]{64}$'),
        rows_done BIGINT NOT NULL CHECK (rows_done>=0),
        bytes_done BIGINT NOT NULL CHECK (bytes_done>=0),
        PRIMARY KEY (job_id,component))""",
    """CREATE OR REPLACE FUNCTION sentinel_snapshot_job_guard()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF (OLD.job_id,OLD.request_sha256,OLD.request,OLD.created_at,OLD.deadline)
                IS DISTINCT FROM
               (NEW.job_id,NEW.request_sha256,NEW.request,NEW.created_at,NEW.deadline)
                OR OLD.state IN ('REFUSED','ABORTED','PUBLISHED') THEN
                RAISE EXCEPTION 'job request, deadline and terminal outcomes are immutable';
            END IF;
            RETURN NEW;
        END $$""",
    "DROP TRIGGER IF EXISTS snapshot_job_guard ON sentinel_snapshot_jobs",
    "CREATE TRIGGER snapshot_job_guard BEFORE UPDATE ON sentinel_snapshot_jobs "
    "FOR EACH ROW EXECUTE FUNCTION sentinel_snapshot_job_guard()",
    "DROP TRIGGER IF EXISTS snapshot_immutable ON sentinel_snapshot_jobs",
    "CREATE TRIGGER snapshot_immutable BEFORE DELETE ON sentinel_snapshot_jobs "
    "FOR EACH ROW EXECUTE FUNCTION sentinel_snapshot_immutable()",
    "DROP TRIGGER IF EXISTS snapshot_immutable ON sentinel_snapshot_job_components",
    "CREATE TRIGGER snapshot_immutable BEFORE UPDATE OR DELETE ON sentinel_snapshot_job_components "
    "FOR EACH ROW EXECUTE FUNCTION sentinel_snapshot_immutable()",
]
for _table in ("sentinel_snapshot_jobs", "sentinel_snapshot_job_components"):
    DDL.extend([
        f"DROP TRIGGER IF EXISTS snapshot_no_truncate ON {_table}",
        f"CREATE TRIGGER snapshot_no_truncate BEFORE TRUNCATE ON {_table} "
        "FOR EACH STATEMENT EXECUTE FUNCTION sentinel_snapshot_immutable()",
    ])
