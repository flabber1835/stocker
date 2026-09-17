"""Runtime catalog witnesses for operational snapshot publication."""

COLUMNS = {
    "sentinel_operational_snapshot_jobs": {"job_id": ("uuid", True)},
    "sentinel_operational_snapshot_validations": {
        "candidate_id": ("uuid", True), "validation_sha256": ("text", True),
    },
    "sentinel_operational_snapshots": {
        "publication_version": ("bigint", True), "job_id": ("uuid", True),
        "candidate_id": ("uuid", True), "validation_sha256": ("text", True),
    },
}
PRIMARY_KEYS = {
    "sentinel_operational_snapshot_jobs": "primary key (job_id)",
    "sentinel_operational_snapshot_validations": "primary key (candidate_id)",
    "sentinel_operational_snapshots": "primary key (publication_version)",
}
TRIGGERS = {table: {
    "snapshot_immutable": ("before delete or update", "for each row",
                           "execute function sentinel_snapshot_immutable()"),
    "snapshot_no_truncate": ("before truncate", "for each statement",
                             "execute function sentinel_snapshot_immutable()"),
} for table in COLUMNS}
for _table, _event in (("sentinel_operational_snapshots", "insert"), ("sentinel_snapshot_jobs", "update")):
    TRIGGERS.setdefault(_table, {})["operational_snapshot_binding"] = (
        "after " + _event, "deferrable initially deferred", "for each row",
        "execute function sentinel_operational_snapshot_binding()")
CONSTRAINTS = {
    "sentinel_operational_snapshot_jobs": (("f", ("foreign key (job_id)", "sentinel_snapshot_jobs")),),
    "sentinel_operational_snapshot_validations": (
        ("f", ("foreign key (candidate_id)", "sentinel_price_candidates")),
        ("f", ("foreign key (validation_sha256)", "sentinel_snapshot_evidence")),
    ),
    "sentinel_operational_snapshots": (
        ("f", ("foreign key (publication_version)", "sentinel_corpus_publications")),
        ("f", ("foreign key (job_id)", "sentinel_operational_snapshot_jobs")),
        ("f", ("foreign key (candidate_id)", "sentinel_price_candidates")),
        ("f", ("foreign key (validation_sha256)", "sentinel_snapshot_evidence")),
        ("u", ("unique (job_id)",)), ("u", ("unique (candidate_id)",)),
    ),
}
