"""Receipt-bound helpers shared with the historical PAPER activation loader."""
import hashlib
import json
from pathlib import Path
import subprocess


BASE = 'dda0195ce0374c4bb4a9c322937ba6dd0819b34f'
IMAGE = 'ghcr.io/flabber1835/stocker/sentinel@sha256:5280f246bc1ca4115c509f4c981e4588c83a6f98ccb0faf94df11868b168b2e0'


class Refused(RuntimeError):
    pass


def require(value, reason):
    if not value:
        raise Refused(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _document(path):
    def unique(items):
        result = {}
        for key, value in items:
            require(key not in result, 'HOST_PATCH_DUPLICATE_KEY')
            result[key] = value
        return result
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique)


def _git(root, *args):
    return subprocess.run(['git', '--no-optional-locks', '-C', str(root), *args],
        capture_output=True, text=True, check=True, timeout=30).stdout.strip()


if __name__ == '__main__':
    raise SystemExit('The one-time GO host overlay has been retired. Use the release installer.')
