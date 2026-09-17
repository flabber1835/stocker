"""Logged compact evidence committed atomically with corpus publication."""

DDL = [
    """CREATE TABLE IF NOT EXISTS sentinel_action_history (
        session DATE PRIMARY KEY,
        publication_version BIGINT NOT NULL REFERENCES sentinel_corpus_publications
            DEFERRABLE INITIALLY DEFERRED,
        payload_sha256 TEXT NOT NULL,
        payload JSONB NOT NULL CHECK(jsonb_typeof(payload)='object'))""",
    """CREATE TABLE IF NOT EXISTS sentinel_action_coverage (
        publication_version BIGINT PRIMARY KEY REFERENCES sentinel_corpus_publications
            DEFERRABLE INITIALLY DEFERRED,
        basis DATE NOT NULL,
        through DATE NOT NULL CHECK(through>basis),
        payload_sha256 TEXT NOT NULL,
        payload JSONB NOT NULL CHECK(jsonb_typeof(payload)='object'))""",
]
for table in ("sentinel_action_history", "sentinel_action_coverage"):
    DDL.extend([
        f"DROP TRIGGER IF EXISTS snapshot_immutable ON {table}",
        f"CREATE TRIGGER snapshot_immutable BEFORE UPDATE OR DELETE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION sentinel_snapshot_immutable()",
        f"DROP TRIGGER IF EXISTS snapshot_no_truncate ON {table}",
        f"CREATE TRIGGER snapshot_no_truncate BEFORE TRUNCATE ON {table} "
        "FOR EACH STATEMENT EXECUTE FUNCTION sentinel_snapshot_immutable()",
    ])
