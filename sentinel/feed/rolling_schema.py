"""Additive, logged candidate storage; no production visibility switch.

Installed only by the explicit feed migration. Parent-row locking serializes
batch insertion with sealing, including writers that bypass the Python API.
"""

DDL = [
    """CREATE TABLE IF NOT EXISTS sentinel_snapshot_evidence (
        evidence_sha256 TEXT PRIMARY KEY CHECK (evidence_sha256 ~ '^[0-9a-f]{64}$'),
        payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'))""",
    """CREATE TABLE IF NOT EXISTS sentinel_price_candidates (
        candidate_id UUID PRIMARY KEY,
        window_start DATE NOT NULL,
        window_end DATE NOT NULL CHECK (window_end > window_start),
        session_axis JSONB NOT NULL CHECK (jsonb_typeof(session_axis) = 'array'
                                    AND jsonb_array_length(session_axis) = 300),
        reference_sha256 TEXT NOT NULL REFERENCES sentinel_snapshot_evidence,
        source_evidence_sha256 TEXT NOT NULL REFERENCES sentinel_snapshot_evidence,
        expected_publication_version BIGINT CHECK (expected_publication_version > 0),
        dependencies_sha256 TEXT NOT NULL CHECK (dependencies_sha256 ~ '^[0-9a-f]{64}$'),
        snapshot_id TEXT CHECK (snapshot_id ~ '^[0-9a-f]{64}$'),
        manifest JSONB,
        CHECK ((snapshot_id IS NULL AND manifest IS NULL) OR
               (snapshot_id IS NOT NULL AND manifest IS NOT NULL
                AND jsonb_typeof(manifest) = 'object')))""",
    """CREATE TABLE IF NOT EXISTS sentinel_snapshot_bars (
        candidate_id UUID NOT NULL REFERENCES sentinel_price_candidates,
        security_id TEXT NOT NULL CHECK (length(security_id) BETWEEN 1 AND 256),
        session DATE NOT NULL,
        ticker TEXT NOT NULL CHECK (length(ticker) BETWEEN 1 AND 256),
        close_signal DOUBLE PRECISION,
        close_unadjusted DOUBLE PRECISION NOT NULL,
        open_unadjusted DOUBLE PRECISION,
        volume DOUBLE PRECISION,
        split_ratio DOUBLE PRECISION NOT NULL,
        dividend_per_share DOUBLE PRECISION NOT NULL,
        PRIMARY KEY (candidate_id, session, security_id),
        CHECK (close_signal > 0 AND close_signal < 'Infinity'::float8),
        CHECK (close_unadjusted > 0 AND close_unadjusted < 'Infinity'::float8),
        CHECK (open_unadjusted > 0 AND open_unadjusted < 'Infinity'::float8),
        CHECK (volume >= 0 AND volume < 'Infinity'::float8),
        CHECK (split_ratio > 0 AND split_ratio < 'Infinity'::float8),
        CHECK (dividend_per_share >= 0 AND dividend_per_share < 'Infinity'::float8))""",
    """CREATE TABLE IF NOT EXISTS sentinel_snapshot_benchmarks (
        candidate_id UUID NOT NULL REFERENCES sentinel_price_candidates,
        session DATE NOT NULL,
        spy_total_return DOUBLE PRECISION NOT NULL,
        bil_open_signal DOUBLE PRECISION,
        bil_close_signal DOUBLE PRECISION NOT NULL,
        bil_close_adjusted DOUBLE PRECISION,
        bil_close_unadjusted DOUBLE PRECISION NOT NULL,
        PRIMARY KEY (candidate_id, session),
        CHECK (spy_total_return > 0 AND spy_total_return < 'Infinity'::float8),
        CHECK (bil_open_signal > 0 AND bil_open_signal < 'Infinity'::float8),
        CHECK (bil_close_signal > 0 AND bil_close_signal < 'Infinity'::float8),
        CHECK (bil_close_adjusted > 0 AND bil_close_adjusted < 'Infinity'::float8),
        CHECK (bil_close_unadjusted > 0 AND bil_close_unadjusted < 'Infinity'::float8))""",
    """CREATE OR REPLACE FUNCTION sentinel_snapshot_immutable()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'snapshot evidence is immutable';
        END $$""",
    """CREATE OR REPLACE FUNCTION sentinel_snapshot_insert()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent sentinel_price_candidates%ROWTYPE;
        BEGIN
            SELECT * INTO parent FROM sentinel_price_candidates
                WHERE candidate_id=NEW.candidate_id FOR UPDATE;
            IF NOT FOUND OR parent.snapshot_id IS NOT NULL THEN
                RAISE EXCEPTION 'snapshot candidate is absent or sealed';
            END IF;
            IF EXISTS (SELECT 1 FROM sentinel_snapshot_retirements WHERE candidate_id=NEW.candidate_id) THEN
                RAISE EXCEPTION 'snapshot candidate is retired';
            END IF;
            IF NOT parent.session_axis @> to_jsonb(ARRAY[NEW.session::text]) THEN
                RAISE EXCEPTION 'snapshot observation is outside the session axis';
            END IF;
            RETURN NEW;
        END $$""",
    """CREATE OR REPLACE FUNCTION sentinel_snapshot_seal()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.snapshot_id IS NOT NULL OR NEW.snapshot_id IS NULL
                OR NEW.manifest IS NULL
                OR (to_jsonb(OLD) - 'snapshot_id' - 'manifest') IS DISTINCT FROM
                   (to_jsonb(NEW) - 'snapshot_id' - 'manifest') THEN
                RAISE EXCEPTION 'only an unsealed candidate may be sealed';
            END IF;
            RETURN NEW;
        END $$""",
    """CREATE OR REPLACE FUNCTION sentinel_snapshot_new_candidate()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.snapshot_id IS NOT NULL OR NEW.manifest IS NOT NULL THEN
                RAISE EXCEPTION 'new snapshot candidate must be unsealed';
            END IF;
            RETURN NEW;
        END $$""",
]

for _table in ("sentinel_snapshot_evidence", "sentinel_snapshot_bars",
               "sentinel_snapshot_benchmarks"):
    DDL.extend([
        f"DROP TRIGGER IF EXISTS snapshot_immutable ON {_table}",
        f"CREATE TRIGGER snapshot_immutable BEFORE UPDATE OR DELETE ON {_table} "
        "FOR EACH ROW EXECUTE FUNCTION sentinel_snapshot_immutable()",
    ])
for _table in ("sentinel_snapshot_bars", "sentinel_snapshot_benchmarks"):
    DDL.extend([
        f"DROP TRIGGER IF EXISTS snapshot_insert ON {_table}",
        f"CREATE TRIGGER snapshot_insert BEFORE INSERT ON {_table} "
        "FOR EACH ROW EXECUTE FUNCTION sentinel_snapshot_insert()",
    ])
DDL.extend([
    "DROP TRIGGER IF EXISTS snapshot_new_candidate ON sentinel_price_candidates",
    "CREATE TRIGGER snapshot_new_candidate BEFORE INSERT ON sentinel_price_candidates "
    "FOR EACH ROW EXECUTE FUNCTION sentinel_snapshot_new_candidate()",
    "DROP TRIGGER IF EXISTS snapshot_seal ON sentinel_price_candidates",
    "CREATE TRIGGER snapshot_seal BEFORE UPDATE ON sentinel_price_candidates "
    "FOR EACH ROW EXECUTE FUNCTION sentinel_snapshot_seal()",
    "DROP TRIGGER IF EXISTS snapshot_immutable ON sentinel_price_candidates",
    "CREATE TRIGGER snapshot_immutable BEFORE DELETE ON sentinel_price_candidates "
    "FOR EACH ROW EXECUTE FUNCTION sentinel_snapshot_immutable()",
])
for _table in ("sentinel_snapshot_evidence", "sentinel_price_candidates",
               "sentinel_snapshot_bars", "sentinel_snapshot_benchmarks"):
    DDL.extend([
        f"DROP TRIGGER IF EXISTS snapshot_no_truncate ON {_table}",
        f"CREATE TRIGGER snapshot_no_truncate BEFORE TRUNCATE ON {_table} "
        "FOR EACH STATEMENT EXECUTE FUNCTION sentinel_snapshot_immutable()",
    ])
