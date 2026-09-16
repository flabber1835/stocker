"""Catalog witnesses for durable preparation coordination."""

COLUMNS = {
    "sentinel_snapshot_jobs": {
        "job_id": ("uuid", True), "request_sha256": ("text", True),
        "request": ("jsonb", True),
        **{key: ("timestamp with time zone", True) for key in (
            "created_at", "deadline", "updated_at", "phase_started_at", "last_progress_at")},
        "state": ("text", True), "resume_state": ("text", True), "reason": ("text", True),
        "owner": ("uuid", False), "fence": ("bigint", True),
        "lease_until": ("timestamp with time zone", False),
        "next_retry": ("timestamp with time zone", False),
        "rows_done": ("bigint", True), "bytes_done": ("bigint", True),
        "candidate_id": ("uuid", False), "publication_version": ("bigint", False),
    },
    "sentinel_snapshot_job_components": {
        "job_id": ("uuid", True), "component": ("text", True),
        "generation_sha256": ("text", True), "artifact_sha256": ("text", True),
        "rows_done": ("bigint", True), "bytes_done": ("bigint", True),
    },
}
PRIMARY_KEYS = {
    "sentinel_snapshot_jobs": "primary key (job_id)",
    "sentinel_snapshot_job_components": "primary key (job_id, component)",
}
TRIGGERS = {
    "sentinel_snapshot_jobs": {
        "snapshot_job_guard": ("before update", "for each row",
                               "execute function sentinel_snapshot_job_guard()"),
        "snapshot_immutable": ("before delete", "for each row",
                               "execute function sentinel_snapshot_immutable()"),
    },
    "sentinel_snapshot_job_components": {
        "snapshot_immutable": ("before delete or update", "for each row",
                               "execute function sentinel_snapshot_immutable()"),
    },
}
for _table in COLUMNS:
    TRIGGERS[_table]["snapshot_no_truncate"] = (
        "before truncate", "for each statement", "execute function sentinel_snapshot_immutable()")
CONSTRAINTS = {
    "sentinel_snapshot_jobs": (
        ("f", ("foreign key (candidate_id)", "sentinel_price_candidates")),
        ("f", ("foreign key (publication_version)", "sentinel_corpus_publications")),
        ("c", ("deadline > created_at",)),
        ("c", ("lease_until <= deadline",)),
        ("c", ("owner is null", "lease_until is null")),
        ("c", ("published", "publication_version is not null")),
        ("c", ("state", "acquiring", "wait_source", "staging", "validating", "ready",
               "retry_wait", "interrupted", "refused", "aborted", "published")),
    ),
    "sentinel_snapshot_job_components": (
        ("f", ("foreign key (job_id)", "sentinel_snapshot_jobs")),
        ("c", ("generation_sha256", "[0-9a-f]{64}")),
        ("c", ("artifact_sha256", "[0-9a-f]{64}")),
    ),
}
