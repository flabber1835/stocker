"""Exact lease wait and read-only progress repairs over retained economics."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

PROFILE_SHA256 = '4a0a37305bdee248232c0c3d795e4e30d9ca52596e82dbe64c0d5e659d61369c'
PROFILE = Path(__file__).with_name('startup-contention-upgrade.json')
SCOPE = frozenset({'automation/service.py', 'automation_runtime.py',
                   'panel/model.py', 'panel/sources.py'})


def profile():
    raw = PROFILE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PROFILE_SHA256:
        raise ValueError('STARTUP_CONTENTION_PROFILE_CHANGED')
    value = json.loads(raw)
    if (set(value) != {'schema', 'files', 'module_sha256'}
            or value['schema'] != 'sentinel.startup-contention-upgrade/1'
            or set(value['files']) != SCOPE):
        raise ValueError('STARTUP_CONTENTION_PROFILE_SHAPE_CHANGED')
    module, count = re.subn(rb"^PROFILE_SHA256 = '[0-9a-f]{64}'$",
        b"PROFILE_SHA256 = '" + b'0'*64 + b"'", Path(__file__).read_bytes(), flags=re.M)
    if count != 1 or hashlib.sha256(module).hexdigest() != value['module_sha256']:
        raise ValueError('STARTUP_CONTENTION_MODULE_CHANGED')
    for record in value['files'].values():
        if (set(record) != {'before', 'after'}
                or not isinstance(record['before'], list) or not record['before']
                or len(record['before']) != len(set(record['before']))
                or any(not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha)
                       for sha in [*record['before'], record['after']])):
            raise ValueError('STARTUP_CONTENTION_SOURCE_RECORD_CHANGED')
    return value


def source_allowed(name, previous, actual):
    record = profile()['files'].get(name)
    return record is not None and previous in record['before'] and actual == record['after']
