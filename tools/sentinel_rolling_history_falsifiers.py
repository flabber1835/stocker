"""Isolated guard-removal checks against disposable PostgreSQL test databases.

Uses the established subprocess mutation runner. Each child replaces code only
in its own module namespace; the checkout and economic fixtures never change.
"""
from tools.sentinel_rolling_storage_falsifiers import main

TEST = 'tests/sentinel/test_rolling_history_retention.py'
MUTANTS = {
    'idle_drain_integration': (
        'sentinel.shadow_service', 'maintenance_pending = retention.idle_pass(config.database_url)',
        'maintenance_pending = False', 'test_shadow_idle_loop_drains_then_yields_without_reacquisition'),
    'coverage_gap': (
        'sentinel.feed.action_history', 'if prior and manifest.window.start > prior[1]:', 'if False:',
        'test_advance_cannot_bridge_unobserved_action_interval'),
    'retirement_writer_ownership': (
        'sentinel.feed.retention_schema', "IN (1579621904,1579663541)) <> 2 THEN", "IN (1579621904,1579663541)) < 0 THEN",
        'test_retirement_requires_shared_writer_ownership'),
    'historical_correction': (
        'sentinel.feed.action_history', 'if changed:', 'if False:',
        'test_out_of_window_correction_is_scoped_and_original_evidence_immutable'),
    'missing_action_evidence': (
        'sentinel.feed.action_history', 'LEFT JOIN sentinel_action_history h', 'JOIN sentinel_action_history h',
        'test_missing_retained_event_cannot_become_no_action'),
    'duplicate_scalar': (
        'sentinel.feed.action_history', 'for e in buckets["scalar"]:', 'for e in buckets["scalar"] * 2:',
        'test_old_command_and_bil_actions_survive_real_retirement_and_restart'),
    'initial_coverage': (
        'sentinel.feed.action_history', 'start < row[0] or end < start', 'end < start',
        'test_history_outside_initial_basis_is_not_fabricated'),
    'live_generation_pin': (
        'sentinel.feed.retention_schema', 'IF cardinality(sentinel_snapshot_pins(NEW.candidate_id))<>0 THEN',
        'IF FALSE THEN', 'test_current_generation_cannot_be_retired_even_by_direct_sql'),
    'active_job_pin': (
        'sentinel.feed.retention_schema', "state NOT IN ('REFUSED','ABORTED','PUBLISHED')", 'FALSE',
        'test_active_job_and_worker_scratch_survive_maintenance'),
    'read_only_generation_pin': (
        'sentinel.feed.rolling_store', 'cur.execute("SELECT pg_try_advisory_xact_lock_shared(%s)", (CORPUS_LOCK_KEY,))',
        'cur.execute("SELECT TRUE")', 'test_explicit_read_only_generation_reader_pins_until_transaction_ends'),
    'rehydration_identity': (
        'sentinel.feed.retention_schema', "AND encode(sha256(convert_to(NEW.restored_bytes,'UTF8')),'hex')=OLD.evidence_sha256",
        'AND TRUE', 'test_retained_payload_cannot_be_rehydrated_under_different_identity'),
    'incremental_cursor': (
        'sentinel.feed.retention', 'cursor = previous[0] if previous else None', 'cursor = None',
        'test_pinned_candidates_do_not_starve_retirement'),
    'unattended_publication_cleanup': (
        'sentinel.feed.rolling_publisher', 'retention.maintain(conn)', 'None',
        'test_repeated_publications_bound_bulk_storage_and_preserve_failed_attempts'),
}


if __name__ == '__main__':
    raise SystemExit(main(mutants=MUTANTS, test_file=TEST,
                         runner='tools.sentinel_rolling_history_falsifiers'))
