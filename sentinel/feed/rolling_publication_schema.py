"""Comparison-only visibility. Never the operational corpus publication ledger."""

DDL = [
    """CREATE TABLE IF NOT EXISTS sentinel_snapshot_comparisons (
        version BIGSERIAL PRIMARY KEY,
        previous_version BIGINT REFERENCES sentinel_snapshot_comparisons,
        job_id UUID NOT NULL UNIQUE REFERENCES sentinel_snapshot_jobs,
        candidate_id UUID NOT NULL UNIQUE REFERENCES sentinel_price_candidates,
        validation_sha256 TEXT NOT NULL REFERENCES sentinel_snapshot_evidence,
        producer_sha256 TEXT NOT NULL REFERENCES sentinel_snapshot_evidence,
        published_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        CHECK (previous_version IS NULL OR previous_version < version)
    )""",
    """CREATE TABLE IF NOT EXISTS sentinel_snapshot_attempts (
        job_id UUID PRIMARY KEY REFERENCES sentinel_snapshot_jobs,
        expected_version BIGINT REFERENCES sentinel_snapshot_comparisons
    )""",
    """CREATE TABLE IF NOT EXISTS sentinel_snapshot_validations (
        candidate_id UUID PRIMARY KEY REFERENCES sentinel_price_candidates,
        validation_sha256 TEXT NOT NULL REFERENCES sentinel_snapshot_evidence
    )""",
]
for _table in ("sentinel_snapshot_comparisons", "sentinel_snapshot_attempts",
               "sentinel_snapshot_validations"):
    DDL.extend([
        f"DROP TRIGGER IF EXISTS snapshot_immutable ON {_table}",
        f"CREATE TRIGGER snapshot_immutable BEFORE UPDATE OR DELETE ON {_table} "
        "FOR EACH ROW EXECUTE FUNCTION sentinel_snapshot_immutable()",
        f"DROP TRIGGER IF EXISTS snapshot_no_truncate ON {_table}",
        f"CREATE TRIGGER snapshot_no_truncate BEFORE TRUNCATE ON {_table} "
        "FOR EACH STATEMENT EXECUTE FUNCTION sentinel_snapshot_immutable()",
    ])
