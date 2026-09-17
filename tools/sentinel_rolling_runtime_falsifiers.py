"""Falsify rolling runtime authority without editing source on disk."""
from tools.sentinel_rolling_storage_falsifiers import main

MUTANTS = {
    "signature": ("sentinel.rolling_authority", "if not hmac.compare_digest(", "if False and not hmac.compare_digest(",
                  "test_authority_tamper_refuses_runtime_status[signature]"),
    "checkpoint_binding": ("sentinel.rolling_authority",
        "authority.checkpoint_sha256 != digest(checkpoint.model_dump(by_alias=True))", "False",
        "test_authority_tamper_refuses_runtime_status[checkpoint]"),
    "runtime_binding": ("sentinel.rolling_authority",
        "authority.runtime_sha256 != digest(checkpoint.runtime_identity)", "False",
        "test_authority_tamper_refuses_runtime_status[runtime]"),
    "committed_timing": ("sentinel.rolling_authority",
        '        shadow._timing_proof(value.timing, decision_session=value.session, committed=True,\n'
        '                             where="rolling runtime post-commit timing")', '        pass',
        "test_authority_tamper_refuses_runtime_status[timing]"),
    "authority_chain": ("sentinel.rolling_runtime", "if (latest.previous_authority_sha256", "if False and (latest.previous_authority_sha256",
        "test_authority_tamper_refuses_runtime_status[chain]"),
    "predecessor": ("sentinel.rolling_runtime", "if (previous is None or", "if False and (previous is None or",
        "test_daily_cannot_skip_missing_predecessor_authority"),
    "candidate_first": ("sentinel.rolling_runtime", "                        if attested is None:", "                        if False:",
        "test_unattested_candidate_cannot_be_skipped_by_new_publication"),
    "backup": ("sentinel.rolling_runtime",
        'backup_runtime_authority.require(conn, operation="rolling runtime attestation")', 'None',
        "test_backup_refusal_after_candidate_commit_cannot_issue_authority"),
    "publication_pin": ("sentinel.rolling_runtime",
        "with snapshots.pinned(conn, commit=False) as (pub, _binding):",
        "with __import__('contextlib').nullcontext((inputs.current(conn), None)) as (pub, _binding):",
        "test_publication_and_writer_locks_span_candidate_and_authority_commits"),
    "writer_lock": ("sentinel.rolling_runtime", "with journal.writer_lock(conn):", "with __import__('contextlib').nullcontext():",
        "test_publication_and_writer_locks_span_candidate_and_authority_commits"),
    "no_legacy_fallback": ("sentinel.rolling_runtime", "if not rolling and origin.read(conn) is not None:", "if False:",
        "test_rolling_book_cannot_dispatch_back_to_legacy_publication"),
    "no_legacy_recovery": ("sentinel.shadow_recovery",
        '    if "input_contract" in retained:\n        # Rolling checkpoints cannot be adopted by legacy segment recovery.',
        '    if False:\n        # Rolling checkpoints cannot be adopted by legacy segment recovery.',
        "test_production_worker_gap_refuses_without_legacy_catchup"),
}

if __name__ == "__main__":
    raise SystemExit(main(mutants=MUTANTS, test_file="tests/sentinel/test_rolling_runtime.py",
                         runner="tools.sentinel_rolling_runtime_falsifiers"))
