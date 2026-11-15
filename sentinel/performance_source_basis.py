"""Closed source witness for the reviewed runtime allocation refactor."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

PROFILE_SHA256 = 'df9dca6ca5e47ab8893d85e6aa77b754ad7f95a38cdd1232d1363712c58723e6'
PROFILE = Path(__file__).with_name('performance-source-transition-v2.json')
BASE_REVISION = 'c585b7ff1f5a443720b4ce7585bd4fac36c84118'
WINDOW_PREDECESSOR = '5b760ca4aee27759d1aa1cf164d439b85b58646a'
BASELINES = {
    'sentinel.core.session': '221a20b69eb3ad0dc877bec7789de608fe85dc6397891b8c9060bbd1f66717e8',
    'sentinel.core.window_material': '3bd34707705bc97bd815d5da82d59ef2bcbd32e36a7e203851d7f5fff3361d76',
    'sentinel.feed.universe': '48fd9b18b13433c51c0e9e7d9e981e42620e2792ef6b3bcbc3dd233261c1080c',
    'stock_strategy_shared.wealth_core.feed': 'afa9324811921271a139500764aee19b85dec96f9a499d392c12f25f97e6ee32',
}


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            raise ValueError('PERFORMANCE_SOURCE_DUPLICATE_KEY')
        value[key] = item
    return value


def _profile():
    raw = PROFILE.read_bytes()
    if PROFILE_SHA256 == '0'*64 or _sha(raw) != PROFILE_SHA256:
        raise ValueError('PERFORMANCE_SOURCE_WITNESS_CHANGED')
    value = json.loads(raw, object_pairs_hook=_pairs)
    normalized, count = re.subn(rb"^PROFILE_SHA256 = '[0-9a-f]{64}'$",
        b"PROFILE_SHA256 = '"+b'0'*64+b"'", Path(__file__).read_bytes(), flags=re.M)
    if (count != 1 or not isinstance(value, dict)
            or set(value) != {'schema', 'authority_effect', 'base_revision',
                              'window_predecessor', 'modules', 'module_sha256'}
            or value['schema'] != 'sentinel.performance-source-transition/2'
            or value['authority_effect'] != 'NONE'
            or value['base_revision'] != BASE_REVISION
            or value['window_predecessor'] != WINDOW_PREDECESSOR
            or not isinstance(value['modules'], dict)
            or set(value['modules']) != set(BASELINES)
            or value['module_sha256'] != _sha(normalized)):
        raise ValueError('PERFORMANCE_SOURCE_WITNESS_INVALID')
    for name, record in value['modules'].items():
        if (not isinstance(record, dict) or set(record) != {'before', 'after'}
                or record['before'] != BASELINES[name]
                or not isinstance(record['after'], str)
                or not re.fullmatch('[0-9a-f]{64}', record['after'])):
            raise ValueError('PERFORMANCE_SOURCE_MEMBER_INVALID')
    return value


def contribution(module, raw):
    """Unknown bytes and every other module retain their actual identity."""
    actual = _sha(raw)
    if module not in BASELINES:
        return actual
    record = _profile()['modules'][module]
    return record['before'] if actual == record['after'] else actual


def wealth_core_source_hash(root):
    """The strategy-only package commitment; runtime attestation stays actual."""
    from sentinel.identity import source_hash

    def member(relative, raw):
        if relative == 'feed.py':
            return contribution('stock_strategy_shared.wealth_core.feed', raw)
        return _sha(raw)

    return source_hash(root, _contribution=member)
