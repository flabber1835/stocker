"""Catalog witnesses for retained evidence and controlled retirement."""
from sentinel.feed import rolling_catalog, rolling_job_catalog

COLUMNS = {
    "sentinel_action_history": {
        "session": ("date", True), "publication_version": ("bigint", True),
        "payload_sha256": ("text", True), "payload": ("jsonb", True)},
    "sentinel_action_coverage": {
        "publication_version": ("bigint", True), "basis": ("date", True),
        "through": ("date", True), "payload_sha256": ("text", True), "payload": ("jsonb", True)},
    "sentinel_snapshot_retirements": {
        "candidate_id": ("uuid", True), "retired_at": ("timestamp with time zone", True)},
    "sentinel_snapshot_workers": {"owner": ("uuid", True), "job_id": ("uuid", True)},
    "sentinel_snapshot_maintenance": {
        "id": ("boolean", True), "updated_at": ("timestamp with time zone", True),
        "diagnostic": ("jsonb", True)},
}
PRIMARY_KEYS = {name: f"primary key ({next(iter(columns))})" for name, columns in COLUMNS.items()}
TRIGGERS = {name: {
    "snapshot_immutable": ("before delete or update", "for each row", "execute function sentinel_snapshot_immutable()"),
    "snapshot_no_truncate": ("before truncate", "for each statement", "execute function sentinel_snapshot_immutable()"),
} for name in COLUMNS if name != "sentinel_snapshot_maintenance"}
TRIGGERS["sentinel_snapshot_retirements"]["retire_guard"] = (
    "before insert", "for each row", "execute function sentinel_snapshot_retire_guard()")
CONSTRAINTS = {
    "sentinel_action_history": (("f", ("foreign key (publication_version)", "sentinel_corpus_publications")),),
    "sentinel_action_coverage": (("f", ("foreign key (publication_version)", "sentinel_corpus_publications")),),
    "sentinel_snapshot_retirements": (("f", ("foreign key (candidate_id)", "sentinel_price_candidates")),),
    "sentinel_snapshot_workers": (("f", ("foreign key (job_id)", "sentinel_snapshot_jobs")),),
}

# The later migration intentionally narrows these existing trigger operations.
rolling_catalog.COLUMNS["sentinel_snapshot_evidence"].update(
    payload=("jsonb", False), restored_bytes=("text", False))
for table in ("sentinel_snapshot_bars", "sentinel_snapshot_benchmarks"):
    rolling_catalog.TRIGGERS[table]["snapshot_immutable"] = (
        "before delete or update", "for each row", "execute function sentinel_snapshot_payload_guard()")
rolling_catalog.TRIGGERS["sentinel_snapshot_evidence"]["snapshot_immutable"] = (
    "before delete or update", "for each row", "execute function sentinel_snapshot_evidence_guard()")
rolling_catalog.TRIGGERS["sentinel_price_candidates"]["snapshot_live_candidate"] = (
    "before insert", "for each row", "execute function sentinel_snapshot_live_candidate()")
rolling_job_catalog.TRIGGERS["sentinel_snapshot_jobs"]["snapshot_live_job"] = (
    "before insert or update", "for each row", "execute function sentinel_snapshot_live_job()")
