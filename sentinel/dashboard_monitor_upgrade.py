"""Exact independent-dashboard monitoring admission over a retained book."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

PROFILE_SHA256 = '02453c63e30523c5995d1f364d3af19ac22b3112e5e4f2197e426c90e8963735'
PROFILE = Path(__file__).with_name('dashboard-monitor-upgrade.json')
SCOPE = frozenset({'feed/publication.py', 'panel/app.py', 'panel/authority_reader.py',
                   'panel/sources.py', 'panel/presentation.py', 'shadow_service_status.py'})
ADDITIONS = frozenset({'receipt_authentication.py', 'panel/verification_monitor.py',
                       'shadow_service_probe.py'})


def profile():
    raw = PROFILE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PROFILE_SHA256:
        raise ValueError('DASHBOARD_MONITOR_PROFILE_CHANGED')
    value = json.loads(raw)
    if (set(value) != {'schema', 'files', 'additions', 'module_sha256'}
            or value['schema'] != 'sentinel.dashboard-monitor-upgrade/1'
            or set(value['files']) != SCOPE or set(value['additions']) != ADDITIONS):
        raise ValueError('DASHBOARD_MONITOR_PROFILE_SHAPE_CHANGED')
    module, count = re.subn(rb"^PROFILE_SHA256 = '[0-9a-f]{64}'$",
        b"PROFILE_SHA256 = '"+b'0'*64+b"'", Path(__file__).read_bytes(), flags=re.M)
    if count != 1 or hashlib.sha256(module).hexdigest() != value['module_sha256']:
        raise ValueError('DASHBOARD_MONITOR_MODULE_CHANGED')
    for record in value['files'].values():
        if (set(record) != {'before', 'after'} or not isinstance(record['before'], list)
                or not record['before'] or len(set(record['before'])) != len(record['before'])
                or any(not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha)
                       for sha in [*record['before'], record['after']])):
            raise ValueError('DASHBOARD_MONITOR_SOURCE_RECORD_CHANGED')
    if any(not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha)
           for sha in value['additions'].values()):
        raise ValueError('DASHBOARD_MONITOR_ADDITION_CHANGED')
    return value


def source_allowed(name, previous, actual):
    record = profile()['files'].get(name)
    return record is not None and previous in record['before'] and actual == record['after']


def additions_allowed(actual):
    return {name for name, sha in profile()['additions'].items() if actual.get(name) == sha}
