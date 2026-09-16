"""Remove snapshot input guards and require genuine targeted assertion failures."""
from tools.sentinel_rolling_storage_falsifiers import main

MUTANTS = {
    "snapshot_binding": (
        "sentinel.core.rolling_inputs",
        "if self.manifest.snapshot_id != snapshot_id:", "if False:",
        "test_wrong_snapshot_and_unknown_reference_schema_refuse",
    ),
    "validation_binding": (
        "sentinel.core.rolling_inputs",
        'or validation.get("snapshot_id") != snapshot_id', 'or False',
        "test_reference_validation_must_name_this_snapshot[snapshot]",
    ),
    "metadata_conflict": (
        "sentinel.core.rolling_inputs", "if len(values) > 1:", "if False:",
        "test_conflicting_metadata_does_not_depend_on_source_order",
    ),
    "terminal_identity": (
        "sentinel.core.rolling_inputs", "if (result.unresolved or not result.conservation_holds()",
        "if (False or not result.conservation_holds()",
        "test_unresolved_terminal_cannot_be_excluded_by_bounded_price_absence",
    ),
    "returning_anchor": (
        "sentinel.core.rolling_inputs",
        'if bar.security_id not in known and meta[bar.security_id].first_session != session:',
        'if False:', "test_returning_security_does_not_get_an_invented_first_observation",
    ),
    "equity_signal": (
        "sentinel.core.rolling_inputs", "signal_close=row.close_signal)",
        "signal_close=row.close_unadjusted)", "test_source_bundle_feeds_adapter_without_legacy_publication",
    ),
    "spy_warmup": (
        "sentinel.core.rolling_inputs", "str(row.session): row.spy_total_return for row in benchmarks",
        "str(row.session): row.bil_close_adjusted for row in benchmarks",
        "test_empty_legacy_corpus_forms_canonical_initial_pending_book",
    ),
    "symbol_ambiguity": (
        "sentinel.core.rolling_inputs", "if active:", "if False:",
        "test_ambiguous_active_symbol_refuses_even_when_metadata_agrees",
    ),
    "future_actions": (
        "sentinel.core.rolling_inputs",
        'or not "1900-01-01" <= day <= str(self.manifest.window.end)', 'or False',
        "test_reference_actions_cannot_claim_future_information",
    ),
    "restored_content": (
        "sentinel.core.rolling_inputs", "    rolling_store.verify_content(conn, candidate_id)",
        "    pass", "test_cold_start_verifies_restored_payload_not_only_manifest",
    ),
}

if __name__ == "__main__":
    raise SystemExit(main(mutants=MUTANTS, test_file="tests/sentinel/test_rolling_inputs.py",
                          runner="tools.sentinel_rolling_inputs_falsifiers"))
