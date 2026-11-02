"""One complete URL-selected trading source edge, with no financial authority."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from sentinel import structural_refactor_source_basis as structural

BASE_REVISION = '71b7c2a113dca8882f4cbf7a03d79f771e383092'
BASE_SOURCE_SHA256 = '85f353c936459255c048aedc366272ca4c6f3053f654a006da61a42af2688352'
RETAINED_REVISION = '403617ec3df4ba0950a989fa140038802f7e7b6e'
RETAINED_SOURCE_SHA256 = 'd83a9932ae32e0d87adde8691fcc36a7a8c1d93658f2c0ce954a211363918691'
STRUCTURAL_PROFILE_SHA256 = '12e5447817a8f583e2dbf57acfb7af857d0155f4600a2fff4bdef8d748aa429f'
PROFILE_SHA256 = '66fed3091ae132830e622522e3eb835152570834f18ef6ef23f0a556e51b481a'
PROFILE = Path(__file__).with_name('url-selected-trading-transition.json')
_SCHEMA = 'sentinel.url-selected-trading-transition/2'
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
    if (not isinstance(retained, dict) or set(retained) != {RETAINED_REVISION}
            or not isinstance(retained[RETAINED_REVISION], dict)
            or set(retained[RETAINED_REVISION]) != {'source_sha256', 'files'}
            or retained[RETAINED_REVISION]['source_sha256'] != RETAINED_SOURCE_SHA256
            or len(_source_map(retained[RETAINED_REVISION]['files'])) != 421
            or _closure(retained[RETAINED_REVISION]['files']) != RETAINED_SOURCE_SHA256
            or set(retained[RETAINED_REVISION]['files']) - set(baseline)):
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
    retained = value['retained_predecessors'][RETAINED_REVISION]['files']
    if previous == retained:
        return retained
    return value['base_files']
