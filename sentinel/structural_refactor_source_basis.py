"""One sealed structural successor; unknown source never inherits old closure."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

BASE_REVISION = '0067e90b9f3a0e3e0b8c859fe4a90212e750ef16'
TRANSITION_SHA256 = 'c362540d1e4364fb92216a7810116f1563ba035fd75c0e4d9eeb1f98e7e7782b'
TRANSITION = Path(__file__).with_name('structural-refactor-transition.json')
ECONOMIC_PATHS = {
    'sentinel.execution.held_targets': 'execution/held_targets.py',
    'sentinel.execution.target_reprojection': 'execution/target_reprojection.py',
}


def _closure(files):
    if not isinstance(files, dict):
        raise ValueError('STRUCTURAL_TRANSITION_SOURCE_MAP_CHANGED')
    result = hashlib.sha256()
    for name, sha in sorted(files.items()):
        path = Path(name)
        if (not isinstance(name, str) or path.is_absolute() or '..' in path.parts
                or path.as_posix() != name or '\\' in name or not name.endswith('.py')
                or not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha)):
            raise ValueError('STRUCTURAL_TRANSITION_SOURCE_MAP_CHANGED')
        result.update(name.encode() + b'\0' + sha.encode() + b'\n')
    return result.hexdigest()


def _normalized(raw):
    value, count = re.subn(rb"^TRANSITION_SHA256 = '[0-9a-f]{64}'$",
        b"TRANSITION_SHA256 = '" + b'0' * 64 + b"'", raw, flags=re.M)
    if count != 1:
        raise ValueError('STRUCTURAL_TRANSITION_IMPLEMENTATION_CHANGED')
    return hashlib.sha256(value).hexdigest()


def _profile():
    if TRANSITION_SHA256 == '0' * 64:
        return None
    raw = TRANSITION.read_bytes()
    if hashlib.sha256(raw).hexdigest() != TRANSITION_SHA256:
        raise ValueError('STRUCTURAL_TRANSITION_PROFILE_CHANGED')
    value = json.loads(raw)
    if (set(value) != {'schema', 'authority_effect', 'base_revision', 'baseline_files',
                       'baseline_source_sha256', 'candidate_files', 'module_sha256'}
            or value['schema'] != 'sentinel.structural-refactor-transition/1'
            or value['authority_effect'] != 'NONE'
            or value['base_revision'] != BASE_REVISION
            or _closure(value['baseline_files']) != value['baseline_source_sha256']
            or value['baseline_files'].get('feed/rolling_publisher.py') !=
                '0911777fdce9a86a27e253856b6f0b9ed927a52124f8dcb4f078311a22a9d8e7'
            or _normalized(Path(__file__).read_bytes()) != value['module_sha256']):
        raise ValueError('STRUCTURAL_TRANSITION_PROFILE_SHAPE_CHANGED')
    _closure(value['candidate_files'])
    if 'structural_refactor_source_basis.py' in value['candidate_files']:
        raise ValueError('STRUCTURAL_TRANSITION_RECURSIVE_SELF_PIN')
    return value


def economic_contribution(module, raw):
    """Only the exact two reviewed financial extractions retain old semantics."""
    actual = hashlib.sha256(raw).hexdigest()
    path = ECONOMIC_PATHS.get(module)
    if path is None:
        return actual
    value = _profile()
    if value is not None and actual == value['candidate_files'].get(path):
        return value['baseline_files'][path]
    return actual


def historical_view(actual):
    """Return baseline hashes only for the complete exact reviewed successor.

    A missing seal grants no compatibility. The independently checked actual
    executable identity is never replaced by this historical comparison view.
    """
    value = _profile()
    if value is None:
        return actual
    expected = dict(value['candidate_files'])
    expected['structural_refactor_source_basis.py'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if actual != expected:
        return actual
    return value['baseline_files']
