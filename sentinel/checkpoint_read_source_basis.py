"""One exact owned-checkpoint read wrapper; no financial authority."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

BASE_REVISION = 'e4d8671cb84af325fb5000cf8eaa2a4e0cf454c7'
BASELINES = {
    'sentinel.rolling_checkpoint': 'ca31b054df204efcc1b2a2c231ca5faeab51e0032ba1e1cad91188bcbfc40c64',
    'sentinel.rolling_daily_checkpoint': 'b82768e4c925f73bcb14878d245672f93a069d3e7139f7e0f65a5d1762110f3e',
}
CANDIDATES = {'sentinel.rolling_checkpoint': '5ad70f4e6fef66ede7392bf7371693cac808046ff47e7657349438a51d70058b', 'sentinel.rolling_daily_checkpoint': '8f93be6f455c17c8b6eeb17ab1bf8a20936338e6dc4da63692e0a6c6caf9d57b'}
PROFILE_SHA256 = '6a4c7aeac39104f363153d86134a55b44ca53433cce904c8be88f6eb63506432'
PROFILE = Path(__file__).with_name('checkpoint-read-source-transition.json')
_WRAPPER = (b'def read(conn):\n    from sentinel import committed_read\n'
            b'    return committed_read.checkpoint(conn, cursor=CURSOR, read=_read)\n\n\n'
            b'def _read(conn):\n')


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            raise ValueError('CHECKPOINT_READ_SOURCE_DUPLICATE_KEY')
        value[key] = item
    return value


def _normalized(raw):
    value, count = re.subn(rb"^PROFILE_SHA256 = '[a-f0-9]{64}'$",
        b"PROFILE_SHA256 = '"+b'0'*64+b"'", raw, flags=re.M)
    if count != 1:
        raise ValueError('CHECKPOINT_READ_SOURCE_IMPLEMENTATION_CHANGED')
    return _sha(value)


def _profile():
    raw = PROFILE.read_bytes()
    if _sha(raw) != PROFILE_SHA256:
        raise ValueError('CHECKPOINT_READ_SOURCE_WITNESS_CHANGED')
    value = json.loads(raw, object_pairs_hook=_pairs)
    if (not isinstance(value, dict) or set(value) != {
            'schema', 'authority_effect', 'base_revision', 'readers', 'module_sha256'}
            or value['schema'] != 'sentinel.checkpoint-read-source-transition/1'
            or value['authority_effect'] != 'NONE' or value['base_revision'] != BASE_REVISION
            or not isinstance(value['readers'], dict) or set(value['readers']) != set(BASELINES)
            or set(CANDIDATES) != set(BASELINES)
            or value['module_sha256'] != _normalized(Path(__file__).read_bytes())):
        raise ValueError('CHECKPOINT_READ_SOURCE_WITNESS_INVALID')
    for module, record in value['readers'].items():
        if (not isinstance(record, dict) or set(record) != {'before', 'after'}
                or record['before'] != BASELINES[module] or record['after'] != CANDIDATES[module]):
            raise ValueError('CHECKPOINT_READ_SOURCE_MEMBER_INVALID')
    return value


def predecessor(module, raw):
    """Reverse only the complete sealed wrapper to independently pinned bytes."""
    if module not in BASELINES or _sha(raw) != CANDIDATES.get(module):
        return raw
    value = _profile()
    if raw.count(_WRAPPER) != 1:
        raise ValueError('CHECKPOINT_READ_SOURCE_RECIPE_CHANGED')
    before = raw.replace(_WRAPPER, b'def read(conn):\n')
    if _sha(before) != value['readers'][module]['before']:
        raise ValueError('CHECKPOINT_READ_SOURCE_PREDECESSOR_CHANGED')
    return before
