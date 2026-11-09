"""Compact storage preserves independently pinned complete original inventories."""
from copy import deepcopy
import hashlib
import inspect
import json

import pytest

from scripts.sentinel_source_history import encoded
from sentinel import runtime_admission as admission, url_selected_source_basis as basis
from tests.support.source_history import expanded_profile


def test_original_twenty_two_maps_keep_the_independently_recorded_git_witness():
    profile = basis._profile()
    original = {revision: record for revision, record in profile['retained_predecessors'].items()
                if revision != basis.STARTUP_PROFILE_PREDECESSOR_REVISION}
    # Canonical aggregate of every complete map in Git 430462d95, independently
    # captured before conversion; no historical digest was re-pinned.
    assert len(original) == 22
    raw = json.dumps(original, sort_keys=True, separators=(',', ':')).encode()
    assert hashlib.sha256(raw).hexdigest() == 'e4d001f0bee019132a70eb069d002472b6a451b1921637e99d185ce56c8246a5'
    prior = profile['retained_predecessors'][basis.STARTUP_PROFILE_PREDECESSOR_REVISION]['files']
    assert len(prior) == 463
    assert admission.source_closure(prior) == 'fbacab07df6d2cc5410ad2e3ec3825b7e50a576ab2be0382e8dc37da123e8a5a'
    actual = admission._source_files(basis.PROFILE.parent)
    assert set(actual) == set(prior)
    assert {name for name in prior if actual[name] != prior[name]} == {
        'panel/projection_worker.py', 'panel/projection_service.py',
        'panel/presentation.py', 'url_selected_source_basis.py'}
    assert basis.predecessor_view(actual, previous=prior) == prior


def test_storage_is_small_and_roundtrip_preserves_every_logical_map():
    raw = basis.PROFILE.read_bytes()
    assert len(raw) < 250_000  # Existing outer security bound remains 1,000,000.
    logical = expanded_profile()
    assert encoded(logical) == raw
    assert logical == basis._profile()
    assert len(logical['retained_predecessors']) == 23


def test_shared_paths_are_validated_once_and_every_complete_map_is_still_hashed(monkeypatch):
    maps, closures = [], []
    original_map, original_closure = basis._source_map, basis._validated_closure
    def validated(value):
        maps.append(len(value))
        return original_map(value)
    def hashed(value):
        closures.append(len(value))
        return original_closure(value)
    monkeypatch.setattr(basis, '_source_map', validated)
    monkeypatch.setattr(basis, '_validated_closure', hashed)
    profile = basis._profile()
    assert len(maps) == 2+len(profile['retained_predecessors'])
    assert len(closures) == 1+len(profile['retained_predecessors'])
    assert sum(maps) < 2500


def repin_wire(tmp_path, monkeypatch, value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    target = tmp_path/'changed-profile.json'
    target.write_bytes(raw)
    monkeypatch.setattr(basis, 'PROFILE', target)
    monkeypatch.setattr(basis, 'PROFILE_SHA256', hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize('fault', ['redundant', 'conflict', 'duplicate', 'unsorted',
    'unknown_removal', 'bad_path', 'bad_digest', 'recursive', 'files', 'foreign_field', 'missing_map'])
def test_repinning_compact_wire_cannot_admit_ambiguous_or_foreign_maps(tmp_path, monkeypatch, fault):
    value = json.loads(basis.PROFILE.read_bytes())
    revision = basis.RETAINED_REVISION
    record = value['retained_predecessors'][revision]
    candidate = value['candidate_files']
    if fault == 'redundant':
        name = next(name for name in candidate if name not in record['overrides'] and name not in record['removed'])
        record['overrides'][name] = candidate[name]
    elif fault == 'conflict':
        name = next(name for name in record['overrides'] if name in candidate)
        record['removed'] = sorted([*record['removed'], name])
    elif fault == 'duplicate':
        record['removed'].append(record['removed'][0])
    elif fault == 'unsorted':
        record['removed'].reverse()
    elif fault == 'unknown_removal':
        record['removed'] = sorted([*record['removed'], 'unknown.py'])
    elif fault == 'bad_path':
        record['overrides']['../unknown.py'] = 'f'*64
    elif fault == 'bad_digest':
        record['overrides']['foreign.py'] = 'not-a-digest'
    elif fault == 'recursive':
        record['parent'] = revision
    elif fault == 'files':
        record['files'] = {}
    elif fault == 'missing_map':
        del value['retained_predecessors'][revision]
    else:
        record['foreign'] = True
    repin_wire(tmp_path, monkeypatch, value)
    with pytest.raises(ValueError, match='URL_SOURCE_'):
        basis._profile()


def test_redundant_delta_guard_has_an_executed_falsifier(tmp_path, monkeypatch):
    source = inspect.getsource(basis._expand_retained)
    guard = 'any(candidate.get(name) == digest for name, digest in overrides.items())'
    assert source.count(guard) == 1
    namespace = {}
    exec(compile(source.replace(guard, 'False'), 'removed-canonical-delta-guard', 'exec'),
         basis.__dict__, namespace)
    monkeypatch.setattr(basis, '_expand_retained', namespace['_expand_retained'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_repinning_compact_wire_cannot_admit_ambiguous_or_foreign_maps(tmp_path, monkeypatch, 'redundant')


def test_complete_map_count_remains_independently_pinned(tmp_path, monkeypatch):
    value = deepcopy(expanded_profile())
    revision = basis.STARTUP_PROFILE_PREDECESSOR_REVISION
    del value['retained_predecessors'][revision]['files']['panel/projection_worker.py']
    record = value['retained_predecessors'][revision]
    record['source_sha256'] = basis._closure(record['files'])
    repin_wire(tmp_path, monkeypatch, json.loads(encoded(value)))
    with pytest.raises(ValueError, match='RETAINED_PREDECESSOR_CHANGED'):
        basis._profile()


def test_source_map_count_has_a_finite_bound():
    with pytest.raises(ValueError,match='SOURCE_MAP_CHANGED'):
        basis._source_map({f'module{n}.py':'a'*64 for n in range(1025)})
