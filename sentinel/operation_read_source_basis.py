"""One qualified action-input read refactor; unknown bytes keep their identity."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

BASE_REVISION = '277160861e2353d8ad93d15da8e2615ebdb11c18'
BASELINES = {
    'sentinel.execution.reconcile': '0061e79de130e6c29f78b552a23322d77a7c9a9ce2ada56fa56dc12953cb07e2',
    'sentinel.execution.feed_actions': '8ce0436b4d58161f40ffb52900022529b23f3b565bdc9003a58eaa5f207e9b47',
}
CANDIDATES = {
    'sentinel.execution.reconcile': '0a49d779f60888ff1d0e79d532f857e528789b7c17feeb8ac7816cba231693d9',
    'sentinel.execution.feed_actions': '02fb6675efe5f1abce06a864b98d3cfa5423c8bda112762708626d516b17a1d5',
}
PROFILE_SHA256 = 'a6f7fd89ae3d7be3fa6a38e5d4e36a4fe1a2c1540dc5c3e2bfda5b20613ec282'
PROFILE = Path(__file__).with_name('operation-read-source-transition.json')


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            raise ValueError('OPERATION_READ_SOURCE_DUPLICATE_KEY')
        value[key] = item
    return value


def _normalized(raw):
    value, count = re.subn(rb"^PROFILE_SHA256 = '[a-f0-9]{64}'$",
        b"PROFILE_SHA256 = '"+b'0'*64+b"'", raw, flags=re.M)
    if count != 1:
        raise ValueError('OPERATION_READ_SOURCE_IMPLEMENTATION_CHANGED')
    return _sha(value)


def _profile():
    if PROFILE_SHA256 == '0'*64:
        return None
    raw = PROFILE.read_bytes()
    if _sha(raw) != PROFILE_SHA256:
        raise ValueError('OPERATION_READ_SOURCE_WITNESS_CHANGED')
    value = json.loads(raw, object_pairs_hook=_pairs)
    if (not isinstance(value, dict) or set(value) != {
            'schema', 'authority_effect', 'base_revision', 'compilers', 'module_sha256'}
            or value['schema'] != 'sentinel.operation-read-source-transition/1'
            or value['authority_effect'] != 'NONE' or value['base_revision'] != BASE_REVISION
            or not isinstance(value['compilers'], dict)
            or set(value['compilers']) != set(BASELINES)
            or value['module_sha256'] != _normalized(Path(__file__).read_bytes())):
        raise ValueError('OPERATION_READ_SOURCE_WITNESS_INVALID')
    for module, record in value['compilers'].items():
        if (not isinstance(record, dict) or set(record) != {'before', 'after'}
                or record['before'] != BASELINES[module]
                or record['after'] != CANDIDATES[module]):
            raise ValueError('OPERATION_READ_SOURCE_MEMBER_INVALID')
    return value


def contribution(module, raw):
    """Only a complete recognized compiler retains its independent old hash."""
    actual = _sha(raw)
    if module not in BASELINES:
        return actual
    from sentinel import fractional_execution_source_basis
    qualified = fractional_execution_source_basis.contribution(module, raw)
    value = _profile()
    actual = qualified
    if value is not None and actual == value['compilers'][module]['after']:
        return value['compilers'][module]['before']
    return _sha(raw)
