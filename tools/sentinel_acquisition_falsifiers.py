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
    "resource_download": ("sentinel.feed.snapshot_export",
        'limits.check("ZIP_BYTES", buffer.tell() + len(chunk), limits.ZIP_BYTES)', 'pass',
        "test_stream_limit_counts_bytes_without_trusting_length[None]"),
    "resource_declared_download": ("sentinel.feed.snapshot_export",
        'limits.check("ZIP_BYTES", int(length), limits.ZIP_BYTES)', 'pass',
        "test_declared_oversize_refuses_before_consuming"),
    "resource_http_encoding": ("sentinel.feed.snapshot_export",
        'response.headers.get("Content-Encoding", "identity").lower() != "identity"', 'False',
        "test_http_compression_refuses_before_decompression"),
    "resource_zip_entries": ("sentinel.feed.acquisition_limits",
        'check("ZIP_ENTRIES", count, ZIP_ENTRIES)', 'pass',
        "test_directory_bounds_precede_zipfile_allocation[ZIP_ENTRIES]"),
    "resource_zip_bytes": ("sentinel.feed.acquisition_limits",
        'check("ZIP_BYTES", len(blob), ZIP_BYTES)', 'pass',
        "test_directory_bounds_precede_zipfile_allocation[ZIP_BYTES]"),
    "resource_directory": ("sentinel.feed.acquisition_limits",
        'check("DIRECTORY_BYTES", size, DIRECTORY_BYTES)', 'pass',
        "test_directory_bounds_precede_zipfile_allocation[DIRECTORY_BYTES]"),
    "resource_expansion_declared": ("sentinel.feed.snapshot_export",
        'limits.check("CSV_BYTES", info.file_size, limits.CSV_BYTES)', 'pass',
        "test_expansion_refused_before_opening_member"),
    "resource_expansion_observed": ("sentinel.feed.acquisition_limits",
        'check("CSV_BYTES", self.total, CSV_BYTES)', 'pass',
        "test_observed_expansion_bound_is_independent_of_metadata"),
    "resource_rows": ("sentinel.feed.snapshot_export",
        'limits.check("ROWS", len(rows) + 1, limits.ROWS)', 'pass',
        "test_csv_exact_limit_then_one_less_refuses[ROWS]"),
    "resource_cells": ("sentinel.feed.snapshot_export",
        'limits.check("CELLS", (len(rows) + 1) * len(fields), limits.CELLS)', 'pass',
        "test_csv_exact_limit_then_one_less_refuses[CELLS]"),
    "resource_columns": ("sentinel.feed.snapshot_export",
        'limits.check("COLUMNS", len(fields), limits.COLUMNS)', 'pass',
        "test_csv_exact_limit_then_one_less_refuses[COLUMNS]"),
    "resource_zip_codec": ("sentinel.feed.snapshot_export",
        'info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED} or info.flag_bits & 1', 'False',
        "test_alternative_zip_decoder_refused_before_open"),
    "resource_record": ("sentinel.feed.acquisition_limits",
        'check("RECORD_CHARS", self.total, RECORD_CHARS)', 'pass',
        "test_csv_exact_limit_then_one_less_refuses[RECORD_CHARS]"),
    "resource_cache_reservation": ("sentinel.feed.acquisition_work",
        'total + incoming <= limits.CACHE_BYTES', 'True',
        "test_cache_reserves_bytes_before_writing"),
    "resource_cache_count": ("sentinel.feed.acquisition_work",
        'count + int(replacement is not None) <= limits.CACHE_FILES', 'True',
        "test_cache_file_count_is_bounded_independently_of_bytes"),
    "resource_cache_serialization": ("sentinel.feed.acquisition_work",
        'with _cache_lock(path.parent / "cache.lock"):\n        # Every writer',
        'with __import__("contextlib").nullcontext():\n        # Every writer',
        "test_concurrent_writers_reserve_under_one_kernel_lock"),
}


def test_file(name):
    if name.startswith("resource_"):
        return "tests/sentinel/test_acquisition_resource_containment.py"
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
