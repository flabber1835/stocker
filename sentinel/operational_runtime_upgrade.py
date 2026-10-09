"""Exact operational runtime admission; no strategy or financial authority."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

PROFILE_SHA256 = '4bbad3ad46fffe2cca8ae32b9aa25b0b5ed63b0532de023b0124495fae39034a'
PROFILE = Path(__file__).with_name('operational-runtime-upgrade.json')
SCOPE = frozenset({'automation/service.py', 'schema.py', 'supervisor_io.py',
                   'panel/model.py', 'panel/sources.py'})
ADDITIONS = frozenset({'panel/authority_reader.py'})


def profile():
    raw = PROFILE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PROFILE_SHA256:
        raise ValueError('OPERATIONAL_RUNTIME_PROFILE_CHANGED')
    value = json.loads(raw)
    if (set(value) != {'schema', 'files', 'additions', 'module_sha256'}
            or value['schema'] != 'sentinel.operational-runtime-upgrade/1'
            or set(value['files']) != SCOPE or set(value['additions']) != ADDITIONS):
        raise ValueError('OPERATIONAL_RUNTIME_PROFILE_SHAPE_CHANGED')
    module, count = re.subn(rb"^PROFILE_SHA256 = '[0-9a-f]{64}'$",
        b"PROFILE_SHA256 = '" + b'0'*64 + b"'", Path(__file__).read_bytes(), flags=re.M)
    if count != 1 or hashlib.sha256(module).hexdigest() != value['module_sha256']:
        raise ValueError('OPERATIONAL_RUNTIME_MODULE_CHANGED')
    for record in value['files'].values():
        if (set(record) != {'before', 'after'}
                or not isinstance(record['before'], list) or not record['before']
                or any(not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha)
                       for sha in [*record['before'], record['after']])
                or len(record['before']) != len(set(record['before']))):
            raise ValueError('OPERATIONAL_RUNTIME_SOURCE_RECORD_CHANGED')
    if any(not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha)
           for sha in value['additions'].values()):
        raise ValueError('OPERATIONAL_RUNTIME_ADDITION_CHANGED')
    return value


def source_allowed(name, previous, actual):
    record = profile()['files'].get(name)
    return record is not None and previous in record['before'] and actual == record['after']


def additions_allowed(actual):
    """Return only present additions whose exact reviewed bytes match."""
    return {name for name, sha in profile()['additions'].items()
            if actual.get(name) == sha}
