from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


PROFILE_SHA256 = '200f95d633527d829504ea77ce40994c8c06567303f0b1e4af2178bfd1b3591b'
PROFILE = Path(__file__).with_name('native-read-runtime-upgrade.json')
SCOPE = frozenset({'runtime_admission.py', 'autonomy_runtime_upgrade.py'})
ADDITIONS = frozenset({
    'native_read_upgrade.py', 'execution/native_readonly.py',
    'execution/native_activity.py', 'execution/alpaca_history.py',
    'execution/live_funding.py',
})
ORIGINAL_PROFILE = '09c9f7738ec5849284f239a07385af15faacb2c434b1d5e6ead31003622a9da9'
ORIGINAL_CHECKER = '9845046c7b3112f8b2f9ca06fb7c98dd058728d6767b6f5deab5e81c63f79dec'
ORIGINAL_NORMALIZED_CHECKER = 'd1374b8e76afe5a6319d316dffbb587cb8501fc8d5c5d7877787b4752ccf0057'
ORIGINAL_ADMISSION = 'fcf1228470a7a2a42dbc9534b05e66770a63d123281017aa0ffecfaf62a8f4b8'
ADMISSION_PREDECESSORS = (
    ORIGINAL_ADMISSION,
    'a73b7606409bab7f53fe65c991bd3fb1aa9d77c77f3bbb14603cdbc48dc945f0',
    '71b1a41073718a8cf39fcc48d9e6f70a01a39de9c64edbcc9c6e6988ff89cd0e',
    '67d9c6929921eeee50d5e855edeff8a8a282f8380212141e8bd4b224b2d91705',
    'ae76dd995f3ba44769ae933438f7d708783fb0a1a930b6939f29664811072276',
    '4b629db5827dce482070f2f1271f42894937f087e132286b37d265e565baa968',
    '1f3f95d3c8a5ddb81e57a6387536f8376efe7c3ecefeb8a4badf516e8e5491e4',
    'ba2f4da0c777aff553cbd8c6d83381cd26deeb4a4d3168baeaf3a4e0e1cf610e',
    'b74d74be6767674f9c186a160e4a0f983a93813e3236981109fae8d049cb96d0',
    '990f8810a1788c68b960f481dd4dbc8c134072b9b1b2af63fd277d37b40de7b6',
    '096e216e79c9f605a2fa210a6997c8dbecf42af0567e158a41ebb9bcab620d34',
    '033aafc80d6e391687c4512e5e2bb2f5b846af2ac28819d37c4868a5e68740b1',
    'c0e52e0bcfa13fb2540656d6cdd1ad7b9d266dc640aa4dd9f01f3eed711a8b0d',
    '1d00db9525d9af85590f469c56ccd57b6d6fdc6c51f40becf5325b284394fa9b',
    '4b3e4eec5f787ceb2d8ce3f4782b196df323032f1243a4b983376bd8a3580b91',
)


def _normalized(content):
    value, count = re.subn(
        rb"^PROFILE_SHA256 = '[0-9a-f]{64}'$",
        b"PROFILE_SHA256 = '" + b'0' * 64 + b"'", content, flags=re.M)
    if count != 1:
        raise ValueError('NATIVE_READ_IMPLEMENTATION_CHANGED')
    return hashlib.sha256(value).hexdigest()


def profile():
    raw = PROFILE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PROFILE_SHA256:
        raise ValueError('NATIVE_READ_PROFILE_CHANGED')
    value = json.loads(raw)
    keys = {'schema', 'authority_effect', 'files', 'additions', 'module_sha256',
            'autonomy_checker_normalized_sha256', 'original_profile_sha256',
            'original_checker_sha256', 'original_checker_normalized_sha256',
            'original_admission_sha256', 'admission_predecessor_witnesses'}
    if (set(value) != keys
            or value['schema'] != 'sentinel.native-read-runtime-upgrade/1'
            or value['authority_effect'] != 'NONE'
            or set(value['files']) != SCOPE
            or set(value['additions']) != ADDITIONS):
        raise ValueError('NATIVE_READ_PROFILE_SHAPE_CHANGED')
    originals = {
        'original_profile_sha256': ORIGINAL_PROFILE,
        'original_checker_sha256': ORIGINAL_CHECKER,
        'original_checker_normalized_sha256': ORIGINAL_NORMALIZED_CHECKER,
        'original_admission_sha256': ORIGINAL_ADMISSION,
    }
    if (any(value[key] != sha for key, sha in originals.items())
            or hashlib.sha256(PROFILE.with_name('autonomy-runtime-upgrade.json').read_bytes()).hexdigest()
            != ORIGINAL_PROFILE):
        raise ValueError('NATIVE_READ_ORIGINAL_PROFILE_CHANGED')
    expected_before = {
        'runtime_admission.py': list(ADMISSION_PREDECESSORS),
        'autonomy_runtime_upgrade.py': [ORIGINAL_CHECKER, ORIGINAL_NORMALIZED_CHECKER],
    }
    for name, record in value['files'].items():
        if (set(record) != {'before', 'after'}
                or record['before'] != expected_before[name]
                or not isinstance(record['after'], str)
                or not re.fullmatch('[0-9a-f]{64}', record['after'])):
            raise ValueError('NATIVE_READ_SOURCE_RECORD_CHANGED')
    witnesses = value['admission_predecessor_witnesses']
    if (not isinstance(witnesses, list) or len(witnesses) != len(ADMISSION_PREDECESSORS)
            or any(not isinstance(item, dict) or set(item) != {'revision', 'sha256'}
                   or not isinstance(item['revision'], str)
                   or not re.fullmatch('[0-9a-f]{40}', item['revision']) for item in witnesses)
            or tuple(item['sha256'] for item in witnesses) != ADMISSION_PREDECESSORS):
        raise ValueError('NATIVE_READ_PREDECESSOR_WITNESSES_CHANGED')
    if (any(not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha)
            for sha in (*value['additions'].values(), value['module_sha256'],
                        value['autonomy_checker_normalized_sha256']))
            or value['module_sha256'] != value['additions']['native_read_upgrade.py']
            or _normalized(Path(__file__).read_bytes()) != value['module_sha256']):
        raise ValueError('NATIVE_READ_IMPLEMENTATION_CHANGED')
    return value


def require_autonomy_successor(module_sha, admission_sha, *, original_module,
                                original_admission, original_profile):
    value = profile()
    if (original_module != ORIGINAL_NORMALIZED_CHECKER
            or original_admission != ORIGINAL_ADMISSION
            or original_profile != ORIGINAL_PROFILE
            or module_sha != value['autonomy_checker_normalized_sha256']
            or admission_sha != value['files']['runtime_admission.py']['after']):
        raise ValueError('AUTONOMY_RUNTIME_IMPLEMENTATION_CHANGED')


def source_allowed(name, previous, actual):
    record = profile()['files'].get(name)
    return record is not None and previous in record['before'] and actual == record['after']


def additions_allowed(actual):
    value = profile()
    allowed = {name for name, sha in value['additions'].items() if actual.get(name) == sha}
    if (actual.get('native_read_upgrade.py')
            == hashlib.sha256(Path(__file__).read_bytes()).hexdigest()):
        allowed.add('native_read_upgrade.py')
    return allowed
