"""Process-local reuse of immutable Compose discovery, never service readiness."""
import hashlib
import json
import os
from pathlib import Path
import shlex

FILES = ('scripts/sentinel_compose_context.py','scripts/sentinel-compose.sh','scripts/sentinel-env.sh','scripts/sentinel_env.py',
    'scripts/sentinel_postgres_helpers.py','scripts/sentinel_host_capabilities.py',
    'scripts/sentinel_strip_cpu_limits.py','docker-compose.sentinel.yml',
    'docker-compose.sentinel-backup.yml','.env',
    'artifacts/compose/docker-compose.sentinel.nocpu.yml',
    'artifacts/compose/docker-compose.sentinel.postgres-helpers.yml',
    'artifacts/sentinel/deployment/validated-runtime.env')


def _bytes(path):
    if not path.exists():
        return None
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 2*1024*1024:
        raise ValueError('Compose context file is not bounded regular content')
    with path.open('rb') as stream:
        raw = stream.read(2*1024*1024+1)
    if len(raw) > 2*1024*1024:
        raise ValueError('Compose context file exceeds bound')
    return raw


def _context(root, env):
    root = Path(root).resolve()
    records = []
    for name in FILES:
        raw = _bytes(root/name)
        records.append((name,hashlib.sha256(raw).hexdigest() if raw is not None else None))
    override = _bytes(root/FILES[-2])
    if override is not None:
        value = json.loads(override)
        mounts = value['services']['sentinel-postgres']['volumes']
        if len(mounts) != 1 or mounts[0]['target'] != '/usr/local/libexec':
            raise ValueError('Compose helper context changed')
        helper = Path(mounts[0]['source'])/'sentinel-archive-wal.sh'
        raw = _bytes(helper)
        records.append((str(helper),hashlib.sha256(raw).hexdigest() if raw is not None else None))
    environment = hashlib.sha256(json.dumps(dict(env),sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return os.getpid(),str(root),environment,tuple(records)


class ComposeContext:
    def __init__(self):
        self._cache = {}

    def resolve(self, *, root, env, invoke):
        key = _context(root, env)
        if key in self._cache:
            return list(self._cache[key])
        result = invoke(['bash','scripts/sentinel-compose.sh','--explain'])
        if result.returncode != 0:
            raise ValueError('Compose resolver refused')
        args = shlex.split((result.stdout or '').strip())
        if not args or '-f' not in args:
            raise ValueError('Compose resolver returned no exact graph')
        # Resolution can legitimately create generated overrides. Bind the
        # completed local context; every later reuse reobserves it.
        key = _context(root, env)
        if len(self._cache) >= 16:
            self._cache.clear()
        self._cache[key] = tuple(args)
        return list(args)
