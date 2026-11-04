"""One complete URL-selected trading source edge, with no financial authority."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from sentinel import structural_refactor_source_basis as structural

BASE_REVISION = 'e790d2120d3e0d69b0c7a8935ab2de8d9d2c4666'
BASE_SOURCE_SHA256 = '6d83f60c1503637cf0f6f8b6757d41ca47d5e1afa768da99c01a82d98b4c62db'
RETAINED_REVISION = '403617ec3df4ba0950a989fa140038802f7e7b6e'
RETAINED_SOURCE_SHA256 = 'd83a9932ae32e0d87adde8691fcc36a7a8c1d93658f2c0ce954a211363918691'
PREVIOUS_BASE_REVISION = '71b7c2a113dca8882f4cbf7a03d79f771e383092'
REVIEWED_PREDECESSOR_REVISION = 'bdb975c88c90a80c1ee7c98aed6dceeee12c8fc5'
DASHBOARD_PREDECESSOR_REVISION = 'f58c22fba3d3f88d410084d051ca86b7d99562df'
INSTALLED_PREDECESSOR_REVISION = '2e5e856c34e50958810a51f89e32b20db6a776a2'
PAPER_RELEASE_PREDECESSOR_REVISION = 'fcfbd7b1e8bd1134ad14563347ab9df0980c545f'
RETAINED_PREDECESSORS = {
    PAPER_RELEASE_PREDECESSOR_REVISION: (442, '95b41c4029df447215be2f04bcce5a25c7a4fe629e130cc37a673badc22cedca'),
    DASHBOARD_PREDECESSOR_REVISION: (440, 'a84f981e687970d230b197025a0b4260e9587aaf6381a7ecc64022761cfa02fa'),
    RETAINED_REVISION: (421, RETAINED_SOURCE_SHA256),
    PREVIOUS_BASE_REVISION: (422, '85f353c936459255c048aedc366272ca4c6f3053f654a006da61a42af2688352'),
    REVIEWED_PREDECESSOR_REVISION: (434, 'a8b6cce6e00654f402fd74735b66e0711331c44b3ea171e0241a40230b4096a4'),
    INSTALLED_PREDECESSOR_REVISION: (434, '85165e291f835307e86d45a1c678d44529ce42d1d46713614147c676ade7c47b'),
}
STRUCTURAL_PROFILE_SHA256 = '139d811983db0777eb6a92949e7e6adbe1c12d063c05d40c461f918cc741c5a0'
PROFILE_SHA256 = '930a620d6daa6d3295be9f13b0c3cf21ea8a0d9a073267b6448f167828fc38c7'
PROFILE = Path(__file__).with_name('url-selected-trading-transition.json')
_SCHEMA = 'sentinel.url-selected-trading-transition/6'
_SELF = 'url_selected_source_basis.py'


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('URL_SOURCE_PROFILE_DUPLICATE_KEY')
        result[key] = value
    return result


def _source_map(value: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError('URL_SOURCE_MAP_CHANGED')
    result = dict(value)
    for name, digest in result.items():
        if not isinstance(name, str) or not isinstance(digest, str):
            raise ValueError('URL_SOURCE_MAP_CHANGED')
        path = Path(name)
        if (path.is_absolute() or path.drive or '..' in path.parts
                or path.as_posix() != name or '\\' in name
                or '__pycache__' in path.parts or not name.endswith('.py')
                or re.fullmatch('[0-9a-f]{64}', digest) is None):
            raise ValueError('URL_SOURCE_MAP_CHANGED')
    return result


def _closure(files: Mapping[str, str]) -> str:
    result = hashlib.sha256()
    for name, digest in sorted(_source_map(files).items()):
        result.update(name.encode() + b'\0' + digest.encode() + b'\n')
    return result.hexdigest()


def _normalized(raw: bytes) -> str:
    normalized, count = re.subn(rb"^PROFILE_SHA256 = '[0-9a-f]{64}'$",
        b"PROFILE_SHA256 = '" + b'0' * 64 + b"'", raw, flags=re.M)
    if count != 1:
        raise ValueError('URL_SOURCE_IMPLEMENTATION_CHANGED')
    return _sha(normalized)


def _profile() -> dict | None:
    if PROFILE_SHA256 == '0' * 64:
        return None
    raw = PROFILE.read_bytes()
    if len(raw) > 1_000_000 or _sha(raw) != PROFILE_SHA256:
        raise ValueError('URL_SOURCE_PROFILE_CHANGED')
    value = json.loads(raw, object_pairs_hook=_pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite profile')))
    if (not isinstance(value, dict) or set(value) != {
            'schema', 'authority_effect', 'base_revision', 'base_source_sha256',
            'base_files', 'candidate_files', 'module_sha256', 'structural_profile_sha256',
            'retained_predecessors'}
            or value['schema'] != _SCHEMA or value['authority_effect'] != 'NONE'
            or value['base_revision'] != BASE_REVISION
            or value['base_source_sha256'] != BASE_SOURCE_SHA256
            or value['structural_profile_sha256'] != STRUCTURAL_PROFILE_SHA256
            or structural.TRANSITION_SHA256 != STRUCTURAL_PROFILE_SHA256
            or _normalized(Path(__file__).read_bytes()) != value['module_sha256']):
        raise ValueError('URL_SOURCE_PROFILE_SHAPE_CHANGED')
    baseline = _source_map(value['base_files'])
    candidate = _source_map(value['candidate_files'])
    sealed = structural._profile()
    if sealed is None:
        raise ValueError('URL_SOURCE_PREDECESSOR_UNSEALED')
    expected = dict(sealed['candidate_files'])
    expected['structural_refactor_source_basis.py'] = _sha(Path(structural.__file__).read_bytes())
    retained = value['retained_predecessors']
    if not isinstance(retained, dict) or set(retained) != set(RETAINED_PREDECESSORS):
        raise ValueError('URL_SOURCE_RETAINED_PREDECESSOR_CHANGED')
    for revision, (count, expected_sha) in RETAINED_PREDECESSORS.items():
        record = retained[revision]
        if (not isinstance(record, dict) or set(record) != {'source_sha256', 'files'}
                or record['source_sha256'] != expected_sha
                or len(_source_map(record['files'])) != count
                or _closure(record['files']) != expected_sha):
            raise ValueError('URL_SOURCE_RETAINED_PREDECESSOR_CHANGED')
        if revision in {REVIEWED_PREDECESSOR_REVISION, INSTALLED_PREDECESSOR_REVISION,
                        DASHBOARD_PREDECESSOR_REVISION, PAPER_RELEASE_PREDECESSOR_REVISION}:
            if not set(record['files']) <= set(candidate) | {_SELF}:
                raise ValueError('URL_SOURCE_RETAINED_PREDECESSOR_CHANGED')
        elif set(record['files']) - set(baseline):
            raise ValueError('URL_SOURCE_RETAINED_PREDECESSOR_CHANGED')
    if (len(baseline) != 422 or _closure(baseline) != BASE_SOURCE_SHA256
            or baseline != expected or set(baseline) - set(candidate)
            or _SELF in baseline or _SELF in candidate):
        raise ValueError('URL_SOURCE_COMPLETE_MAP_CHANGED')
    return value


def predecessor_view(actual: Mapping[str, str], *, previous=None) -> Mapping[str, str]:
    """Translate only the complete sealed candidate; retain actual identities."""
    value = _profile()
    if value is None:
        return actual
    expected = dict(value['candidate_files'])
    expected[_SELF] = _sha(Path(__file__).read_bytes())
    if actual != expected:
        return actual
    for record in value['retained_predecessors'].values():
        retained = record['files']
        if previous == retained:
            return retained
    return value['base_files']
