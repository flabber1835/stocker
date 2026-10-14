"""Exact shadow-worker monitoring admission over a retained book."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

PROFILE_SHA256 = '865a6d8dbc9ce7a0999c9650154c3c9b66cf2cf93b5a5cce90fe14291c1b7ebf'
PROFILE = Path(__file__).with_name('shadow-ui-upgrade.json')
SCOPE = frozenset({'shadow_supervisor.py', 'shadow_worker_liveness.py', 'shadow_service_status.py', 'panel/sources.py', 'panel/render.py', 'panel/presentation.py',
                   'panel/app.py', 'panel/model.py', 'automation/outbox.py', 'web_push.py'})
ADDITIONS = frozenset({'shadow_service_status.py', 'paper_plan_preview.py', 'shadow_restart_recovery.py'})


def profile():
    raw = PROFILE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PROFILE_SHA256:
        raise ValueError('SHADOW_UI_PROFILE_CHANGED')
    value = json.loads(raw)
    if (set(value) != {'schema', 'files', 'additions', 'module_sha256'}
            or value['schema'] != 'sentinel.shadow-ui-upgrade/1'
            or set(value['files']) != SCOPE or set(value['additions']) != ADDITIONS):
        raise ValueError('SHADOW_UI_PROFILE_SHAPE_CHANGED')
    module, count = re.subn(rb"^PROFILE_SHA256 = '[0-9a-f]{64}'$",
        b"PROFILE_SHA256 = '" + b'0'*64 + b"'", Path(__file__).read_bytes(), flags=re.M)
    if count != 1 or hashlib.sha256(module).hexdigest() != value['module_sha256']:
        raise ValueError('SHADOW_UI_MODULE_CHANGED')
    for record in value['files'].values():
        if (set(record) != {'before', 'after'}
                or not isinstance(record['before'], list) or not record['before']
                or len(record['before']) != len(set(record['before']))
                or any(not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha)
                       for sha in [*record['before'], record['after']])):
            raise ValueError('SHADOW_UI_SOURCE_RECORD_CHANGED')
    if any(not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha)
           for sha in value['additions'].values()):
        raise ValueError('SHADOW_UI_ADDITION_CHANGED')
    return value


def source_allowed(name, previous, actual):
    record = profile()['files'].get(name)
    return record is not None and previous in record['before'] and actual == record['after']


def additions_allowed(actual):
    return {name for name, sha in profile()['additions'].items() if actual.get(name) == sha}
