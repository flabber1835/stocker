"""Exact opening verification/readiness executable successor; no authority."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


PROFILE_SHA256 = 'a7122319426e657c4178b5c1f222e325a1060c48bdb76f5e0c00d68919325ff1'
PROFILE = Path(__file__).with_name('opening-latency-runtime-upgrade.json')
BASE_REVISION = '1e1db91b878d3073549a1e46337893882c3935b2'
BASE_FILES = {'feed/readers.py': 'e5be04df5104efbd3ad98f0b5f5fdf165c7f9ed8f65387485566772a54f786a0', 'rolling_runtime.py': 'f63e920c79fdd61bb1324ad32758be0dc01b3de4354254d22be2b7467f365da5', 'structural_verification.py': 'cf04409818079b566a9781c419872ee3f623b069f78eef6405bd8b71c27a985e', 'runtime_admission.py': 'ca9dcc6ff535fe2e90aa38cf8ecf386cfabe0f1aa5c70c94005e69f7d087e407', 'idle_leader_upgrade.py': '7a2199dbd8af0a64528f5fd1e9396bd7d96060e6272f3fdc06d6b88c898327ba', 'execution/opening_prices.py': 'e6d51d8f949cacf9903dd4afd7c65917bf0e89f3fcb7d4f84152fdf3fa23675f'}
RETAINED_PROFILES = {'autonomy-runtime-upgrade.json': '09c9f7738ec5849284f239a07385af15faacb2c434b1d5e6ead31003622a9da9', 'callback-liveness-upgrade.json': 'b7f8f033a61aa06eb24fcbf0cecca000d892830e20dd619a354e780cc6741fc0', 'clock-sampling-runtime-upgrade.json': '885ce3556ee3eae0aab3a02af313dc20ecc5e28ceff9fffe0d1c96192b809372', 'close-cycle-upgrade.json': '644d297796a7bb277d83c2e5936e29e21f3f5aeffdebd4e3cf0608d94302e3be', 'dashboard-monitor-upgrade.json': '1f9929e8ae0c9b739c28dd9115eeaf9a6c69c8ce4036d3b0382a7d6898ecbc69', 'dual-plan-renewal-upgrade.json': '6d8ba8f4b362cb39b100ab94fa8dfba2c4e8f6cd16232a3bc9fd6d8826d574d4', 'idle-leader-runtime-upgrade.json': 'c037285eda8aba76adcf6be1fa8bbe97d5bc0f36a49123dcdce7fd8017dd9acb', 'native-read-runtime-upgrade.json': '200f95d633527d829504ea77ce40994c8c06567303f0b1e4af2178bfd1b3591b', 'open-time-upgrade.json': '282a161b42c8966ff6c6a75094d5085a3e9c6a42b11163fe6c3ffc8baf297b3d', 'operational-liveness-upgrade.json': '3fd11d20e942a9eaf2c00684b7d6d1444cc1e91cf9528f9106e131e5bd15fb4b', 'operational-runtime-upgrade.json': '86d02b45ce868506668cb0e7cd330c047651f371f433926f7c2d8eb498e0f618', 'paper-composition-upgrade.json': 'bf41ee4968143f9cb42e844b1854dc7f3dd840ecfb674135e447b1b458e731a2', 'retained-readiness-upgrade.json': 'c190835a70e44aace35bd1bb3e8cf619c1bf55ce9d9f966f88a931efcf1a66e0', 'shadow-ui-upgrade.json': '1f3fe126b1cdffdf1e18eb88945d63be4b8bbe21de8bd86aa1c050919b59aa10', 'startup-contention-upgrade.json': 'a1131aa56c53dfeda652b798e8ec1042b58f8abe13819e02d0c9de84ce9f0920', 'unsent-recovery-upgrade.json': '2d59b3e68df1368f0f8f8ca4644f5f1a8334867fdbb0893ae216a7035faf1672'}
WITNESSES_SHA256 = '88fa2bb4d58cfe6294558e6fbd99bf72446af210ef8664553f56e9ede0c213f1'
SCOPE = frozenset(BASE_FILES)
ADDITIONS = frozenset({'opening_latency_upgrade.py'})


def _normalized(content):
    value, count = re.subn(
        rb"^PROFILE_SHA256 = '[0-9a-f]{64}'$",
        b"PROFILE_SHA256 = '" + b'0' * 64 + b"'", content, flags=re.M)
    if count != 1:
        raise ValueError('OPENING_LATENCY_IMPLEMENTATION_CHANGED')
    return hashlib.sha256(value).hexdigest()


def profile():
    raw = PROFILE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PROFILE_SHA256:
        raise ValueError('OPENING_LATENCY_PROFILE_CHANGED')
    value = json.loads(raw)
    if (set(value) != {'schema', 'authority_effect', 'base_revision', 'files',
                       'additions', 'module_sha256', 'retained_profiles',
                       'predecessor_witnesses', 'idle_checker_normalized_sha256'}
            or value['schema'] != 'sentinel.opening-latency-runtime-upgrade/1'
            or value['authority_effect'] != 'NONE'
            or value['base_revision'] != BASE_REVISION
            or set(value['files']) != SCOPE
            or set(value['additions']) != ADDITIONS
            or value['retained_profiles'] != RETAINED_PROFILES
            or hashlib.sha256(json.dumps(value['predecessor_witnesses'],
                sort_keys=True, separators=(',', ':')).encode()).hexdigest() != WITNESSES_SHA256):
        raise ValueError('OPENING_LATENCY_PROFILE_SHAPE_CHANGED')
    retained = []
    for name, expected in RETAINED_PROFILES.items():
        content = PROFILE.with_name(name).read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError('OPENING_LATENCY_RETAINED_PROFILE_CHANGED')
        retained.append(json.loads(content))
    for name, record in value['files'].items():
        before = {BASE_FILES[name]}
        for previous in retained:
            old = previous.get('files', {}).get(name)
            if old is not None:
                before.update((*old['before'], old['after']))
        for witness in value['predecessor_witnesses']:
            if name in witness['files']:
                before.add(witness['files'][name])
        if (set(record) != {'before', 'after'}
                or record['before'] != sorted(before)
                or not isinstance(record['after'], str)
                or not re.fullmatch('[0-9a-f]{64}', record['after'])):
            raise ValueError('OPENING_LATENCY_SOURCE_RECORD_CHANGED')
    hashes = (*value['additions'].values(), value['module_sha256'],
              value['idle_checker_normalized_sha256'])
    if (any(not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha)
            for sha in hashes)
            or value['module_sha256'] != value['additions']['opening_latency_upgrade.py']
            or _normalized(Path(__file__).read_bytes()) != value['module_sha256']):
        raise ValueError('OPENING_LATENCY_IMPLEMENTATION_CHANGED')
    return value


def require_idle_checker_successor(normalized_sha):
    value = profile()
    actual = PROFILE.with_name('idle_leader_upgrade.py').read_bytes()
    if (normalized_sha != value['idle_checker_normalized_sha256']
            or hashlib.sha256(actual).hexdigest()
            != value['files']['idle_leader_upgrade.py']['after']):
        raise ValueError('IDLE_LEADER_IMPLEMENTATION_CHANGED')


def source_allowed(name, previous, actual):
    record = profile()['files'].get(name)
    return record is not None and previous in record['before'] and actual == record['after']


def additions_allowed(actual):
    profile()
    current = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return {'opening_latency_upgrade.py'} if actual.get('opening_latency_upgrade.py') == current else set()
