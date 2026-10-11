"""Exact operator scheduling-recovery admission over a retained book."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

PROFILE_SHA256 = '7bea90fe646b16d4704005b0d7eabe31ee63f233f420eb3acdef940b44ec5471'
PROFILE = Path(__file__).with_name('unsent-recovery-upgrade.json')
SCOPE = frozenset({'automation/store.py', 'automation/integrity.py',
    'automation/control_integrity.py', 'cli/main.py', 'cli/automation.py',
    'cli/_shared.py', 'cli/authorized_routes.py'})
ADDITIONS = frozenset({'automation/unsent_recovery.py'})


def profile():
    raw = PROFILE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PROFILE_SHA256:
        raise ValueError('UNSENT_RECOVERY_PROFILE_CHANGED')
    value = json.loads(raw)
    if (set(value) != {'schema', 'files', 'additions', 'module_sha256'}
            or value['schema'] != 'sentinel.unsent-recovery-upgrade/1'
            or set(value['files']) != SCOPE or set(value['additions']) != ADDITIONS):
        raise ValueError('UNSENT_RECOVERY_PROFILE_SHAPE_CHANGED')
    module, count = re.subn(rb"^PROFILE_SHA256 = '[0-9a-f]{64}'$",
        b"PROFILE_SHA256 = '" + b'0'*64 + b"'", Path(__file__).read_bytes(), flags=re.M)
    if count != 1 or hashlib.sha256(module).hexdigest() != value['module_sha256']:
        raise ValueError('UNSENT_RECOVERY_MODULE_CHANGED')
    for record in value['files'].values():
        if (set(record) != {'before', 'after'}
                or not isinstance(record['before'], list) or not record['before']
                or len(record['before']) != len(set(record['before']))
                or any(not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha)
                       for sha in [*record['before'], record['after']])):
            raise ValueError('UNSENT_RECOVERY_SOURCE_RECORD_CHANGED')
    if any(not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha)
           for sha in value['additions'].values()):
        raise ValueError('UNSENT_RECOVERY_ADDITION_CHANGED')
    return value


def source_allowed(name, previous, actual):
    record = profile()['files'].get(name)
    return record is not None and previous in record['before'] and actual == record['after']


def additions_allowed(actual):
    return {name for name, sha in profile()['additions'].items() if actual.get(name) == sha}
