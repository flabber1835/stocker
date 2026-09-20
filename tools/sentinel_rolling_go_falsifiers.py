"""Run the focused rolling GO guard-removal tests in isolated child processes."""
from tools.sentinel_rolling_storage_falsifiers import main

MUTANTS = {
    "read_only_snapshot": (
        "sentinel.feed.rolling_go_inputs", '    binding = snapshots._bound(conn, pub)',
        '    require_schemas(conn)\n    binding = snapshots._bound(conn, pub)',
        "test_readiness_reads_snapshot_without_legacy_tables"),
    "existing_book": (
        "sentinel.feed.rolling_go_inputs", "        require_first_deployment(conn)", "        pass",
        "test_failed_attempt_book_is_preserved_and_not_adopted"),
    "caller_target": (
        "sentinel.feed.rolling_go_inputs", "if target_session != snapshots.source_final_session():", "if False:",
        "test_source_final_target_cannot_be_selected_by_caller"),
    "strategy_request": (
        "sentinel.feed.rolling_go_inputs", 'if request["strategy_sha256"] != digest(strategy):', 'if False:',
        "test_strategy_request_is_bound_to_current_source"),
    "current_frontier": (
        "sentinel.feed.rolling_go_inputs", "PASS if material.session == target else FAIL", "PASS",
        "test_readiness_refuses_stale_frontier"),
    "current_domains": (
        "sentinel.feed.rolling_go_inputs", "PASS if share >= MIN_FRONTIER_DOMAIN_COVERAGE else FAIL", "PASS",
        "test_readiness_checks_canonical_current_inputs[domain]"),
    "current_population": (
        "sentinel.feed.rolling_go_inputs", "PASS if frontier and frontier >= baseline * MIN_FRONTIER_POPULATION_RATIO else FAIL", "PASS",
        "test_readiness_checks_canonical_current_inputs[population]"),
    "warmup_domains": (
        "sentinel.feed.rolling_go_inputs", "PASS if share >= .9 else FAIL", "PASS",
        "test_readiness_checks_canonical_current_inputs[warmup]"),
    "issuer_evidence": (
        "sentinel.feed.rolling_go_inputs", "PASS if summary.related_issuers else FAIL", "PASS",
        "test_readiness_checks_canonical_current_inputs[issuer]"),
    "bil_domains": (
        "sentinel.feed.rolling_go_inputs", "PASS if defensive_complete else FAIL", "PASS",
        "test_readiness_checks_canonical_current_inputs[bil]"),
    "pin_exclusion": (
        "sentinel.feed.rolling_go_health", '"publication_pin_excludes_writers": shared and not acquired',
        '"publication_pin_excludes_writers": True', "test_database_health_refuses_a_missing_publication_pin"),
}

if __name__ == "__main__":
    raise SystemExit(main(mutants=MUTANTS, test_file="tests/sentinel/test_rolling_go_inputs.py",
                          runner="tools.sentinel_rolling_go_falsifiers"))
