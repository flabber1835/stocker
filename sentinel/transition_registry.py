"""Strict historical source transitions, represented once as data and rules.

The original manifests and checker sources are authenticated witnesses. Loading
them does not execute the historical chain of self-referential validators.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from sentinel.transition_registry_specs import PROFILES

ROOT = Path(__file__).parent
_DIGEST = re.compile(r'[0-9a-f]{64}')
ADDITION_PROFILES = ('operational', 'recovery', 'ui', 'monitor', 'open_time',
                     'close_cycle', 'autonomy', 'native_read', 'clock_sampling',
                     'idle_leader', 'opening_latency', 'protected_cohort')
REQUIRED_ADDITIONS = ('native_read', 'clock_sampling', 'idle_leader',
                      'opening_latency', 'protected_cohort')
EXTENSIBLE_ADDITIONS = ('operational', 'recovery', 'ui', 'monitor', 'open_time',
                        'close_cycle', 'autonomy', 'clock_sampling', 'opening_latency')
ADDITION_SUCCESSORS = ('monitor', 'open_time', 'close_cycle', 'autonomy',
                       'native_read', 'clock_sampling', 'idle_leader',
                       'opening_latency', 'protected_cohort')
FILE_SUCCESSORS = {
    'native_read': ('clock_sampling', 'idle_leader', 'opening_latency', 'protected_cohort'),
    'clock_sampling': ('idle_leader', 'opening_latency', 'protected_cohort'),
    'idle_leader': ('opening_latency', 'protected_cohort'),
    'opening_latency': ('protected_cohort',),
    'protected_cohort': (),
}
NONADMINISTRATIVE_SCOPES = ('native_read', 'clock_sampling', 'idle_leader',
                           'opening_latency', 'protected_cohort')


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _path(name):
    path = Path(name)
    if (not isinstance(name, str) or path.is_absolute() or '..' in path.parts
            or path.as_posix() != name or '\\' in name):
        raise ValueError('TRANSITION_PROFILE_PATH_CHANGED')
    return ROOT / name


def _read_exact(name, expected):
    if not isinstance(expected, str) or not _DIGEST.fullmatch(expected):
        raise ValueError('TRANSITION_PROFILE_DIGEST_CHANGED')
    raw = _path(name).read_bytes()
    if _sha(raw) != expected:
        raise ValueError('TRANSITION_WITNESS_CHANGED:' + name)
    return raw


def _records(value):
    if not isinstance(value, dict):
        raise ValueError('TRANSITION_SOURCE_RECORD_CHANGED')
    for name, record in value.items():
        _path(name)
        if (not isinstance(record, dict) or set(record) != {'before', 'after'}
                or not isinstance(record['before'], list) or not record['before']
                or len(record['before']) != len(set(record['before']))
                or any(not isinstance(sha, str) or not _DIGEST.fullmatch(sha)
                       for sha in [*record['before'], record['after']])):
            raise ValueError('TRANSITION_SOURCE_RECORD_CHANGED')


def load_profiles():
    """Authenticate all immutable JSON and original current-baseline checkers.

    The pinned JSON authenticates each historical schema, scope, witness,
    predecessor list and normalized checker value. Exact checker pins retain
    their original implementation provenance without executing their old
    current-runtime comparisons against a later runtime.
    """
    result = {}
    for spec in PROFILES:
        _read_exact(spec.checker + '.py', spec.checker_sha256)
        value = json.loads(_read_exact(spec.filename, spec.sha256))
        if (not isinstance(value, dict) or set(value) != spec.keys
                or not isinstance(value.get('schema'), str)
                or value.get('authority_effect', 'NONE') != 'NONE'):
            raise ValueError('TRANSITION_PROFILE_SHAPE_CHANGED:' + spec.key)
        _records(value['files'])
        additions = value.get('additions', {})
        if not isinstance(additions, dict):
            raise ValueError('TRANSITION_ADDITIONS_CHANGED')
        for name, expected in additions.items():
            _path(name)
            if not isinstance(expected, str) or not _DIGEST.fullmatch(expected):
                raise ValueError('TRANSITION_ADDITIONS_CHANGED')
        for name, expected in value.get('retained_profiles', {}).items():
            _read_exact(name, expected)
        result[spec.key] = value
    # The forward-cash migration also pins its two actual source additions.
    for name, expected in result['economic'].get('additions', {}).items():
        raw = _path(name).read_bytes()
        if name == 'economic_migration.py':
            raw, count = re.subn(rb"^PROFILE_SHA256 = '[0-9a-f]{64}'$",
                b"PROFILE_SHA256 = '" + b'0' * 64 + b"'", raw, flags=re.M)
            if count != 1:
                raise ValueError('ECONOMIC_MIGRATION_ADDITION_CHANGED:' + name)
        if _sha(raw) != expected:
            raise ValueError('ECONOMIC_MIGRATION_ADDITION_CHANGED:' + name)
    return result


@dataclass(frozen=True)
class Transitions:
    profiles: Mapping[str, dict]

    def source_allowed(self, name, previous, actual, keys=None):
        for key in self.profiles if keys is None else keys:
            record = self.profiles[key]['files'].get(name)
            if (record is not None and previous in record['before']
                    and actual == record['after']):
                return True
        return False

    def additions_allowed(self, actual):
        specs = {spec.key: spec for spec in PROFILES}
        allowed = {}
        for key in ADDITION_PROFILES:
            expected = dict(self.profiles[key].get('additions', {}))
            checker = specs[key].checker + '.py'
            # Atomic checkers replace the normalized self digest. Individual
            # checkers retain their original declared digest as well as their
            # explicit actual-checker allowance; the file pins remain separate.
            if key in {'opening_latency', 'protected_cohort'}:
                expected[checker] = specs[key].checker_sha256
            if key in {'opening_latency', 'protected_cohort'}:
                allowed[key] = set(expected) if all(actual.get(n) == s for n, s in expected.items()) else set()
            elif key == 'idle_leader':
                allowed[key] = {checker} if actual.get(checker) == specs[key].checker_sha256 else set()
            else:
                allowed[key] = {n for n, s in expected.items() if actual.get(n) == s}
                if (key in {'autonomy', 'native_read', 'clock_sampling'}
                        and actual.get(checker) == specs[key].checker_sha256):
                    allowed[key].add(checker)
        # Preserve the predecessor atomic check: normalize only authenticated
        # protected-cohort successors before checking the entire opening set.
        expected = dict(self.profiles['opening_latency']['additions'])
        expected['opening_latency_upgrade.py'] = specs['opening_latency'].checker_sha256
        predecessor = dict(actual)
        for name, previous in self.profiles['opening_latency']['additions'].items():
            if self.source_allowed(name, previous, actual.get(name), ('protected_cohort',)):
                predecessor[name] = previous
        if all(predecessor.get(n) == s for n, s in expected.items()):
            allowed['opening_latency'].update(expected)
        for key in EXTENSIBLE_ADDITIONS:
            allowed[key].update(name for name, previous in self.profiles[key]['additions'].items()
                if actual.get(name) == previous or self.source_allowed(
                    name, previous, actual.get(name), ADDITION_SUCCESSORS))
        return allowed

    def closure_allowed(self, previous, actual, base_additions):
        allowed = self.additions_allowed(actual)
        if set(previous) - set(actual):
            return False
        if any(set(self.profiles[key]['additions']) - set(actual) for key in REQUIRED_ADDITIONS):
            return False
        additions = set().union(*allowed.values())
        if set(actual) - set(previous) - set(base_additions) - additions:
            return False
        if any((set(actual) & set(self.profiles[key]['additions'])) - allowed[key]
               for key in ADDITION_PROFILES):
            return False
        return not any(name in actual and actual[name] != record['after']
            and not self.source_allowed(name, record['after'], actual[name], successors)
            for key, successors in FILE_SUCCESSORS.items()
            for name, record in self.profiles[key]['files'].items())

    def administrative(self, administrative, additions):
        result = set(administrative)
        for key in ('ui', 'open_time', 'close_cycle'):
            result.difference_update(self.profiles[key]['files'])
        result.update(additions)
        for key in NONADMINISTRATIVE_SCOPES:
            result.difference_update(self.profiles[key]['files'])
        return result


def load():
    return Transitions(load_profiles())
