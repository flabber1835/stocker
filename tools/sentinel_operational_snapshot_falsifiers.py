"""Remove operational publication guards and require targeted test failures."""
from tools.sentinel_rolling_storage_falsifiers import main

MUTANTS = {
    "ordinary_publication_cas": (
        "sentinel.feed.operational_snapshot",
        "if (current.version if current else None) != request.expected_publication_version:",
        "if False:", "test_publication_cas_rejects_concurrent_job",
    ),
    "source_final_target": (
        "sentinel.feed.operational_snapshot",
        "if str(request.window.end) != source_final_session():", "if False:",
        "test_target_that_aged_during_validation_cannot_publish",
    ),
    "legacy_reader_fence": (
        "sentinel.feed.publication",
        'if "rolling_snapshot" in publication.evidence and not allow_snapshot:', "if False:",
        "test_legacy_readers_cannot_mislabel_legacy_rows_with_snapshot_version",
    ),
    "legacy_publisher_marker": (
        "sentinel.feed.publication",
        'if "rolling_snapshot" in merged:', "if False:",
        "test_cannot_supply_snapshot_marker_to_legacy_publisher",
    ),
    "bound_operational_validation": (
        "sentinel.feed.operational_snapshot",
        'if proof != {"schema": VALIDATION_SCHEMA, "scope": "DATA_ONLY",',
        'if False and proof != {"schema": VALIDATION_SCHEMA, "scope": "DATA_ONLY",',
        "test_missing_operational_validation_cannot_publish",
    ),
    "job_scope": (
        "sentinel.feed.rolling_publisher",
        "if operational_snapshot.registered(conn, job_id) != operational:", "if False:",
        "test_job_cannot_cross_comparison_boundary",
    ),
    "post_receipt_lease": (
        "sentinel.feed.operational_snapshot",
        "    jobs._owned(conn, lease)  # Receipt-chain work cannot extend the publication lease.",
        "    pass",
        "test_receipt_work_cannot_outlive_publication_lease",
    ),
    "deferred_binding": (
        "sentinel.feed.operational_snapshot_schema",
        "IF binding.job_id IS NULL OR NOT EXISTS (",
        "IF FALSE AND NOT EXISTS (",
        "test_deferred_constraint_prevents_unbound_published_job",
    ),
}

if __name__ == "__main__":
    raise SystemExit(main(mutants=MUTANTS, test_file="tests/sentinel/test_operational_snapshot.py",
                          runner="tools.sentinel_operational_snapshot_falsifiers"))
