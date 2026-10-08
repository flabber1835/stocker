"""Exact source repair for unsent dual-plan certificate renewal."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

PROFILE_SHA256 = '4ce64af26285d27d1ae00c52c6f7c78e808b5dcf205da07cecef906f8f46f64a'
PROFILE = Path(__file__).with_name('dual-plan-renewal-upgrade.json')
SCOPE = frozenset({'paper/preparation.py'})


def profile():
    raw = PROFILE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PROFILE_SHA256:
        raise ValueError('DUAL_PLAN_RENEWAL_PROFILE_CHANGED')
    value = json.loads(raw)
    if (set(value) != {'schema', 'files', 'module_sha256'}
            or value['schema'] != 'sentinel.dual-plan-renewal-upgrade/1'
            or set(value['files']) != SCOPE):
        raise ValueError('DUAL_PLAN_RENEWAL_PROFILE_SHAPE_CHANGED')
    module = Path(__file__).read_bytes()
    module, count = re.subn(rb"^PROFILE_SHA256 = '[0-9a-f]{64}'$",
        b"PROFILE_SHA256 = '" + b'0'*64 + b"'", module, flags=re.M)
    if count != 1 or hashlib.sha256(module).hexdigest() != value['module_sha256']:
        raise ValueError('DUAL_PLAN_RENEWAL_MODULE_CHANGED')
    for record in value['files'].values():
        if (set(record) != {'before', 'after'}
                or not isinstance(record['before'], list) or not record['before']
                or len(record['before']) != len(set(record['before']))
                or any(not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha)
                       for sha in [*record['before'], record['after']])):
            raise ValueError('DUAL_PLAN_RENEWAL_SOURCE_RECORD_CHANGED')
    return value


def source_allowed(name, previous, actual):
    record = profile()['files'].get(name)
    return record is not None and previous in record['before'] and actual == record['after']
