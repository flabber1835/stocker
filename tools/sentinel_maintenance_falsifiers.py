"""Mutate only a disposable source copy; every altered guard must be detected."""
import argparse
from pathlib import Path
import subprocess
import sys

TEST = 'tests/backup/test_recurring_maintenance.py::'
MEDIA = 'sentinel/backup_retention.py'
HOST = 'scripts/sentinel_backup_maintenance.py'
MUTANTS = {
    'wal_headroom': (HOST, 'RENEW_BYTES = 256 * 1024 * 1024', 'RENEW_BYTES = 2**60',
                     'test_proactive_wal_boundary_is_independent_of_age[15-True]'),
    'age_renewal': (HOST, 'RENEW_SECONDS = 12 * 3600', 'RENEW_SECONDS = 2**60',
                    'test_production_tick_renews_verifies_restores_then_retains_and_restarts'),
    'restore_receipt': (MEDIA, '    valid_receipt(receipt, selected, media.system_id, image)\n', '',
                        'test_bad_restore_evidence_never_deletes[physical_only-True]'),
    'wal_floor': (MEDIA, 'min(r["start"] for r in ranges)', 'min(r["end"] for r in ranges)',
                  'test_calendar_retention_and_exact_start_segment_boundary'),
    'every_range': (MEDIA, 'for r in item["ranges"]]', 'for r in item["ranges"][-1:]]',
                     'test_every_manifest_range_contributes_to_retention_floor'),
    'keep_selected': (MEDIA, 'keep = {selected, *names[:2]}', 'keep = set(names[:2])',
                       'test_selected_historical_generation_is_never_pruned'),
    'journal_revalidation': (MEDIA,
        'require(metadata(media.base, name, media.system_id)["metadata_sha256"] == digest,\n                "protected backup changed',
        'require(True,\n                "protected backup changed',
        'test_restart_revalidates_every_protected_identity'),
    'worker_flock': (MEDIA, '        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n', '',
                      'test_worker_lock_survives_parent_death'),
    'successor_binding': (HOST, 'if paths[0] != root + "/base/" + selected["name"]:', 'if False:',
                          'test_successor_identity_mismatch_refuses_before_status_or_retention'),
    'active_volume': (HOST, 'if runner(["docker", "ps", "-a", "--filter", "volume=" + name, "--format", "{{.ID}}"]):',
                       'if False:', 'test_reaper_keeps_active_recent_foreign_and_unlabeled_resources'),
    'inventory_bound': (MEDIA, 'require(count <= MAX_BASES, "base inventory limit exceeded")',
                        'require(True, "base inventory limit exceeded")', 'test_bounds_are_checked_before_deletion'),
    'journal_clock': (MEDIA,
        'type(journal.get("observed_at")) is int and journal["observed_at"] <= now', 'True',
        'test_journal_clock_regression_preserves_obsolete_and_protected_bases'),
    'wal_alias_preflight': (MEDIA,
        'require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,\n                        "WAL namespace contains aliased objects")',
        'require(True, "WAL namespace contains aliased objects")',
        'test_private_wal_alias_refuses_before_any_base_deletion'),
    'supervisor_flock': (HOST, '            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)',
                        '            pass', 'test_loop_has_one_owner_retries_failed_tick_and_releases_lock'),
    'environment_bytes': ('scripts/sentinel_env.py', 'if observations[0] != observations[1]:', 'if False:',
        'tests/host_python38/test_env_ingestion.py::EnvHarness::test_same_timestamp_rewrite_requires_two_matching_byte_observations'),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child', choices=MUTANTS)
    args = parser.parse_args()
    if args.child:
        if Path.cwd().resolve() != Path('/tmp/repo') or not Path('/source').is_dir():
            raise RuntimeError('mutation requires disposable runner mounts')
        import pytest
        path, old, new, test = MUTANTS[args.child]
        source = Path(path)
        original = source.read_bytes()
        text = original.decode()
        assert text.count(old) == 1, (path, old)
        try:
            source.write_bytes(text.replace(old, new, 1).encode())
            return pytest.main([test if test.startswith('tests/') else TEST + test,
                                '-q', '--tb=short', '-p', 'no:cacheprovider'])
        finally:
            source.write_bytes(original)
    failed = []
    for name in MUTANTS:
        result = subprocess.run([sys.executable, '-m', __spec__.name, '--child', name],
                                capture_output=True, text=True)
        killed = result.returncode == 1 and '1 failed' in result.stdout
        print(name + (': KILLED' if killed else ': NOT PROVED'), flush=True)
        print(result.stdout, flush=True)
        print(result.stderr, flush=True)
        if not killed:
            failed.append(name)
    return bool(failed)


if __name__ == '__main__':
    raise SystemExit(main())
