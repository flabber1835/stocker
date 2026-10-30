"""Real file-scoped fsync for private host tests, independent of ambient sync."""
from __future__ import annotations

import os
from pathlib import Path
import sys


def synchronize(paths):
    if not paths:
        raise ValueError('explicit file or directory operands required')
    for path in paths:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        try:
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
        synchronize(sys.argv[1:] if argv is None else argv)
    except (OSError, ValueError) as exc:
        print('private file fsync refused: ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
