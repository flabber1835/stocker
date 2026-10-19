"""Exact executable compatibility for idle scheduler availability; no authority."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


PROFILE_SHA256 = 'c037285eda8aba76adcf6be1fa8bbe97d5bc0f36a49123dcdce7fd8017dd9acb'
PROFILE = Path(__file__).with_name('idle-leader-runtime-upgrade.json')
BASE_REVISION = 'c0be72ed708b20cc8fff25b0cd8e1796889377f0'
BASE_FILES = {
    'automation/service.py': 'd7fca08f49744bb7927d4974a44ea1bd1fa27a2cb882269fc75fac03bc8ca778',
    'automation_runtime.py': 'f08f6cc746ccf4e8344eb4423def08752525ac658d3b67059104b3532eda0fa8',
    'alert_service.py': 'cb55423badcb6c9029f43df1845650fa1fc3fe2f23868e8a0b7f9e143baa82f4',
    'runtime_admission.py': '087fe6d1981122054f34aa83fc41c07d9c583cdaf185bf6e9b0f4e54598f6421',
    'clock_sampling_upgrade.py': 'd0565361b99373a786d2e639f4a58b9805555569138c56fca20f69974274e3ce',
}
SCOPE = frozenset(BASE_FILES)
ADDITIONS = frozenset({'idle_leader_upgrade.py'})
RETAINED_PROFILES = {
    'clock-sampling-runtime-upgrade.json': '885ce3556ee3eae0aab3a02af313dc20ecc5e28ceff9fffe0d1c96192b809372',
    'close-cycle-upgrade.json': '644d297796a7bb277d83c2e5936e29e21f3f5aeffdebd4e3cf0608d94302e3be',
    'open-time-upgrade.json': '282a161b42c8966ff6c6a75094d5085a3e9c6a42b11163fe6c3ffc8baf297b3d',
    'startup-contention-upgrade.json': 'a1131aa56c53dfeda652b798e8ec1042b58f8abe13819e02d0c9de84ce9f0920',
}


def _normalized(content):
    value, count = re.subn(
        rb"^PROFILE_SHA256 = '[0-9a-f]{64}'$",
        b"PROFILE_SHA256 = '" + b'0' * 64 + b"'", content, flags=re.M)
    if count != 1:
        raise ValueError('IDLE_LEADER_IMPLEMENTATION_CHANGED')
    return hashlib.sha256(value).hexdigest()


def profile():
    raw = PROFILE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PROFILE_SHA256:
        raise ValueError('IDLE_LEADER_PROFILE_CHANGED')
    value = json.loads(raw)
    if (set(value) != {'schema', 'authority_effect', 'base_revision', 'files',
                       'additions', 'module_sha256', 'retained_profiles',
                       'clock_checker_normalized_sha256'}
            or value['schema'] != 'sentinel.idle-leader-runtime-upgrade/1'
            or value['authority_effect'] != 'NONE'
            or value['base_revision'] != BASE_REVISION
            or set(value['files']) != SCOPE
            or set(value['additions']) != ADDITIONS
            or value['retained_profiles'] != RETAINED_PROFILES):
        raise ValueError('IDLE_LEADER_PROFILE_SHAPE_CHANGED')
    retained = []
    for name, expected in RETAINED_PROFILES.items():
        content = PROFILE.with_name(name).read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError('IDLE_LEADER_RETAINED_PROFILE_CHANGED')
        retained.append(json.loads(content))
    for name, record in value['files'].items():
        before = {BASE_FILES[name]}
        for previous in retained:
            old = previous['files'].get(name)
            if old is not None:
                before.update((*old['before'], old['after']))
        if (set(record) != {'before', 'after'}
                or record['before'] != sorted(before)
                or not isinstance(record['after'], str)
                or not re.fullmatch('[0-9a-f]{64}', record['after'])):
            raise ValueError('IDLE_LEADER_SOURCE_RECORD_CHANGED')
    hashes = (*value['additions'].values(), value['module_sha256'],
              value['clock_checker_normalized_sha256'])
    if (any(not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha)
            for sha in hashes)
            or value['module_sha256'] != value['additions']['idle_leader_upgrade.py']):
        raise ValueError('IDLE_LEADER_IMPLEMENTATION_CHANGED')
    normalized_sha = _normalized(Path(__file__).read_bytes())
    if normalized_sha != value['module_sha256']:
        from sentinel.opening_latency_upgrade import require_idle_checker_successor
        require_idle_checker_successor(normalized_sha)
    return value


def require_clock_checker_successor(normalized_sha):
    value = profile()
    actual = PROFILE.with_name('clock_sampling_upgrade.py').read_bytes()
    if (normalized_sha != value['clock_checker_normalized_sha256']
            or hashlib.sha256(actual).hexdigest()
            != value['files']['clock_sampling_upgrade.py']['after']):
        raise ValueError('CLOCK_SAMPLING_IMPLEMENTATION_CHANGED')


def source_allowed(name, previous, actual):
    record = profile()['files'].get(name)
    if record is not None and previous in record['before'] and actual == record['after']:
        return True
    from sentinel.opening_latency_upgrade import source_allowed as successor
    return successor(name, previous, actual)


def additions_allowed(actual):
    profile()
    current = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return {'idle_leader_upgrade.py'} if actual.get('idle_leader_upgrade.py') == current else set()
