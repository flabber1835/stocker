"""Preserve a canonical PostgreSQL directory bind when archive bytes agree."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

POSTGRES = 'postgres:16@sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b'
HELPER = 'sentinel-archive-wal.sh'


def run(argv):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise RuntimeError('canonical PostgreSQL helper inspection refused')
    if len(result.stdout.encode()) > 65536:
        raise RuntimeError('canonical PostgreSQL helper observation exceeds bound')
    return result.stdout


def unchanged_mount(root, invoke=run):
    ids = invoke(['docker', '--context', 'default', 'ps', '--all', '--quiet',
        '--filter', 'label=com.docker.compose.project=sentinel',
        '--filter', 'label=com.docker.compose.service=sentinel-postgres']).split()
    if not ids:
        return None
    if len(ids) != 1:
        raise RuntimeError('canonical PostgreSQL ownership is ambiguous')
    template = ('{"name":{{json .Name}},"image":{{json .Config.Image}},'
        '"project":{{json (index .Config.Labels "com.docker.compose.project")}},'
        '"service":{{json (index .Config.Labels "com.docker.compose.service")}},'
        '"mounts":{{json .Mounts}}}')
    value = json.loads(invoke(['docker', '--context', 'default', 'inspect', '--format', template, ids[0]]))
    if (value.get('name') != '/sentinel-sentinel-postgres-1' or value.get('image') != POSTGRES
            or value.get('project') != 'sentinel' or value.get('service') != 'sentinel-postgres'):
        raise RuntimeError('canonical PostgreSQL helper ownership changed')
    mounts = [m for m in value['mounts'] if m.get('Destination') == '/usr/local/libexec']
    if not mounts:
        return None  # Archive-off predecessor is reconciled by the ordinary installer.
    if (len(mounts) != 1 or mounts[0].get('Type') != 'bind'
            or mounts[0].get('RW') is not False):
        raise RuntimeError('PostgreSQL helper mount is not one read-only directory bind')
    source = Path(mounts[0]['Source'])
    candidate = Path(root) / 'scripts' / HELPER
    mounted = source / HELPER
    if (not source.is_absolute() or source.resolve() != source or not source.is_dir()
            or not mounted.is_file() or mounted.is_symlink()):
        return None
    if mounted.read_bytes() != candidate.read_bytes():
        return None
    return source


def publish_override(path, source):
    value = {'services': {'sentinel-postgres': {'volumes': [dict(type='bind',
        source=str(source), target='/usr/local/libexec', read_only=True)]}}}
    raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and not path.is_symlink() and path.read_bytes() == raw:
        return
    if path.is_symlink():
        raise RuntimeError('PostgreSQL helper override must not be a symlink')
    descriptor, name = tempfile.mkstemp(prefix='.postgres-helpers-', dir=str(path.parent))
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        source = unchanged_mount(Path(__file__).resolve().parents[1])
        if source is not None:
            publish_override(args.output, source)
            print(args.output)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise SystemExit('REFUSED: PostgreSQL helper selection: ' + type(exc).__name__)


if __name__ == '__main__':
    main()
