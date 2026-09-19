"""Falsify descriptor ownership guards on disposable local locks only."""
import argparse
import subprocess
import sys

from tools.sentinel_rolling_storage_falsifiers import child

TEST = 'tests/scripts/test_host_lock_ownership.py'
MUTANTS = {
    'backup_owner': ('sentinel_backup_lock', 'return owns_exclusive_flock(fd)',
                     'return True', 'test_independent_descriptor_is_not_the_owner[backup]'),
    'go_owner': ('sentinel_go_lock', 'return owns_exclusive_flock(fd)',
                 'return True', 'test_independent_descriptor_is_not_the_owner[go]'),
    'exclusive_mode': ('sentinel_lock_ownership',
        "fields[2:5] != ['FLOCK', 'ADVISORY', 'WRITE']",
        "fields[2:4] != ['FLOCK', 'ADVISORY']",
        'test_shared_lock_is_not_exclusive_and_is_not_upgraded[backup]'),
    'overflow_byte': ('sentinel_lock_ownership', 'stream.read(4097)', 'stream.read(4096)',
        'test_valid_lock_record_cannot_hide_oversized_descriptor_evidence'),
    'size_guard': ('sentinel_lock_ownership', 'if len(data) > 4096:', 'if False:',
        'test_valid_lock_record_cannot_hide_oversized_descriptor_evidence'),
    'inode_binding': ('sentinel_lock_ownership',
        'return (int(major, 16), int(minor, 16), int(inode)) == (',
        'return True or (int(major, 16), int(minor, 16), int(inode)) == (',
        'test_descriptor_lock_record_must_match_its_actual_inode'),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child', choices=MUTANTS)
    args = parser.parse_args()
    if args.child:
        return child(args.child, mutants=MUTANTS, test_file=TEST)
    failed = []
    for name in MUTANTS:
        result = subprocess.run([sys.executable, '-m', __spec__.name, '--child', name],
                                capture_output=True, text=True, check=False)
        killed = result.returncode == 1 and '1 failed' in result.stdout
        print(name + (': KILLED' if killed else ': NOT PROVED'), flush=True)
        print(result.stdout, flush=True)
        print(result.stderr, flush=True)
        if not killed:
            failed.append(name)
    return bool(failed)


if __name__ == '__main__':
    raise SystemExit(main())
