"""Kill targeted continuity/checkpoint mutants without editing source files."""
from tools.sentinel_rolling_storage_falsifiers import main

MUTANTS = {
    "archive_binding": (
        "sentinel.rolling_daily_checkpoint", '    require_input(conn, checkpoint)', '    pass',
        "test_changed_input_archive_refuses"),
    "archive_append": (
        "sentinel.rolling_daily_checkpoint",
        'if result.rowcount != 1:\n        raise Refused("DAILY_INPUT_ARCHIVE_ALREADY_EXISTS")',
        'if False:\n        raise Refused("DAILY_INPUT_ARCHIVE_ALREADY_EXISTS")',
        "test_input_archive_cannot_be_overwritten"),
    "overlap_keys": (
        "sentinel.core.rolling_continuity",
        'if (left is None or right is None\n                    or (left.session, left.security_id) != (right.session, right.security_id)):',
        'if False:', "test_overlap_guard_distinguishes_economic_changes[keys-IDENTITY_KEYS]"),
    "raw_economics": (
        "sentinel.core.rolling_continuity",
        'if a != b:\n                raise RollingContinuityRefused("OVERLAP_RAW_ECONOMICS_CHANGED: " + left.security_id)',
        'if False:\n                raise RollingContinuityRefused("OVERLAP_RAW_ECONOMICS_CHANGED: " + left.security_id)',
        "test_overlap_guard_distinguishes_economic_changes[raw-RAW_ECONOMICS]"),
    "signal_rebase": (
        "sentinel.core.rolling_continuity",
        'if ratio <= 0 or factors.setdefault(left.security_id, ratio) != ratio:',
        'if False:', "test_overlap_guard_distinguishes_economic_changes[signal-NONUNIFORM_SIGNAL]"),
    "benchmark_rebase": (
        "sentinel.core.rolling_continuity",
        'if ratio is None or ratio <= 0 or scales.setdefault(field, ratio) != ratio:',
        'if False:', "test_overlap_guard_distinguishes_economic_changes[spy-NONUNIFORM_BENCHMARK]"),
    "bil_raw": (
        "sentinel.core.rolling_continuity",
        'if a != b:\n                raise RollingContinuityRefused("OVERLAP_BIL_RAW_ECONOMICS_CHANGED")',
        'if False:\n                raise RollingContinuityRefused("OVERLAP_BIL_RAW_ECONOMICS_CHANGED")',
        "test_overlap_guard_distinguishes_economic_changes[bil-BIL_RAW_ECONOMICS]"),
    "reference_metadata": (
        "sentinel.core.rolling_continuity",
        'if meta.get(sid) != value or sectors.get(sid) != old_sectors[sid]:', 'if False:',
        "test_historical_economic_changes_refuse_without_advancing[sector]"),
    "historical_actions": (
        "sentinel.core.rolling_continuity", 'if actions != old_actions:', 'if False:',
        "test_historical_economic_changes_refuse_without_advancing[actions]"),
    "prior_state_binding": (
        "sentinel.core.history", 'or checked.prior_state_sha256 != prior_state_sha256', 'or False',
        "test_proof_cannot_admit_a_different_prior_state"),
    "checkpoint_signature": (
        "sentinel.rolling_daily_checkpoint",
        'or not hmac.compare_digest(str(raw["hmac_sha256"]), signature(raw["checkpoint"]))', 'or False',
        "test_changed_signed_checkpoint_refuses"),
    "checkpoint_cas": (
        "sentinel.rolling_daily_checkpoint",
        'if result.rowcount != 1:\n        raise Refused("DAILY_CHECKPOINT_CAS_CHANGED")',
        'if False:\n        raise Refused("DAILY_CHECKPOINT_CAS_CHANGED")',
        "test_stale_checkpoint_cannot_overwrite_current"),
    "final_deadline": (
        "sentinel.rolling_daily", '                initial._timing(conn, result.session)\n',
        '                pass\n', "test_final_write_rechecks_authority[deadline]"),
    "final_backup": (
        "sentinel.rolling_daily",
        '                backup_runtime_authority.require(conn, operation="rolling daily checkpoint commit")',
        '                pass', "test_final_write_rechecks_authority[backup]"),
    "read_only_restart": (
        "sentinel.rolling_daily", 'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY',
        'SET TRANSACTION ISOLATION LEVEL READ COMMITTED READ WRITE',
        "test_checkpoint_reads_only_current_suffix_in_read_only_transaction"),
}

if __name__ == "__main__":
    raise SystemExit(main(mutants=MUTANTS, test_file="tests/sentinel/test_rolling_daily.py",
                          runner="tools.sentinel_rolling_daily_falsifiers"))
