"""One complete URL-selected trading source edge, with no financial authority."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from sentinel import structural_refactor_source_basis as structural

BASE_REVISION = '403617ec3df4ba0950a989fa140038802f7e7b6e'
BASE_SOURCE_SHA256 = 'd83a9932ae32e0d87adde8691fcc36a7a8c1d93658f2c0ce954a211363918691'
STRUCTURAL_PROFILE_SHA256 = 'c362540d1e4364fb92216a7810116f1563ba035fd75c0e4d9eeb1f98e7e7782b'
PROFILE_SHA256 = 'ebd25d68bcc90e27c6d07b9090f94377b7722f879e4916f027a50f5e8c78f3d7'
PROFILE = Path(__file__).with_name('url-selected-trading-transition.json')
_SCHEMA = 'sentinel.url-selected-trading-transition/1'
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
            'base_files', 'candidate_files', 'module_sha256', 'structural_profile_sha256'}
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
    if (len(baseline) != 421 or _closure(baseline) != BASE_SOURCE_SHA256
            or baseline != expected or set(baseline) - set(candidate)
            or _SELF in baseline or _SELF in candidate):
        raise ValueError('URL_SOURCE_COMPLETE_MAP_CHANGED')
    return value


def predecessor_view(actual: Mapping[str, str]) -> Mapping[str, str]:
    """Translate only the complete sealed candidate; retain actual identities."""
    value = _profile()
    if value is None:
        return actual
    expected = dict(value['candidate_files'])
    expected[_SELF] = _sha(Path(__file__).read_bytes())
    if actual != expected:
        return actual
    return value['base_files']
