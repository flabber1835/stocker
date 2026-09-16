"""Catalog witnesses for comparison publication; no production reader cutover."""

COLUMNS = {
    "sentinel_snapshot_comparisons": {
        "version": ("bigint", True), "previous_version": ("bigint", False),
        "job_id": ("uuid", True), "candidate_id": ("uuid", True),
        "validation_sha256": ("text", True), "producer_sha256": ("text", True),
        "published_at": ("timestamp with time zone", True),
    },
    "sentinel_snapshot_attempts": {
        "job_id": ("uuid", True), "expected_version": ("bigint", False),
    },
    "sentinel_snapshot_validations": {
        "candidate_id": ("uuid", True), "validation_sha256": ("text", True),
    },
}
PRIMARY_KEYS = {
    "sentinel_snapshot_comparisons": "primary key (version)",
    "sentinel_snapshot_attempts": "primary key (job_id)",
    "sentinel_snapshot_validations": "primary key (candidate_id)",
}
TRIGGERS = {table: {
    "snapshot_immutable": ("before delete or update", "for each row",
                           "execute function sentinel_snapshot_immutable()"),
    "snapshot_no_truncate": ("before truncate", "for each statement",
                             "execute function sentinel_snapshot_immutable()"),
} for table in COLUMNS}
CONSTRAINTS = {
    "sentinel_snapshot_comparisons": (
        ("f", ("foreign key (previous_version)", "sentinel_snapshot_comparisons")),
        ("f", ("foreign key (job_id)", "sentinel_snapshot_jobs")),
        ("f", ("foreign key (candidate_id)", "sentinel_price_candidates")),
        ("f", ("foreign key (validation_sha256)", "sentinel_snapshot_evidence")),
        ("f", ("foreign key (producer_sha256)", "sentinel_snapshot_evidence")),
        ("u", ("unique (job_id)",)), ("u", ("unique (candidate_id)",)),
        ("c", ("previous_version < version",)),
    ),
    "sentinel_snapshot_attempts": (
        ("f", ("foreign key (job_id)", "sentinel_snapshot_jobs")),
        ("f", ("foreign key (expected_version)", "sentinel_snapshot_comparisons")),
    ),
    "sentinel_snapshot_validations": (
        ("f", ("foreign key (candidate_id)", "sentinel_price_candidates")),
        ("f", ("foreign key (validation_sha256)", "sentinel_snapshot_evidence")),
    ),
}
