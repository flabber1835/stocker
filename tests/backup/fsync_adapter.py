"""Explicit file and filesystem sync for private host qualification."""
from __future__ import annotations

import errno
import os
from pathlib import Path
import sys


def _syncfs(descriptor):
    import ctypes
    try:
        syncfs = ctypes.CDLL(None, use_errno=True).syncfs
    except AttributeError:
        raise OSError(errno.ENOSYS, 'private filesystem sync is unavailable') from None
    syncfs.argtypes = [ctypes.c_int]
    syncfs.restype = ctypes.c_int
    if syncfs(descriptor) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def synchronize(paths, *, filesystem=False):
    if not paths:
        raise ValueError('explicit file or directory operands required')
    for path in paths:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        try:
            if filesystem:
                _syncfs(descriptor)
            else:
                os.fsync(descriptor)
        finally:
            os.close(descriptor)


def install(directory, ambient_path):
    directory = Path(directory)
    directory.mkdir(mode=0o700)
    command = directory / 'sync'
    command.write_bytes(b'#!' + os.fsencode(sys.executable) + b'\n' + Path(__file__).read_bytes())
    command.chmod(0o700)
    return str(directory) + os.pathsep + ambient_path


def main(argv=None):
    try:
        operands = list(sys.argv[1:] if argv is None else argv)
        filesystem = bool(operands and operands[0] in ('-f', '--file-system'))
        if filesystem:
            operands.pop(0)
        if operands and operands[0] == '--':
            operands.pop(0)
        elif operands and operands[0].startswith('-'):
            raise ValueError('unsupported private sync option')
        synchronize(operands, filesystem=filesystem)
    except (OSError, ValueError) as exc:
        print('private sync refused: ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
