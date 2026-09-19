"""Falsify bounded backup reads without editing source or touching live media."""
import argparse
import subprocess
import sys

from tools.sentinel_rolling_storage_falsifiers import child


BOUNDS = "tests/backup/test_runtime_backup_bounds.py"
READS = "tests/sentinel/test_backup_bounded_reads.py"
MUTANTS = {
    "early_objects": (
        "if count + (1 if et > 1 else 0) > RUNTIME_MAX_ARCHIVE_OBJECTS:",
        "if False:", BOUNDS,
        "test_over_budget_chain_refuses_before_name_enumeration[objects]"),
    "early_bytes": (
        "if count * segment_size > RUNTIME_MAX_VERIFIED_BYTES:", "if False:", BOUNDS,
        "test_over_budget_chain_refuses_before_name_enumeration[bytes]"),
    "history_object": (
        "count + (1 if et > 1 else 0)", "count", BOUNDS,
        "test_over_budget_chain_refuses_before_name_enumeration[history-object]"),
    "checked_read_length": (
        "[sizes[name] for name in objects]",
        '[conn.execute("SELECT (pg_stat_file(%s)).size", (root + "/" + name,)).fetchone()[0] for name in objects]',
        READS, "test_hash_sql_uses_checked_length_even_if_file_grows[budget-extra-bytes]"),
    "post_read_growth": (
        "if _archive_metadata(conn, root=wal_root, objects=objects) != actual:",
        "if False:", BOUNDS,
        "test_changed_archive_during_scrub_refuses_without_caching[growth]"),
    "post_read_sidecar": (
        "if _archive_metadata(conn, root=wal_root, objects=objects) != actual:",
        "if False:", BOUNDS,
        "test_changed_archive_during_scrub_refuses_without_caching[sidecar]"),
    "post_read_alias": (
        "        _require_no_aliases(conn, base=base, system_id=system_id, objects=objects)",
        "        pass", BOUNDS,
        "test_alias_introduced_after_hashing_cannot_enter_cache"),
    "second_content_pass": (
        "repeated = _hash_objects(conn, root=wal_root, objects=hash_names,\n"
        "                                 sizes={name: int(actual[name][0]) for name in hash_names})",
        "repeated = digests", READS,
        "test_real_sql_changed_chain_is_retryable_and_never_cached[same-size-after-read]"),
    "coarse_metadata_reuse": (
        "hash_names = objects",
        'hash_names = () if cached is not None and cached["metadata"] == actual else objects',
        READS, "test_same_metadata_cannot_reuse_old_content_authority"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", choices=MUTANTS)
    args = parser.parse_args()
    if args.child:
        old, new, path, test = MUTANTS[args.child]
        return child(args.child, mutants={args.child: (
            "sentinel.backup_runtime_authority", old, new, test)}, test_file=path)
    failed = []
    for name in MUTANTS:
        result = subprocess.run([sys.executable, "-m", __spec__.name, "--child", name],
                                capture_output=True, text=True, check=False)
        killed = result.returncode == 1 and "1 failed" in result.stdout
        print(name + (": KILLED" if killed else ": NOT PROVED"), flush=True)
        print(result.stdout, flush=True)
        print(result.stderr, flush=True)
        if not killed:
            failed.append(name)
    return bool(failed)


if __name__ == "__main__":
    raise SystemExit(main())
