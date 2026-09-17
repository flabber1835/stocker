"""Require targeted test failures when cold-start admission guards are broken."""
from tools.sentinel_rolling_storage_falsifiers import main

MUTANTS = {
    "spy_transport_domain": (
        "sentinel.rolling_initialization",
        "spy_closeadj=tuple(row.spy_total_return for row in material.benchmarks)",
        "spy_closeadj=tuple(row.bil_close_adjusted for row in material.benchmarks)",
        "test_composed_input_keeps_spy_equity_and_bil_domains_separate",
    ),
    "bil_spy_contamination": (
        "sentinel.rolling_initialization",
        "row.bil_close_adjusted, row.bil_close_unadjusted)",
        "row.spy_total_return, row.bil_close_unadjusted)",
        "test_composed_input_keeps_spy_equity_and_bil_domains_separate",
    ),
    "bil_raw_domain": (
        "sentinel.rolling_initialization",
        "row.bil_close_adjusted, row.bil_close_unadjusted)",
        "row.bil_close_adjusted, row.bil_close_signal)",
        "test_composed_input_keeps_spy_equity_and_bil_domains_separate",
    ),
    "bil_previous_session": (
        "sentinel.rolling_initialization",
        "defensive_previous_bar=defensive(material.benchmarks[-2])",
        "defensive_previous_bar=defensive(material.benchmarks[-1])",
        "test_composed_input_keeps_spy_equity_and_bil_domains_separate",
    ),
    "partial_state": (
        "sentinel.rolling_checkpoint", "if lineage_names(conn):", "if False:",
        "test_partial_state_is_never_interpreted_as_fresh[catchup]",
    ),
    "execution_history": (
        "sentinel.rolling_checkpoint", "if cur.fetchone()[0]:", "if False:",
        "test_existing_execution_history_prevents_new_genesis",
    ),
    "orphaned_strategy_evidence": (
        "sentinel.rolling_checkpoint", "if cur.fetchone()[0]:",
        'if cur.fetchone()[0] and table != "sentinel_trial_strategy_evidence":',
        "test_orphaned_strategy_evidence_prevents_new_genesis",
    ),
    "checkpoint_authentication": (
        "sentinel.rolling_checkpoint",
        'if not hmac.compare_digest(str(raw["hmac_sha256"]), _signature(payload)):', "if False:",
        "test_checkpoint_authentication_detects_valid_json_mutations[input_value]",
    ),
    "checkpoint_config": (
        "sentinel.rolling_checkpoint",
        "if (checkpoint.observation_id != observation_id or checkpoint.starting_cash != starting_cash",
        "if (False",
        "test_checkpoint_cannot_change_capital_or_observation[starting_cash-200000]",
    ),
    "extra_lineage": (
        "sentinel.rolling_checkpoint",
        "if lineage_names(conn) != {CURSOR, store._genesis_name, store._name(checkpoint.session)}:",
        "if False:", "test_extra_shadow_lineage_prevents_checkpoint_admission",
    ),
    "atomic_genesis": (
        "sentinel.rolling_initialization",
        'conn, observation_id=context["observation_id"], commit_genesis=False)',
        'conn, observation_id=context["observation_id"], commit_genesis=True)',
        "test_failed_first_state_leaves_no_partial_seed[genesis]",
    ),
    "publication_review": (
        "sentinel.rolling_initialization",
        'if shadow_runtime._data_publication_subject_sha256(pub, pub.window_end) != context["runtime"].get(',
        'if False and shadow_runtime._data_publication_subject_sha256(pub, pub.window_end) != context["runtime"].get(',
        "test_unreviewed_publication_cannot_seed",
    ),
    "acquisition_strategy": (
        "sentinel.rolling_initialization",
        'if request["strategy_sha256"] != digest(context["strategy"]):', "if False:",
        "test_acquisition_bound_to_another_strategy_cannot_seed",
    ),
    "final_opening_deadline": (
        "sentinel.rolling_initialization",
        "                _timing(conn, result.session)  # Final writes cannot extend the opening deadline.",
        "                pass",
        "test_final_checkpoint_write_cannot_extend_opening_deadline",
    ),
    "consistent_read_only_restart": (
        "sentinel.rolling_initialization",
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",
        "SET TRANSACTION ISOLATION LEVEL READ COMMITTED READ WRITE",
        "test_restart_reads_a_consistent_read_only_snapshot",
    ),
    "rollback_version": (
        "sentinel.feed.operational_snapshot",
        "version = previous.version + 1 if previous else 1",
        "version = conn.execute(\"SELECT nextval(pg_get_serial_sequence('sentinel_corpus_publications','version'))\").fetchone()[0]",
        "test_failed_publication_does_not_burn_a_committed_version",
    ),
}

if __name__ == "__main__":
    raise SystemExit(main(mutants=MUTANTS, test_file="tests/sentinel/test_rolling_initialization.py",
                          runner="tools.sentinel_rolling_initialization_falsifiers"))
