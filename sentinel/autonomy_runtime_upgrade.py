from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

PROFILE_SHA256 = '09c9f7738ec5849284f239a07385af15faacb2c434b1d5e6ead31003622a9da9'
PROFILE = Path(__file__).with_name('autonomy-runtime-upgrade.json')
SCOPE = frozenset({
    'config.py',
    'dual_reconciliation.py', 'execution/alpaca.py', 'execution/contract.py', 'execution/feed_inputs.py',
    'execution/fill_integrity.py', 'execution/guarded.py', 'execution/journal.py',
    'execution/reconcile.py', 'feed/acquisition_part_schema.py',
    'feed/acquisition_parts.py', 'feed/action_history.py',
    'feed/alpaca_observation.py', 'feed/alpaca_source.py',
    'feed/alpaca_transport.py', 'feed/history_retention_catalog.py',
    'feed/preparation_wait.py', 'feed/retention_schema.py',
    'feed/rolling_builder.py', 'feed/runtime_schema.py', 'schema.py',
    'shadow_worker.py',
})
ADDITIONS = frozenset({'trading_environment.py', 'autonomy_runtime_upgrade.py'})


def profile():
    raw = PROFILE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PROFILE_SHA256:
        raise ValueError('AUTONOMY_RUNTIME_PROFILE_CHANGED')
    value = json.loads(raw)
    if (set(value) != {'schema', 'files', 'additions', 'module_sha256',
                      'admission_sha256'}
            or value['schema'] != 'sentinel.autonomy-runtime-upgrade/1'
            or set(value['files']) != SCOPE
            or set(value['additions']) != ADDITIONS):
        raise ValueError('AUTONOMY_RUNTIME_PROFILE_SHAPE_CHANGED')
    module, count = re.subn(
        rb"^PROFILE_SHA256 = '[0-9a-f]{64}'$",
        b"PROFILE_SHA256 = '" + b'0' * 64 + b"'",
        Path(__file__).read_bytes(), flags=re.M,
    )
    if (count != 1 or hashlib.sha256(module).hexdigest() != value['module_sha256']
            or value['additions']['autonomy_runtime_upgrade.py'] != value['module_sha256']
            or hashlib.sha256(PROFILE.with_name('runtime_admission.py').read_bytes()).hexdigest()
            != value['admission_sha256']):
        raise ValueError('AUTONOMY_RUNTIME_IMPLEMENTATION_CHANGED')
    for record in value['files'].values():
        if (set(record) != {'before', 'after'}
                or not isinstance(record['before'], list) or not record['before']
                or len(record['before']) != len(set(record['before']))
                or any(not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha)
                       for sha in [*record['before'], record['after']])):
            raise ValueError('AUTONOMY_RUNTIME_SOURCE_RECORD_CHANGED')
    if any(not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha)
           for sha in value['additions'].values()):
        raise ValueError('AUTONOMY_RUNTIME_ADDITION_CHANGED')
    return value


def source_allowed(name, previous, actual):
    record = profile()['files'].get(name)
    return (record is not None and previous in record['before']
            and actual == record['after'])


def additions_allowed(actual):
    value = profile()
    allowed = {name for name, sha in value['additions'].items()
               if actual.get(name) == sha}
    normalized = re.sub(
        rb"^PROFILE_SHA256 = '[0-9a-f]{64}'$",
        b"PROFILE_SHA256 = '" + b'0' * 64 + b"'",
        Path(__file__).read_bytes(), flags=re.M,
    )
    if (actual.get('autonomy_runtime_upgrade.py')
            == hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
            and hashlib.sha256(normalized).hexdigest() == value['module_sha256']):
        allowed.add('autonomy_runtime_upgrade.py')
    return allowed
