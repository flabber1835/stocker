"""Guard-removal checks for durable preparation job invariants."""
from tools.sentinel_rolling_storage_falsifiers import main

MUTANTS = {
    "owner": (
        "sentinel.feed.rolling_jobs", "str(row[4]) != lease.owner", "False",
        "test_each_lease_identity_is_required[owner]",
    ),
    "fence": (
        "sentinel.feed.rolling_jobs", "row[5] != lease.fence", "False",
        "test_each_lease_identity_is_required[fence]",
    ),
    "fixed_deadline": (
        "sentinel.feed.rolling_job_schema",
        "NEW.request,NEW.created_at,NEW.deadline)",
        "NEW.request,NEW.created_at,OLD.deadline)",
        "test_expired_deadline_cannot_be_extended_or_reclaimed",
    ),
    "meaningful_progress": (
        "sentinel.feed.rolling_jobs", "meaningful = rows > current[8] or bytes_ > current[9]",
        "meaningful = True", "test_heartbeat_is_not_meaningful_progress",
    ),
    "source_generation": (
        "sentinel.feed.rolling_jobs", "if cur.fetchone() != values:", "if False:",
        "test_component_is_idempotent_but_changed_generation_refuses",
    ),
    "sealed_ready": (
        "sentinel.feed.rolling_jobs", 'rolling_store.manifest(conn, candidate)', "None",
        "test_ready_requires_exact_sealed_candidate_and_does_not_publish",
    ),
    "candidate_window": (
        "sentinel.feed.rolling_jobs",
        'parent[0] != request.window.model_dump(mode="json")["sessions"]', "False",
        "test_candidate_with_different_window_refuses",
    ),
    "retry_budget": (
        "sentinel.feed.rolling_jobs", "if retry >= current[2]:", "if False:",
        "test_retry_cannot_hide_budget_exhaustion",
    ),
    "ready_lease": (
        "sentinel.feed.rolling_jobs",
        "current = _owned(conn, lease)\n    with conn.cursor() as cur:\n        cur.execute(\"UPDATE sentinel_snapshot_jobs SET state=%s,resume_state=%s,candidate_id=%s,\"",
        "None\n    with conn.cursor() as cur:\n        cur.execute(\"UPDATE sentinel_snapshot_jobs SET state=%s,resume_state=%s,candidate_id=%s,\"",
        "test_ready_rechecks_lease_after_loading_evidence",
    ),
}

if __name__ == "__main__":
    raise SystemExit(main(mutants=MUTANTS,
                          test_file="tests/sentinel/test_rolling_snapshot_jobs.py",
                          runner="tools.sentinel_rolling_job_falsifiers"))
