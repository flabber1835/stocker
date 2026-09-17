"""Remove execution-input guards in isolated processes, never on disk."""
from tools.sentinel_rolling_storage_falsifiers import main

MUTANTS = {
    "current_decision_marks": ("sentinel.execution.feed_inputs",
        'if str(session) != pub.window_end:', 'if False:',
        "test_readers_bind_snapshot_raw_marks_and_leave_legacy_readers_closed"),
    "cash_history_coverage": ("sentinel.execution.feed_cash",
        'if str(first) < str(self.refs.manifest.window.start) or str(through) > self.pub.window_end:', 'if False:',
        "test_snapshot_dividend_inputs_reuse_entitlement_domains"),
    "integrity_is_not_version_dispatch": ("sentinel.execution.feed_inputs",
        'return publication.require_current(conn)\n    except publication.CorpusIncoherent as exc:\n        if str(exc) != "ROLLING_SNAPSHOT_REQUIRES_VERSIONED_READER":',
        'return publication.require_current(conn)\n    except publication.CorpusIncoherent as exc:\n        if False:',
        "test_corrupt_receipt_cannot_trigger_a_permissive_reader_fallback"),
    "raw_close_domain": ("sentinel.execution.feed_inputs",
        'SELECT security_id,ticker,close_unadjusted FROM sentinel_snapshot_bars',
        'SELECT security_id,ticker,close_signal FROM sentinel_snapshot_bars',
        "test_readers_bind_snapshot_raw_marks_and_leave_legacy_readers_closed"),
    "complete_marks": ("sentinel.execution.feed_inputs",
        'if row is None or set(security_ids) - set(marks):', 'if row is None:',
        "test_readers_bind_snapshot_raw_marks_and_leave_legacy_readers_closed"),
    "next_session_only": ("sentinel.execution.feed_inputs",
        'if requested > end and requested != calendar.next_session(end):', 'if False:',
        "test_next_open_resolver_is_bounded_and_historical_dates_do_not_borrow_extension"),
    "active_listing_only": ("sentinel.execution.feed_inputs",
        'row.get("isdelisted") == "N" and ', '',
        "test_next_open_identity_never_extends_a_delisted_or_reused_symbol[delisted]"),
    "successor_conflict": ("sentinel.execution.feed_inputs",
        'and not competing:', ':',
        "test_next_open_identity_never_extends_a_delisted_or_reused_symbol[successor]"),
    "shadow_only": ("sentinel.execution.feed_inputs",
        'if is_rolling(pub) and not dual_mode:', 'if False:',
        "test_rolling_preparation_refuses_non_shadow_mode_before_broker_read"),
    "historical_action_coverage": ("sentinel.execution.feed_actions",
        'predecessor < refs.manifest.window.start or ', '',
        "test_action_reader_requires_retained_predecessor_and_never_reads_legacy_rows"),
    "scalar_bil_terms": ("sentinel.execution.feed_actions",
        'defensive_rows=defensive, dispositions=dispositions', 'defensive_rows=[], dispositions=dispositions',
        "test_snapshot_actions_preserve_scalar_and_material_reconciliation_policy"),
}

if __name__ == "__main__":
    raise SystemExit(main(mutants=MUTANTS, test_file="tests/sentinel/test_rolling_paper_inputs.py",
                         runner="tools.sentinel_rolling_paper_falsifiers"))
