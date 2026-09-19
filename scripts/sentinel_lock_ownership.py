"""Read-only Linux proof that a descriptor owns an exclusive whole-file flock."""
from __future__ import annotations

import os
from pathlib import Path


def owns_exclusive_flock(fd: int) -> bool:
    try:
        identity = os.fstat(fd)
        with Path('/proc/self/fdinfo/%d' % fd).open('rb') as stream:
            data = stream.read(4097)
        if len(data) > 4096:
            return False
        records = [line.split() for line in data.decode('ascii').splitlines()
                   if line.startswith('lock:')]
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
