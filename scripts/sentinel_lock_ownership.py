"""Prove exclusive flock ownership, including Linux without fdinfo lock records."""
from __future__ import annotations

import errno
import fcntl
import os
from pathlib import Path
import stat
import sys
import tempfile


def _reassert_exclusive(fd: int) -> bool:
    """Require prior exclusivity, then establish it on this open description.

    Contention alone is not proof. The second flock fails on an independently
    opened descriptor while the actual owner lives. If that owner exits between
    probes, success acquires exclusive ownership before work can proceed.
    See docs/host-lock-ownership.md for the deliberately non-read-only contract.
    """
    identity = os.fstat(fd)
    if not stat.S_ISREG(identity.st_mode):
        return False
    probe = os.open('/proc/self/fd/%d' % fd, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        other = os.fstat(probe)
        if (identity.st_dev, identity.st_ino) != (other.st_dev, other.st_ino):
            return False
        try:
            fcntl.flock(probe, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in (errno.EAGAIN, errno.EACCES):
                return False
        else:
            # Closing this independent description drops only its probe lock.
            return False
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    finally:
        os.close(probe)


def owns_exclusive_flock(fd: int) -> bool:
    try:
        identity = os.fstat(fd)
        with Path('/proc/self/fdinfo/%d' % fd).open('rb') as stream:
            data = stream.read(4097)
        if len(data) > 4096:
            return False
        lines = data.decode('ascii').splitlines()
        records = [line.split() for line in lines
                   if line.startswith('lock:')]
        if not records:
            # Old procfs must still identify a readable descriptor. Empty or
            # malformed evidence is not an invitation to acquire a lock.
            positions = [line.split() for line in lines if line.startswith('pos:')]
            flags = [line.split() for line in lines if line.startswith('flags:')]
            if (any(line.split(':', 1)[0] not in ('pos', 'flags', 'mnt_id', 'ino') for line in lines)
                    or len(positions) != 1 or len(flags) != 1
                    or len(positions[0]) != 2 or len(flags[0]) != 2
                    or int(positions[0][1]) < 0 or int(flags[0][1], 8) < 0):
                return False
            return _reassert_exclusive(fd)
        if len(records) != 1:
            return False
        fields = records[0]
        if (len(fields) != 9 or fields[2:5] != ['FLOCK', 'ADVISORY', 'WRITE']
                or fields[7:] != ['0', 'EOF']):
            return False
        major, minor, inode = fields[6].split(':')
        return (int(major, 16), int(minor, 16), int(inode)) == (
            os.major(identity.st_dev), os.minor(identity.st_dev), identity.st_ino)
    except (OSError, ValueError, UnicodeError):
        return False


def main() -> int:
    """Disposable host check; no environment, database or backup access."""
    try:
        with tempfile.TemporaryDirectory(prefix='sentinel-flock-probe-') as directory:
            path = Path(directory) / 'lock'
            with path.open('a+') as owner, path.open('a+') as other:
                if owns_exclusive_flock(owner.fileno()):
                    raise RuntimeError('unlocked descriptor accepted')
                fcntl.flock(owner, fcntl.LOCK_SH | fcntl.LOCK_NB)
                if owns_exclusive_flock(owner.fileno()):
                    raise RuntimeError('shared descriptor accepted')
                fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if not owns_exclusive_flock(owner.fileno()):
                    raise RuntimeError('exclusive descriptor refused')
                if owns_exclusive_flock(other.fileno()):
                    raise RuntimeError('independent descriptor accepted')
                duplicate = os.dup(owner.fileno())
                try:
                    if not owns_exclusive_flock(duplicate):
                        raise RuntimeError('duplicate descriptor refused')
                finally:
                    os.close(duplicate)
        print('host flock compatibility: PASS (owner, duplicate, independent, shared, unlocked)')
        return 0
    except (OSError, RuntimeError) as exc:
        print('REFUSED: host flock compatibility: %s' % exc, file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
