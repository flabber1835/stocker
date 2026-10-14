"""Installation recovery milestone under the existing exclusive target lock."""
import argparse
import os
from pathlib import Path
import sys
import time

from sentinel_backup_lock import lock_is_held, LOCK_ROOT_ENV
from sentinel_backup_deadlines import (BASE_COMMAND_SECONDS, CHAIN_STATUS_SECONDS,
                                      INVOCATION_SECONDS, RESTORE_COMMAND_SECONDS)
from sentinel_maintenance_process import run_bounded


def milestone(mode, runner=run_bounded, *, reuse_current=False):
    if mode not in {'full', 'physical'} or not lock_is_held():
        raise RuntimeError('installation backup requires the verified target owner and restore mode')
    root = Path(os.environ[LOCK_ROOT_ENV])
    deadline = time.monotonic() + INVOCATION_SECONDS
    def command(argv, timeout):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError('installation recovery deadline exhausted')
        if argv[0] == 'bash':
            print('  recovery milestone: ' + Path(argv[1]).name, file=sys.stderr, flush=True)
        # Each phase owns its descendants, including a shell that exits while
        # another process still holds its pipe or inherited backup descriptor.
        result = runner(argv, timeout=min(timeout, remaining), private_group=True)
        if argv[0] == 'bash':
            print(result.stdout, end='', file=sys.stderr, flush=True)
        print(result.stderr, end='', file=sys.stderr, flush=True)
        if result.returncode:
            raise RuntimeError('installation recovery command refused')
        return result.stdout
    if reuse_current:
        if mode != 'full':
            raise RuntimeError('only full activation recovery may reuse a prior proof')
        from sentinel_activation_checkpoint import reuse
        backup = reuse(root, command)
        if backup is not None:
            if time.monotonic() >= deadline:
                raise RuntimeError('installation recovery deadline exhausted')
            print('verified_installation_backup:' + backup, flush=True)
            return backup
    output = command(['bash', 'scripts/sentinel-base-backup.sh'], BASE_COMMAND_SECONDS)
    paths = [line[len('verified_base_backup:'):].strip() for line in output.splitlines()
             if line.startswith('verified_base_backup:')]
    if len(paths) != 1:
        raise RuntimeError('installation backup did not return one exact base')
    backup = Path(paths[0])
    import re
    if backup.parent != root / 'base' or not re.fullmatch(r'base-[0-9]{8}T[0-9]{6}Z', backup.name):
        raise RuntimeError('installation backup escaped the owned target')
    command(['bash', 'scripts/sentinel-backup-status.sh', '--backup', str(backup)],
            CHAIN_STATUS_SECONDS)
    restore = ['bash', 'scripts/sentinel-restore-drill.sh', '--backup', str(backup)]
    if mode == 'physical':
        restore.append('--physical-only')
    command(restore, RESTORE_COMMAND_SECONDS)
    if time.monotonic() >= deadline:
        raise RuntimeError('installation recovery deadline exhausted')
    print('verified_installation_backup:' + str(backup), flush=True)
    return str(backup)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restore', required=True, choices=('full', 'physical'))
    parser.add_argument('--reuse-current-proof', action='store_true')
    args = parser.parse_args()
    try:
        milestone(args.restore, reuse_current=args.reuse_current_proof)
    except (RuntimeError, OSError, ValueError) as exc:
        print('REFUSED: ' + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
