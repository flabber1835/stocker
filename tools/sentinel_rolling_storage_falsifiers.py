"""Run focused guard-removal falsifiers without editing the checkout.

Each child imports one mutated module into its own process, then runs the real
behavioral test. A killed mutant requires a test failure, never a collection or
infrastructure error. Intended for the existing PostgreSQL-capable test image.
"""
from __future__ import annotations

import argparse
import importlib
from pathlib import Path
import subprocess
import sys

TEST = "tests/sentinel/test_rolling_snapshot_storage.py"
MUTANTS = {
    "manifest_reference_expansion": (
        "sentinel.feed.rolling_store", 'verify_evidence(conn, value.reference_sha256)',
        'load_evidence(conn, value.reference_sha256)',
        "test_manifest_and_content_verification_do_not_decode_text_again",
    ),
    "stored_reference_checksum": (
        "sentinel.feed.rolling_store", 'valid = payload is None and observed == identity',
        'valid = payload is None',
        "test_stored_byte_verifier_rejects_corrupt_or_unavailable_evidence[checksum]",
    ),
    "stored_reference_exclusive": (
        "sentinel.feed.rolling_store", 'valid = payload is None and observed == identity',
        'valid = observed == identity',
        "test_stored_byte_verifier_rejects_corrupt_or_unavailable_evidence[both]",
    ),
    "stored_reference_size": (
        "sentinel.feed.rolling_store", 'check("SNAPSHOT_EVIDENCE_BYTES", size, MAX_EVIDENCE_BYTES)',
        'pass', "test_stored_byte_verifier_checks_text_size",
    ),
    "evidence_server_expansion": (
        "sentinel.feed.rolling_store", "JSONB_EVIDENCE_BYTES = 1024 * 1024",
        "JSONB_EVIDENCE_BYTES = 1024 * 1024 * 1024",
        "test_large_evidence_never_uses_jsonb_conversion",
    ),
    "evidence_size_bound": (
        "sentinel.feed.rolling_store",
        'check("SNAPSHOT_EVIDENCE_BYTES", len(encoded), MAX_EVIDENCE_BYTES)', 'pass',
        "test_evidence_size_limit_refuses_before_database_access",
    ),
    "retired_text_reference": (
        "sentinel.feed.retention_schema",
        "AND payload IS NULL AND canonical_payload IS NULL) THEN", "AND FALSE) THEN",
        "test_text_evidence_retirement_restoration_and_live_pin",
    ),
    "calendar_gap": (
        "sentinel.feed.rolling_contract",
        "if actual != expected:", "if False:",
        "test_window_counts_sessions_and_rejects_missing_middle",
    ),
    "independent_identity": (
        "sentinel.feed.rolling_store",
        "tuple(expected) != key or", "False or",
        "test_independent_coverage_refuses_keyset_drift[wrong_identity]",
    ),
    "sealed_insert": (
        "sentinel.feed.rolling_schema",
        "IF NOT FOUND OR parent.snapshot_id IS NOT NULL THEN",
        "IF NOT FOUND THEN",
        "test_sealed_rows_and_evidence_are_immutable_even_through_sql",
    ),
    "benchmark_gap": (
        "sentinel.feed.rolling_store",
        "if row.session != expected:", "if False:",
        "test_wrong_benchmark_axis_refuses",
    ),
    "presealed_insert": (
        "sentinel.feed.rolling_schema",
        "IF NEW.snapshot_id IS NOT NULL OR NEW.manifest IS NOT NULL THEN",
        "IF FALSE THEN",
        "test_presealed_insert_cannot_bypass_sealing",
    ),
    "erase_by_truncate": (
        "sentinel.feed.rolling_schema",
        'f"CREATE TRIGGER snapshot_no_truncate BEFORE TRUNCATE ON {_table} "\n'
        '        "FOR EACH STATEMENT EXECUTE FUNCTION sentinel_snapshot_immutable()",',
        '"SELECT 1",',
        "test_truncate_cannot_erase_snapshot_evidence[sentinel_snapshot_bars]",
    ),
    "restore_payload": (
        "sentinel.feed.rolling_store",
        "or bars_hash.hexdigest() != value.bars_sha256", "or False",
        "test_restore_verification_reads_payload_not_only_manifest[bar_value]",
    ),
}


def child(name, *, mutants=MUTANTS, test_file=TEST):
    import pytest
    module_name, original, replacement, test = mutants[name]
    module = importlib.import_module(module_name)
    source = Path(module.__file__).read_text(encoding="utf-8")
    if source.count(original) != 1:
        raise RuntimeError("mutant no longer matches exactly one guard: " + name)
    exec(compile(source.replace(original, replacement), module.__file__, "exec"),
         module.__dict__)
    return pytest.main([test_file + "::" + test, "-q", "-p", "no:cacheprovider"])


def main(*, mutants=MUTANTS, test_file=TEST,
         runner="tools.sentinel_rolling_storage_falsifiers"):
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", choices=mutants)
    args = parser.parse_args()
    if args.child:
        return child(args.child, mutants=mutants, test_file=test_file)
    failed = []
    for name in mutants:
        result = subprocess.run(
            [sys.executable, "-m", runner,
             "--child", name], capture_output=True, text=True, check=False)
        killed = result.returncode == 1 and "1 failed" in result.stdout
        print(name + (": KILLED" if killed else ": NOT PROVED"), flush=True)
        if not killed:
            failed.append(name)
            print(result.stdout)
            print(result.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
