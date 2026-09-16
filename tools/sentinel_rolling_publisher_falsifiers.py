"""Guard-removal checks for direct comparison publication."""
from tools.sentinel_rolling_storage_falsifiers import main

MUTANTS = {
    "independent_coverage": (
        "sentinel.feed.rolling_builder", "coverage_proof = coverage.require_complete(**bounds)",
        "coverage_proof = {}", "test_bad_source_never_publishes[missing_equity]"),
    "comparison_cas": (
        "sentinel.feed.rolling_publisher",
        "if attempt is None or attempt[0] != (latest[0] if latest else None):", "if False:",
        "test_compare_and_swap_loser_preserves_winner"),
    "legacy_cas": (
        "sentinel.feed.rolling_publisher",
        'if _legacy_version(conn) != request.expected_publication_version:\n'
        '        raise ComparisonRefused("legacy publication changed during preparation")',
        'if False:\n        raise ComparisonRefused("legacy publication changed during preparation")',
        "test_legacy_publication_change_invalidates_ready"),
    "monotonic_frontier": (
        "sentinel.feed.rolling_publisher", "if latest is not None and request.window.end < latest[1]:",
        "if False:", "test_old_comparison_cannot_replace_newer_frontier"),
    "post_validation_lease": (
        "sentinel.feed.rolling_publisher",
        "jobs._owned(conn, lease)  # Recheck time after proof loading, before visibility.",
        "pass  # mutated", "test_post_validation_lease_is_rechecked"),
    "reference_null_semantics": (
        "sentinel.feed.rolling_source", "if self._tickers_json(self._ticker_keys) != self.tickers:",
        "if False:", "test_corroboration_refuses_changed_ticker_fields"),
    "source_refresh": (
        "sentinel.feed.rolling_source", "if checked.refreshed != captured.refreshed:",
        "if False:", "test_corroboration_refuses_changed_refresh"),
    "benchmark_reobservation": (
        "sentinel.feed.rolling_source", "if self._sfp() != self.sfp:",
        "if False:", "test_corroboration_refuses_changed_benchmark"),
    "partition_refresh": (
        "sentinel.feed.rolling_source",
        "if len({s.refreshed for s in self.snapshots if s.table == sharadar.SEP}) != 1:",
        "if False:", "test_preflight_refuses_mixed_sep_refreshes"),
    "closed_target": (
        "sentinel.feed.rolling_source", "if str(self.window.end) > calendar.latest_closed_session():",
        "if False:", "test_source_rejects_unclosed_target"),
    "benchmark_keys": (
        "sentinel.feed.rolling_builder", "if set(by_key) != expected:",
        "if False:", "test_benchmark_key_guard_is_exact"),
    "catalog_immutable": (
        "sentinel.feed.rolling_schema",
        "RAISE EXCEPTION 'snapshot evidence is immutable';", "RETURN OLD;",
        "test_comparison_catalog_is_immutable"),
    "retry_after": (
        "sentinel.feed.rolling_publisher",
        "delay = max(1, math.ceil(exc.delay)) if isinstance(exc, sharadar.SharadarRetryDeferred) else 10",
        "delay = 1", "test_retry_after_is_not_shortened"),
}

if __name__ == "__main__":
    raise SystemExit(main(mutants=MUTANTS,
                          test_file="tests/sentinel/test_rolling_snapshot_publisher.py",
                          runner="tools.sentinel_rolling_publisher_falsifiers"))
