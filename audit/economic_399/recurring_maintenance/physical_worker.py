"""Pinned PostgreSQL 16 worker acceptance and target-pause falsifier."""
import argparse
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mutate-target', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    source = root / 'scripts/sentinel-restore-worker.sh'
    temporary = None
    if args.mutate_target:
        original = source.read_text()
        token = '-c "recovery_target_lsn=$SENTINEL_RESTORE_TARGET_LSN" -c recovery_target_action=pause'
        assert original.count(token) == 1
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False, newline='\n') as stream:
            stream.write(original.replace(token, '-c recovery_target_action=pause'))
            temporary = Path(stream.name)
        source = temporary
    command = ['docker', 'run', '--rm', '--network', 'none', '--user', '0', '--entrypoint', 'bash',
        '-v', str(root / 'scripts/sentinel-backup-media-lock.sh') + ':/media-lock-helper:ro',
        '-v', str(source) + ':/restore-worker:ro',
        '-v', str(root / 'scripts/test-backup-maintenance-worker.sh') + ':/lab-test:ro',
        'postgres:16@sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b', '/lab-test']
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=180)
        print(result.stdout, end='')
        print(result.stderr, end='')
        if args.mutate_target:
            assert result.returncode != 0 and 'RECOVERY_TARGET_NOT_PAUSED' in result.stdout
            print('PG16_TARGET_MUTANT: KILLED')
            return 0
        return result.returncode
    finally:
        if temporary:
            temporary.unlink()


if __name__ == '__main__':
    raise SystemExit(main())
