"""Require targeted tests to detect broken renewal and resume guards."""
import argparse
from pathlib import Path
import subprocess
import sys

from tools.sentinel_rolling_storage_falsifiers import child

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
MUTANTS = {
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
