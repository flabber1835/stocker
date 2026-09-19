"""Behavioral falsifiers for bounded selection and publication wiring."""
import argparse
from pathlib import Path
import subprocess
import sys

from tools.sentinel_rolling_storage_falsifiers import child

MUTANTS = {
    'selection_caller': ('sentinel.backup_runtime_authority',
        'require_current_selection=base_backup is None', 'require_current_selection=False',
        'test_selection_change_during_proof_refuses_then_recovers'),
    'cluster_binding': ('sentinel.backup_runtime_authority',
        'system_id.encode("ascii")', 'b"[0-9]+"',
        'test_corrupt_selection_never_reaches_archive_hashes[cluster]'),
    'selection_reread': ('sentinel.backup_runtime_authority',
        'if require_current_selection and _published_base(conn, system_id=system_id) != base:',
        'if False:', 'test_selection_change_during_proof_refuses_then_recovers'),
    'bounded_read': ('sentinel.backup_runtime_authority',
        'RUNTIME_MAX_SELECTION_BYTES + 1', '32 * 1024 * 1024',
        'test_large_non_ascii_record_is_bounded_before_decoding'),
    'size_guard': ('sentinel.backup_runtime_authority',
        'if len(payload) > RUNTIME_MAX_SELECTION_BYTES:', 'if False:',
        'test_large_non_ascii_record_is_bounded_before_decoding'),
    'selection_alias': ('sentinel.backup_runtime_authority',
        "{shlex.quote(BASE_ROOT + '/.sentinel-runtime-base-' + system_id + '-v1')}",
        "{shlex.quote(BASE_ROOT + '/' + MARKER)}",
        'test_real_sql_refuses_selection_alias_during_archive_proof[symlink]'),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child', choices=(*MUTANTS, 'producer_wiring'))
    args = parser.parse_args()
    if args.child == 'producer_wiring':
        import pytest
        # Only permitted in the runner's disposable writable checkout copy.
        source = Path('/tmp/repo/scripts/sentinel-base-backup.sh')
        if Path.cwd().resolve() != Path('/tmp/repo'):
            raise RuntimeError('shell mutation requires the disposable /tmp/repo copy')
        original = source.read_bytes()
        text = original.decode()
        start = text.index('# Select the verified generation')
        end = text.index('# Publish a compact', start)
        try:
            source.write_bytes((text[:start] + text[end:]).encode())
            return pytest.main(['tests/backup/test_shell_lifecycle.py::test_verified_producer_publishes_exact_runtime_selection',
                                '-q', '-p', 'no:cacheprovider'])
        finally:
            source.write_bytes(original)
    if args.child:
        path = ('tests/sentinel/test_backup_selection_sql.py'
                if args.child in {'bounded_read', 'size_guard', 'selection_alias'}
                else 'tests/backup/test_runtime_base_selection.py')
        return child(args.child, mutants=MUTANTS, test_file=path)
    failed = []
    for name in (*MUTANTS, 'producer_wiring'):
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
