"""Require targeted tests to detect broken renewal and resume guards."""
import argparse
from pathlib import Path
import subprocess
import sys

from tools.sentinel_rolling_storage_falsifiers import child

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
MUTANTS = {
    "hidden_formation_progress": (
        "sentinel_go_feed_progress", '"rolling_comparison_publication", "historical_formation",', '"rolling_comparison_publication",',
        "test_real_formation_protocol_reaches_host"),
    "shadow_claim_expiry_terminal": (
        "sentinel.feed.rolling_jobs", "if state and state[0] not in TERMINAL and not state[1]:", "if False:",
        "test_expired_deadline_cannot_be_extended_or_reclaimed"),
    "shadow_preflight_budget_reset": (
        "sentinel.shadow_service", "acquisition_deadline=acquisition_deadline", "acquisition_deadline=shadow_budget.cutoff()",
        "test_rolling_preflight_consumes_original_attempt_budget"),
    "shadow_one_hour": (
        "sentinel.rolling_runtime", "absolute_deadline=acquisition_deadline", "absolute_deadline=None",
        "test_daily_service_uses_its_two_hour_budget[None]"),
    "shadow_terminal_deadline": (
        "sentinel.shadow_worker", "(JobWaiting, JobDeadlineExceeded)", "(JobWaiting,)",
        "test_expired_shadow_worker_exits_availability_without_work"),
    "shadow_spawn_deadline_reset": (
        "sentinel.shadow_supervisor", "stdin=subprocess.DEVNULL, env=worker_env", "stdin=subprocess.DEVNULL",
        "test_shadow_spawn_carries_exact_cutoff_and_overwrites_stale_parent"),
    "silent_storage_scan": (
        "sentinel.feed.rolling_store", "if index % BATCH_SIZE == 0:", "if False:",
        "test_real_work_renews_only_live_owned_job[go-seal-None]"),
    "silent_action_history": (
        "sentinel.feed.action_history", "rolling_work.checkpoint()\n        symbols =",
        "pass\n        symbols =",
        "test_real_work_renews_only_live_owned_job[go-publication-None]"),
    "unbounded_final_command": (
        "sentinel_host_command", "proc.communicate(timeout=timeout)", "proc.communicate(timeout=None)",
        "test_final_runners_enforce_timeout_and_kill_descendants[run]"),
    "unhealthy_panel_handoff": (
        "sentinel_go_post_validate", 'or state["Health"].get("Status") != "healthy"', "or False",
        "test_panel_wait_and_actual_health_precede_handoff[unhealthy-True-False-False]"),
    "leaked_worker_scope": (
        "sentinel.feed.rolling_work", "_HEARTBEAT.reset(token)", "pass",
        "test_nested_work_scope_restores_previous_owner_and_cleans_up"),
    "inner_one_hour": (
        "sentinel_go_24x7_entry",
        "        absolute_deadline=rolling_go_inputs.deadline_from_host(\n"
        "            os.environ.get('SENTINEL_GO_PREPARATION_DEADLINE')),\n", "",
        "test_slow_preparation_and_backup_share_original_host_deadline[False]"),
    "deadline_reset": (
        "sentinel_go_deadline",
        "return datetime.fromtimestamp(end, timezone.utc).isoformat()",
        "return datetime.fromtimestamp(time.time() + 7200, timezone.utc).isoformat()",
        "test_slow_preparation_and_backup_share_original_host_deadline[False]"),
    "hidden_builder_progress": (
        "sentinel_go_feed_progress",
        '"rolling_identity", "rolling_normalization", "rolling_seal",',
        '"rolling_identity", "rolling_normalization",',
        "test_real_builder_protocol_reaches_host[rolling_seal]"),
    "terminal_horizon": (
        "sentinel.feed.rolling_publisher", "if horizon and remaining > 2:", "if False:",
        "test_go_renews_after_real_retained_acquisition_without_redownload[acquiring]"),
    "wrong_failure_type": (
        "sentinel_go_backup_retry", 'or value.get("error_type") != "BackupHorizonExceeded"', 'or False',
        "test_horizon_text_without_exact_resumable_signal_never_renews[changes0]"),
    "resume_expiry": (
        "sentinel.feed.operational_snapshot", 'or state["remaining_seconds"] <= 0', 'or False',
        "test_backup_resume_pins_job_and_deadline_without_new_enqueue[expired]"),
    "resume_request": (
        "sentinel.feed.operational_snapshot",
        'or jobs.PreparationRequest.model_validate(state["request"]) != request', 'or False',
        "test_backup_resume_pins_job_and_deadline_without_new_enqueue[different-request]"),
    "renewal_deadline": (
        "sentinel_go_backup_retry", "if command_timeout(1) <= 0:", "if False:",
        "test_one_deadline_includes_renewal_and_prevents_restart"),
}
TESTS = {
    "hidden_formation_progress": "tests/scripts/test_feed_progress.py",
    "shadow_claim_expiry_terminal": "tests/sentinel/test_rolling_snapshot_jobs.py",
    "shadow_preflight_budget_reset": "tests/sentinel/test_shadow_service.py",
    "shadow_one_hour": "tests/sentinel/test_shadow_acquisition_budget.py",
    "shadow_terminal_deadline": "tests/sentinel/test_supervisor_timing_admission.py",
    "shadow_spawn_deadline_reset": "tests/sentinel/test_supervisor_timing_admission.py",
    "silent_storage_scan": "tests/sentinel/test_rolling_work_liveness.py",
    "silent_action_history": "tests/sentinel/test_rolling_work_liveness.py",
    "unbounded_final_command": "tests/scripts/test_host_command_deadline.py",
    "unhealthy_panel_handoff": "tests/production_composition/test_runtime_handoff_atomicity.py",
    "leaked_worker_scope": "tests/sentinel/test_rolling_work_liveness.py",
    "inner_one_hour": "tests/sentinel/test_go_preparation_deadline.py",
    "deadline_reset": "tests/sentinel/test_go_preparation_deadline.py",
    "hidden_builder_progress": "tests/scripts/test_feed_progress.py",
    "terminal_horizon": "tests/sentinel/test_acquisition_resumption.py",
    "wrong_failure_type": "tests/sentinel/test_go_backup_refresh.py",
    "resume_expiry": "tests/sentinel/test_operational_snapshot.py",
    "resume_request": "tests/sentinel/test_operational_snapshot.py",
    "renewal_deadline": "tests/sentinel/test_go_backup_refresh.py",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", choices=MUTANTS)
    args = parser.parse_args()
    if args.child:
        return child(args.child, mutants=MUTANTS, test_file=TESTS[args.child])
    failed = []
    for name in MUTANTS:
        result = subprocess.run([sys.executable, "-m", __spec__.name, "--child", name],
                                capture_output=True, text=True, timeout=180)
        killed = result.returncode == 1 and "1 failed" in result.stdout
        print(name + (": KILLED" if killed else ": NOT PROVED"), flush=True)
        if not killed:
            print(result.stdout + result.stderr, flush=True)
            failed.append(name)
    return bool(failed)


if __name__ == "__main__":
    raise SystemExit(main())
