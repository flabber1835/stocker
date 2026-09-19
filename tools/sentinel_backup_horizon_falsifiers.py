"""Break renewal guards only in the offline runner's disposable source copy."""
import argparse
from pathlib import Path
import subprocess
import sys

TEST = 'tests/backup/test_shell_lifecycle.py::'
CHAIN = 'scripts/sentinel-backup-verify-chain.sh'
STATUS = 'scripts/sentinel-backup-status.sh'
REFRESH = 'scripts/sentinel_go_backup_refresh.py'
MUTANTS = {
    'payload_bound': (CHAIN,
        '[ "$interval_count" -le $(((1073741824 - history_bytes) / wal_bytes)) ]',
        'true', 'test_status_runtime_horizon_matches_independent_payload_budget[65-1-False]'),
    'history_bytes': (CHAIN, '(1073741824 - history_bytes)',
        '(1073741824)', 'test_status_runtime_horizon_matches_independent_payload_budget[64-2-False]'),
    'object_bound': (CHAIN, '[ "$archive_objects" -le 1024 ]', 'true',
        'test_status_chain_object_bound_precedes_payload_reads[1-1025]'),
    'history_object': (CHAIN, 'archive_objects=$((archive_objects + 1))', ':',
        'test_status_chain_object_bound_precedes_payload_reads[2-1024]'),
    'exit_classification': (STATUS, '[ "$chain_rc" -eq 5 ]', 'true',
        'test_status_horizon_classification_requires_exact_code_and_output[wrong-exit]'),
    'token_classification': (STATUS,
        '[ "$CHAIN" = \'SENTINEL_BACKUP_CHAIN_REASON=RUNTIME_HORIZON_EXCEEDED\' ]', 'true',
        'test_status_horizon_classification_requires_exact_code_and_output[missing-token]'),
    'renewal_caller': (REFRESH, '    "BASE_BACKUP_RUNTIME_HORIZON_EXCEEDED",\n', '',
        'test_go_runtime_horizon_renews_exact_successor_or_refuses[none]'),
    'successor_check': (REFRESH, 'if verified.returncode != 0:', 'if False:',
        'test_go_runtime_horizon_renews_exact_successor_or_refuses[post-check]'),
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
            return pytest.main([TEST + test, '-q', '--tb=short', '-p', 'no:cacheprovider'])
        finally:
            source.write_bytes(original)
    failures = []
    for name in MUTANTS:
        result = subprocess.run([sys.executable, '-m', __spec__.name, '--child', name],
                                capture_output=True, text=True)
        killed = result.returncode == 1 and '1 failed' in result.stdout
        print(name + (': KILLED' if killed else ': NOT PROVED'), flush=True)
        print(result.stdout, flush=True)
        print(result.stderr, flush=True)
        if not killed:
            failures.append(name)
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
