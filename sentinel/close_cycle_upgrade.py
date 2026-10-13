"""Exact close-cycle observation and unsent-recovery admission over a retained book."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

PROFILE_SHA256 = '99b1dca749ca4ce0cac0115f6832b6556fcb9f06f01bdfaa7595fc4fd21a3c24'
PROFILE = Path(__file__).with_name('close-cycle-upgrade.json')
SCOPE = frozenset({'automation/unsent_recovery.py', 'automation_runtime.py', 'feed/rolling_go_inputs.py', 'shadow_service.py',
                   'feed/alpaca_source.py', 'feed/rolling_builder.py', 'core/rolling_inputs.py',
                   'observation_authority.py', 'feed/openfigi.py', 'rolling_reconstruction_evidence.py',
                   'rolling_recovery.py'})
ADDITIONS = frozenset({'feed/alpaca_identity.py'})


def profile():
    raw = PROFILE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PROFILE_SHA256:
        raise ValueError('CLOSE_CYCLE_PROFILE_CHANGED')
    value = json.loads(raw)
    if (set(value) != {'schema', 'files', 'additions', 'module_sha256'}
            or value['schema'] != 'sentinel.close-cycle-upgrade/1'
            or set(value['files']) != SCOPE or set(value['additions']) != ADDITIONS):
        raise ValueError('CLOSE_CYCLE_PROFILE_SHAPE_CHANGED')
    module, count = re.subn(rb"^PROFILE_SHA256 = '[0-9a-f]{64}'$",
        b"PROFILE_SHA256 = '"+b'0'*64+b"'", Path(__file__).read_bytes(), flags=re.M)
    if count != 1 or hashlib.sha256(module).hexdigest() != value['module_sha256']:
        raise ValueError('CLOSE_CYCLE_MODULE_CHANGED')
    for record in value['files'].values():
        if (set(record) != {'before', 'after'} or not isinstance(record['before'], list)
                or not record['before'] or len(set(record['before'])) != len(record['before'])
                or any(not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha)
                       for sha in [*record['before'], record['after']])):
            raise ValueError('CLOSE_CYCLE_SOURCE_RECORD_CHANGED')
    if any(not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha)
           for sha in value['additions'].values()):
        raise ValueError('CLOSE_CYCLE_ADDITION_CHANGED')
    return value


def source_allowed(name, previous, actual):
    record = profile()['files'].get(name)
    return record is not None and previous in record['before'] and actual == record['after']


def additions_allowed(actual):
    return {name for name, sha in profile()['additions'].items() if actual.get(name) == sha}
