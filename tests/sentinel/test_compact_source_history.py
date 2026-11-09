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
    original_revisions = {
        '29ff5f6592a46e89f13ed5d8416503071dc74ccf',
        '2e5e856c34e50958810a51f89e32b20db6a776a2',
        '34a28504a87610fd5c159115fc0b75017ae944ea',
        '35e3a118a8ee4d4efea5857f6e96d4dd8e23724a',
        '403617ec3df4ba0950a989fa140038802f7e7b6e',
        '4122aa29bc86dcf5c4e5d6a91047030a95bf9890',
        '4a08f5961a2dd0d5b174509b6afa4aa7d61d88a3',
        '4a395bfb4f13ba0f34fa0121fa62991fe7b38fed',
        '4bca82da1daff430b4f087493e4f200d2e9719dd',
        '64da9cccb49040acc4f32434bcdf6c31b7b6259e',
        '67458b20746979d08b8091f4519122bca528174f',
        '71b7c2a113dca8882f4cbf7a03d79f771e383092',
        '8fafcfae9c46f471a834d7bd221497d6d940732a',
        'a0a82c6ad9211fdcf9fdad9faa801b8af65239ea',
        'b0d516022b1cc20375d987e7cf94236ce061710f',
        'ba05fe76950fe6d976e08edaadfd88a9e39dec0e',
        'bdb975c88c90a80c1ee7c98aed6dceeee12c8fc5',
        'c0d4ed7b6888e63c9d49584c6fcf063c6950f8f9',
        'c2569a4cb5085db15e24222478a1d5c98c53c74f',
        'e97a15753a71cb7e4e033db6171f1a2ee0e15955',
        'f58c22fba3d3f88d410084d051ca86b7d99562df',
        'fcfbd7b1e8bd1134ad14563347ab9df0980c545f',
    }
    original = {revision: profile['retained_predecessors'][revision] for revision in original_revisions}
    # Canonical aggregate of every complete map in Git 430462d95, independently
    # captured before conversion; no historical digest was re-pinned.
    assert len(original) == 22
    raw = json.dumps(original, sort_keys=True, separators=(',', ':')).encode()
    assert hashlib.sha256(raw).hexdigest() == 'e4d001f0bee019132a70eb069d002472b6a451b1921637e99d185ce56c8246a5'
    prior = profile['retained_predecessors'][basis.STARTUP_PROFILE_PREDECESSOR_REVISION]['files']
    assert len(prior) == 463
    assert admission.source_closure(prior) == 'fbacab07df6d2cc5410ad2e3ec3825b7e50a576ab2be0382e8dc37da123e8a5a'
    actual = profile['retained_predecessors'][basis.ACTIVATION_HEALTH_PREDECESSOR_REVISION]['files']
    assert set(actual) == set(prior)
    assert {name for name in prior if actual[name] != prior[name]} == {
        'panel/projection_worker.py', 'panel/projection_service.py',
        'panel/presentation.py', 'url_selected_source_basis.py'}
    assert basis.predecessor_view(admission._source_files(basis.PROFILE.parent), previous=prior) == prior


def test_storage_is_small_and_roundtrip_preserves_every_logical_map():
    raw = basis.PROFILE.read_bytes()
    assert len(raw) < 250_000  # Existing outer security bound remains 1,000,000.
    logical = expanded_profile()
    assert encoded(logical) == raw
    assert logical == basis._profile()
    assert set(logical['retained_predecessors']) == set(basis.RETAINED_PREDECESSORS)


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
