"""Break acquisition guards in memory; require behavioral failures, not errors."""
import argparse
import subprocess
import sys

from tools.sentinel_rolling_storage_falsifiers import child

MUTANTS = {
    "first_pending_aborts": ("sentinel.feed.export_readiness",
        "pending = pending or exc", "raise",
        "test_all_exports_requested_before_pending_is_returned[pending0]"),
    "pending_accepted": ("sentinel.feed.export_readiness",
        "raise pending", "return snapshots",
        "test_all_exports_requested_before_pending_is_returned[pending0]"),
    "retry_time_ignored": ("sentinel.feed.preparation_wait",
        'min(state["retry_seconds"], state["remaining_seconds"], 10.0)', '0',
        "test_wait_respects_retry_time_and_reuses_exact_job"),
    "deadline_ignored": ("sentinel.feed.preparation_wait",
        'if state["remaining_seconds"] <= 0:', 'if False:',
        "test_deadline_expires_without_retrying_or_renewing"),
    "transaction_left_open": ("sentinel.feed.preparation_wait",
        'conn.rollback()  # No open transaction while sleeping.', 'pass',
        "test_wait_respects_retry_time_and_reuses_exact_job"),
    "integrity_retried": ("sentinel.feed.preparation_wait",
        'jobs.JobWaiting):', 'jobs.JobWaiting, ValueError):',
        "test_integrity_failure_is_not_retried_even_if_job_was_waiting"),
    "go_wait_bypassed": ("sentinel.feed.rolling_go_inputs",
        'if wait else snapshots.prepare(conn, job)', 'if False else snapshots.prepare(conn, job)',
        "test_go_waits_for_all_exports_then_publishes_same_job"),
    "transport_exhaustion_terminal": ("sentinel.feed.snapshot_export",
        'raise sharadar.SharadarUnavailable(', 'raise sharadar.SharadarRequestError(',
        "test_snapshot_transport_exhaustion_remains_shadow_availability"),
}


def test_file(name):
    if name == "transport_exhaustion_terminal":
        return "tests/sentinel/test_source_acquisition_lifecycle.py"
    if name == "go_wait_bypassed":
        return "tests/sentinel/test_rolling_go_inputs.py"
    return "tests/sentinel/test_" + (
        "export_readiness" if name in {"first_pending_aborts", "pending_accepted"}
        else "acquisition_wait") + ".py"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", choices=MUTANTS)
    args = parser.parse_args()
    if args.child:
        return child(args.child, mutants=MUTANTS, test_file=test_file(args.child))
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
