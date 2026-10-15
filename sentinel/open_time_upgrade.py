"""Exact market-open verification and typed-alert admission over a retained book."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

PROFILE_SHA256 = 'b7f0d8ceccffb41145b59d5313cd2331789ff435f725feee5908b8003946a985'
PROFILE = Path(__file__).with_name('open-time-upgrade.json')
SCOPE = frozenset({'automation_runtime.py', 'panel/authority_reader.py', 'panel/model.py', 'panel/sources.py', 'structural_verification.py',
                   'paper/execution.py', 'paper/validation.py', 'shadow_worker.py', 'shadow_supervisor.py',
                   'rolling_runtime.py', 'informational_paper_mirror.py', 'paper_plan_preview.py',
                   'backup_runtime_authority.py'})
ADDITIONS = frozenset({'retained_input_namespaces.py'})


def profile():
    raw = PROFILE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PROFILE_SHA256:
        raise ValueError('OPEN_TIME_PROFILE_CHANGED')
    value = json.loads(raw)
    if (set(value) != {'schema', 'files', 'additions', 'module_sha256'}
            or value['schema'] != 'sentinel.open-time-upgrade/1'
            or set(value['files']) != SCOPE or set(value['additions']) != ADDITIONS):
        raise ValueError('OPEN_TIME_PROFILE_SHAPE_CHANGED')
    module, count = re.subn(rb"^PROFILE_SHA256 = '[0-9a-f]{64}'$",
        b"PROFILE_SHA256 = '"+b'0'*64+b"'", Path(__file__).read_bytes(), flags=re.M)
    if count != 1 or hashlib.sha256(module).hexdigest() != value['module_sha256']:
        raise ValueError('OPEN_TIME_MODULE_CHANGED')
    for record in value['files'].values():
        if (set(record) != {'before', 'after'} or not isinstance(record['before'], list)
                or not record['before'] or len(set(record['before'])) != len(record['before'])
                or any(not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha)
                       for sha in [*record['before'], record['after']])):
            raise ValueError('OPEN_TIME_SOURCE_RECORD_CHANGED')
    if any(not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha)
           for sha in value['additions'].values()):
        raise ValueError('OPEN_TIME_ADDITION_CHANGED')
    return value


def source_allowed(name, previous, actual):
    record = profile()['files'].get(name)
    return record is not None and previous in record['before'] and actual == record['after']


def additions_allowed(actual):
    return {name for name, sha in profile()['additions'].items() if actual.get(name) == sha}
