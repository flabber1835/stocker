"""Exact bounded-callback source admission over the unchanged financial book."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

PROFILE_SHA256 = '50de0ecb2149869f1999251ed67c6bb7e1057a2ead628c49e9b75d65f6555841'
PROFILE = Path(__file__).with_name('callback-liveness-upgrade.json')
SCOPE = frozenset({'automation/health.py', 'automation/service.py',
                   'automation/store.py', 'automation_supervisor.py',
                   'schema.py', 'shadow_health_projection.py'})


def profile():
    raw = PROFILE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PROFILE_SHA256:
        raise ValueError('CALLBACK_LIVENESS_PROFILE_CHANGED')
    value = json.loads(raw)
    if (set(value) != {'schema', 'files', 'module_sha256'}
            or value['schema'] != 'sentinel.callback-liveness-upgrade/1'
            or set(value['files']) != SCOPE):
        raise ValueError('CALLBACK_LIVENESS_PROFILE_SHAPE_CHANGED')
    module, count = re.subn(rb"^PROFILE_SHA256 = '[0-9a-f]{64}'$",
        b"PROFILE_SHA256 = '" + b'0'*64 + b"'", Path(__file__).read_bytes(), flags=re.M)
    if count != 1 or hashlib.sha256(module).hexdigest() != value['module_sha256']:
        raise ValueError('CALLBACK_LIVENESS_MODULE_CHANGED')
    for record in value['files'].values():
        if (set(record) != {'before', 'after'}
                or not isinstance(record['before'], list) or not record['before']
                or len(record['before']) != len(set(record['before']))
                or any(not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha)
                       for sha in [*record['before'], record['after']])):
            raise ValueError('CALLBACK_LIVENESS_SOURCE_RECORD_CHANGED')
    return value


def source_allowed(name, previous, actual):
    record = profile()['files'].get(name)
    return record is not None and previous in record['before'] and actual == record['after']
