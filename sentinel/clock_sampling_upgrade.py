from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


PROFILE_SHA256 = '885ce3556ee3eae0aab3a02af313dc20ecc5e28ceff9fffe0d1c96192b809372'
PROFILE = Path(__file__).with_name('clock-sampling-runtime-upgrade.json')
SCOPE = frozenset({'automation/service.py', 'runtime_admission.py', 'autonomy_runtime_upgrade.py'})
ADDITIONS = frozenset({'clock_sampling_upgrade.py'})
RETAINED_PROFILES = {
    'autonomy-runtime-upgrade.json': '09c9f7738ec5849284f239a07385af15faacb2c434b1d5e6ead31003622a9da9',
    'native-read-runtime-upgrade.json': '200f95d633527d829504ea77ce40994c8c06567303f0b1e4af2178bfd1b3591b',
    'open-time-upgrade.json': '282a161b42c8966ff6c6a75094d5085a3e9c6a42b11163fe6c3ffc8baf297b3d',
}
NATIVE_CHECKER_SHA256 = '6dfae675ef72e28f765c1d33a3702899bd86b6c45833a4daded73216a772c4e7'


def _normalized(content):
    value, count = re.subn(
        rb"^PROFILE_SHA256 = '[0-9a-f]{64}'$",
        b"PROFILE_SHA256 = '" + b'0' * 64 + b"'", content, flags=re.M)
    if count != 1:
        raise ValueError('CLOCK_SAMPLING_IMPLEMENTATION_CHANGED')
    return hashlib.sha256(value).hexdigest()


def profile():
    raw = PROFILE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PROFILE_SHA256:
        raise ValueError('CLOCK_SAMPLING_PROFILE_CHANGED')
    value = json.loads(raw)
    if (set(value) != {'schema', 'authority_effect', 'files', 'additions',
                       'module_sha256', 'autonomy_checker_normalized_sha256',
                       'retained_profiles', 'native_checker_sha256'}
            or value['schema'] != 'sentinel.clock-sampling-runtime-upgrade/1'
            or value['authority_effect'] != 'NONE'
            or set(value['files']) != SCOPE or set(value['additions']) != ADDITIONS):
        raise ValueError('CLOCK_SAMPLING_PROFILE_SHAPE_CHANGED')
    retained = {name: PROFILE.with_name(name).read_bytes() for name in RETAINED_PROFILES}
    if (value['retained_profiles'] != RETAINED_PROFILES
            or value['native_checker_sha256'] != NATIVE_CHECKER_SHA256
            or any(hashlib.sha256(retained[name]).hexdigest() != sha
                   for name, sha in RETAINED_PROFILES.items())
            or hashlib.sha256(PROFILE.with_name('native_read_upgrade.py').read_bytes()).hexdigest()
            != NATIVE_CHECKER_SHA256):
        raise ValueError('CLOCK_SAMPLING_RETAINED_SOURCE_CHANGED')
    native = json.loads(retained['native-read-runtime-upgrade.json'])
    service = json.loads(retained['open-time-upgrade.json'])['files']['automation/service.py']
    expected_before = {
        'automation/service.py': list(dict.fromkeys([*service['before'], service['after']])),
        'runtime_admission.py': [*native['files']['runtime_admission.py']['before'],
                                 native['files']['runtime_admission.py']['after']],
        'autonomy_runtime_upgrade.py': [*native['files']['autonomy_runtime_upgrade.py']['before'],
                                       native['files']['autonomy_runtime_upgrade.py']['after']],
    }
    for name, record in value['files'].items():
        if (set(record) != {'before', 'after'} or record['before'] != expected_before[name]
                or not isinstance(record['after'], str)
                or not re.fullmatch('[0-9a-f]{64}', record['after'])):
            raise ValueError('CLOCK_SAMPLING_SOURCE_RECORD_CHANGED')
    if (any(not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha)
            for sha in (*value['additions'].values(), value['module_sha256'],
                        value['autonomy_checker_normalized_sha256']))
            or value['module_sha256'] != value['additions']['clock_sampling_upgrade.py']):
        raise ValueError('CLOCK_SAMPLING_IMPLEMENTATION_CHANGED')
    normalized_sha = _normalized(Path(__file__).read_bytes())
    if normalized_sha != value['module_sha256']:
        from sentinel.idle_leader_upgrade import require_clock_checker_successor
        require_clock_checker_successor(normalized_sha)
    return value


def require_autonomy_successor(module_sha, admission_sha, *, original_module,
                                original_admission, original_profile):
    from sentinel import native_read_upgrade
    value = profile()
    if (original_module != native_read_upgrade.ORIGINAL_NORMALIZED_CHECKER
            or original_admission != native_read_upgrade.ORIGINAL_ADMISSION
            or original_profile != RETAINED_PROFILES['autonomy-runtime-upgrade.json']
            or module_sha != value['autonomy_checker_normalized_sha256']):
        raise ValueError('AUTONOMY_RUNTIME_IMPLEMENTATION_CHANGED')
    if admission_sha != value['files']['runtime_admission.py']['after']:
        from sentinel.idle_leader_upgrade import source_allowed
        if not source_allowed('runtime_admission.py',
                              value['files']['runtime_admission.py']['after'], admission_sha):
            raise ValueError('AUTONOMY_RUNTIME_IMPLEMENTATION_CHANGED')


def source_allowed(name, previous, actual):
    record = profile()['files'].get(name)
    return record is not None and previous in record['before'] and actual == record['after']


def additions_allowed(actual):
    value = profile()
    allowed = {name for name, sha in value['additions'].items() if actual.get(name) == sha}
    if actual.get('clock_sampling_upgrade.py') == hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
        allowed.add('clock_sampling_upgrade.py')
    return allowed
