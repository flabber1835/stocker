"""All historical edges keep their closed acceptance and refusal behavior."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import inspect
import json
from pathlib import Path

import pytest

from sentinel import runtime_admission as admission
from sentinel import structural_refactor_source_basis as refactor
from sentinel import transition_registry as registry
from tests.support.legacy_transition_oracle import legacy_closure_allowed
from tests.support import historical_transition_fixture as historical
from tests.support import publisher_source_proofs as publisher_proofs
from tests.support.publisher_source_proofs import baseline_catalog, publisher_baseline, admission_baseline


@pytest.fixture
def transitions():
    return registry.load()


def _target(profiles):
    actual = {}
    for profile in profiles.values():
        actual.update(profile.get('additions', {}))
        actual.update({name: record['after'] for name, record in profile['files'].items()})
    for spec in registry.PROFILES:
        if spec.key in {'autonomy', 'native_read', 'clock_sampling', 'idle_leader',
                        'opening_latency', 'protected_cohort'}:
            actual[spec.checker + '.py'] = spec.checker_sha256
    return actual


def test_every_profile_and_original_checker_has_exact_pinned_bytes(transitions):
    assert len(transitions.profiles) == 20
    for spec in registry.PROFILES:
        assert hashlib.sha256((registry.ROOT / spec.filename).read_bytes()).hexdigest() == spec.sha256
        assert hashlib.sha256((registry.ROOT / (spec.checker + '.py')).read_bytes()).hexdigest() == spec.checker_sha256
        assert set(transitions.profiles[spec.key]) == spec.keys


def test_plain_git_catalog_and_independent_source_preimages_agree():
    catalog = baseline_catalog()
    assert len(catalog['files']) == 364
    assert set(catalog) == {'schema', 'revision', 'files'}
    assert hashlib.sha256(publisher_baseline()).hexdigest() == catalog['files']['feed/rolling_publisher.py']
    assert hashlib.sha256(admission_baseline()).hexdigest() == catalog['files']['runtime_admission.py']


def test_historical_hash_adapter_is_explicit_and_mutation_never_looks_authenticated(tmp_path):
    historical.write(tmp_path, 'runtime_admission.py')
    actual = admission._source_files(tmp_path)
    projected = historical.source_files(tmp_path)
    assert actual != projected  # The fixture is expressly not executable source.
    assert projected['runtime_admission.py'] == historical.target()['runtime_admission.py']
    path = tmp_path / 'runtime_admission.py'
    path.write_bytes(path.read_bytes() + b'\nUNREVIEWED = True\n')
    assert historical.source_files(tmp_path) == admission._source_files(tmp_path)
    assert historical.source_files(tmp_path) != projected


@pytest.mark.parametrize('owner', ['historical', 'publisher'])
def test_historical_source_reads_follow_the_imported_runtime_package(tmp_path, monkeypatch, owner):
    """The CI lens keeps tests and the installed runtime in separate roots."""
    module = historical if owner == 'historical' else publisher_proofs
    fixture_root = historical._fixtures()
    monkeypatch.setattr(historical, '_fixtures', lambda: fixture_root)
    monkeypatch.setattr(module, '__file__', str(tmp_path/'lens/tests/support'/Path(module.__file__).name))
    assert not (tmp_path/'lens/sentinel').exists()
    name = '__init__.py'
    actual = (registry.ROOT/name).read_bytes()
    assert hashlib.sha256(actual).hexdigest() == baseline_catalog()['files'][name]
    if owner == 'historical':
        target = tmp_path/'target'
        historical.write(target, name, expected=baseline_catalog()['files'][name])
        observed = (target/name).read_bytes()
    else:
        observed = publisher_proofs.baseline_source(name)
    assert observed == actual


@pytest.mark.parametrize('owner', ['historical', 'publisher'])
def test_repository_relative_source_reader_has_a_split_layout_falsifier(tmp_path, monkeypatch, owner):
    test_historical_source_reads_follow_the_imported_runtime_package(tmp_path, monkeypatch, owner)
    module, attribute = ((historical, 'write') if owner == 'historical'
                         else (publisher_proofs, 'baseline_source'))
    source = inspect.getsource(getattr(module, attribute))
    needle = 'transition_registry.ROOT / name'
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, "Path(__file__).parents[2] / 'sentinel' / name"),
                 'repository-relative-source-reader', 'exec'), module.__dict__, namespace)
    monkeypatch.setattr(module, attribute, namespace[attribute])
    with pytest.raises(FileNotFoundError):
        test_historical_source_reads_follow_the_imported_runtime_package(tmp_path, monkeypatch, owner)


def test_all_historical_before_edges_and_unknown_neighbors_are_closed(transitions):
    for key, profile in transitions.profiles.items():
        for name, record in profile['files'].items():
            for before in record['before']:
                assert transitions.source_allowed(name, before, record['after'], (key,))
                assert not transitions.source_allowed(name, 'f' * 64, record['after'], (key,))
                assert not transitions.source_allowed(name, before, 'f' * 64, (key,))
    assert not transitions.source_allowed('core/unknown.py', '0' * 64, '1' * 64)


def test_registry_matches_complete_frozen_legacy_condition_matrix(transitions):
    profiles = transitions.profiles
    target = _target(profiles)
    cases = [(dict(target), dict(target))]
    # Every source record and every predecessor is compared against the old
    # complete condition, including successor pin constraints and atomic sets.
    for profile in profiles.values():
        for name, record in profile['files'].items():
            for before in record['before']:
                previous, actual = dict(target), dict(target)
                previous[name], actual[name] = before, record['after']
                cases.append((previous, actual))
    # Missing, changed, pre-existing-tampered and neighboring additions must not
    # acquire permission through an already present old manifest entry.
    for name in target:
        for kind in ('missing', 'changed', 'changed-both'):
            previous, actual = dict(target), dict(target)
            if kind == 'missing':
                actual.pop(name)
            else:
                actual[name] = 'f' * 64
                if kind == 'changed-both':
                    previous[name] = 'f' * 64
            cases.append((previous, actual))
    cases.append((dict(target), {**target, 'execution/foreign.py': 'f' * 64}))
    results = []
    for previous, actual in cases:
        expected = legacy_closure_allowed(profiles, previous, actual, admission.ADDITIONS)
        observed = transitions.closure_allowed(previous, actual, admission.ADDITIONS)
        assert observed == expected, (previous, actual)
        results.append(observed)
    assert any(results) and not all(results)
    assert len(cases) > 1000


def test_required_addition_and_atomic_guards_have_independent_falsifier(transitions, monkeypatch):
    actual = _target(transitions.profiles)
    previous = dict(actual)
    missing = next(iter(transitions.profiles['protected_cohort']['additions']))
    actual.pop(missing)
    assert not transitions.closure_allowed(previous, actual, admission.ADDITIONS)
    # Remove the ordinary missing-old-file reason, isolating required presence.
    previous.pop(missing)
    original = registry.Transitions.additions_allowed
    def weakened(self, value):
        result = original(self, value)
        result['protected_cohort'] = set(self.profiles['protected_cohort']['additions']) & set(value)
        return result
    monkeypatch.setattr(registry.Transitions, 'additions_allowed', weakened)
    assert not transitions.closure_allowed(previous, actual, admission.ADDITIONS)
    monkeypatch.setattr(registry, 'REQUIRED_ADDITIONS', tuple(
        key for key in registry.REQUIRED_ADDITIONS if key != 'protected_cohort'))
    assert transitions.closure_allowed(previous, actual, admission.ADDITIONS)


def test_strict_source_edge_guard_has_behavioral_falsifier(transitions, monkeypatch):
    source = inspect.getsource(registry.Transitions.source_allowed)
    needle = "previous in record['before']"
    assert source.count(needle) == 1
    import textwrap
    namespace = {}
    exec(compile(textwrap.dedent(source).replace(needle, 'True'), 'unclosed-edge', 'exec'),
         registry.__dict__, namespace)
    monkeypatch.setattr(registry.Transitions, 'source_allowed', namespace['source_allowed'])
    with pytest.raises(AssertionError):
        test_all_historical_before_edges_and_unknown_neighbors_are_closed(transitions)


@pytest.mark.parametrize('kind', ['json', 'checker', 'retained'])
def test_unknown_historical_witness_bytes_refuse(tmp_path, monkeypatch, kind):
    for spec in registry.PROFILES:
        for name in (spec.filename, spec.checker + '.py'):
            (tmp_path / name).write_bytes((registry.ROOT / name).read_bytes())
        value = json.loads((registry.ROOT / spec.filename).read_bytes())
        for name in value.get('retained_profiles', {}):
            (tmp_path / name).write_bytes((registry.ROOT / name).read_bytes())
    if kind == 'json':
        name = registry.PROFILES[-1].filename
    elif kind == 'checker':
        name = registry.PROFILES[-1].checker + '.py'
    else:
        name = 'protected-cohort-runtime-preopen-predecessor.json'
    path = tmp_path / name
    path.write_bytes(path.read_bytes() + b' ')
    monkeypatch.setattr(registry, 'ROOT', tmp_path)
    with pytest.raises(ValueError, match='TRANSITION_WITNESS_CHANGED'):
        registry.load()


@pytest.mark.parametrize('defect', ['extra_file', 'missing_file', 'extra_addition',
    'bad_predecessor', 'valid_predecessor', 'schema', 'original', 'witness'])
def test_supplied_new_digest_never_widens_independent_profile_shape(
        tmp_path, monkeypatch, defect, _supply_policy=False):
    historical.copy_registry_root(tmp_path)
    key = 'native_read' if defect == 'original' else 'protected_cohort'
    spec = next(item for item in registry.PROFILES if item.key == key)
    path = tmp_path / spec.filename
    value = json.loads(path.read_bytes())
    sample = next(iter(value['files']))
    if defect == 'extra_file':
        value['files']['core/unknown.py'] = deepcopy(value['files'][sample])
    elif defect == 'missing_file':
        value['files'].pop(sample)
    elif defect == 'extra_addition':
        value['additions']['foreign.py'] = 'a' * 64
    elif defect == 'bad_predecessor':
        value['files'][sample]['before'] = ['not-a-source-hash']
    elif defect == 'valid_predecessor':
        value['files'][sample]['before'] = ['f' * 64]
    elif defect == 'schema':
        value['schema'] = 'sentinel.unknown-policy/1'
    elif defect == 'original':
        value['original_admission_sha256'] = 'f' * 64
    else:
        value['predecessor_witnesses'][0]['manifest_sha256'] = 'f' * 64
    raw = json.dumps(value).encode()
    path.write_bytes(raw)
    supplied = dict(sha256=hashlib.sha256(raw).hexdigest())
    if _supply_policy:
        supplied['policy_sha256'] = hashlib.sha256(json.dumps(value,sort_keys=True,
            separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()).hexdigest()
    monkeypatch.setattr(registry, 'ROOT', tmp_path)
    monkeypatch.setattr(registry, 'PROFILES', tuple(
        replace(item, **supplied) if item.key == spec.key else item
        for item in registry.PROFILES))
    with pytest.raises(ValueError, match='PROFILE_SHAPE_CHANGED|SOURCE_RECORD_CHANGED|PROFILE_POLICY_CHANGED'):
        registry.load()


def test_independent_scope_guard_has_supplied_digest_behavioral_falsifier(tmp_path, monkeypatch):
    source = inspect.getsource(registry.load_profiles)
    needle = "or set(value.get('files', {})) != spec.scope"
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'or False'), 'missing-independent-scope', 'exec'),
         registry.__dict__, namespace)
    monkeypatch.setattr(registry, 'load_profiles', namespace['load_profiles'])
    # Supply the independently tested payload pin only within this mutant to
    # isolate the structural scope backstop from the policy-content guard.
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_supplied_new_digest_never_widens_independent_profile_shape(
            tmp_path, monkeypatch, 'extra_file', _supply_policy=True)


def test_independent_policy_payload_guard_has_behavioral_falsifier(tmp_path, monkeypatch):
    source = inspect.getsource(registry.load_profiles)
    needle = '_sha(policy) != spec.policy_sha256'
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'False'), 'missing-policy-witness', 'exec'),
         registry.__dict__, namespace)
    monkeypatch.setattr(registry, 'load_profiles', namespace['load_profiles'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_supplied_new_digest_never_widens_independent_profile_shape(tmp_path, monkeypatch, 'valid_predecessor')


def test_unsealed_refactor_cannot_normalize_unknown_current_source(monkeypatch):
    monkeypatch.setattr(refactor, 'TRANSITION_SHA256', '0' * 64)
    actual = {'runtime_admission.py': 'f' * 64}
    assert refactor.historical_view(actual) is actual


def test_current_full_refactor_seal_preserves_exact_baseline_and_refuses_unknown_bytes():
    # This is a release gate, not an optional fixture. Root writes the reviewed
    # seal only after all changed source scopes are final.
    assert refactor.TRANSITION_SHA256 != '0' * 64
    actual = {path.relative_to(registry.ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in registry.ROOT.rglob('*.py') if '__pycache__' not in path.parts}
    baseline = refactor.historical_view(actual)
    assert baseline is not actual
    assert 'publisher_pipeline_source_basis.py' not in baseline
    for name in actual:
        changed = {**actual, name: 'f' * 64}
        assert refactor.historical_view(changed) is changed
    missing = {k: v for k, v in actual.items() if k != 'feed/publisher_pipeline.py'}
    assert refactor.historical_view(missing) is missing
    extra = {**actual, 'unreviewed_extra.py': 'f' * 64}
    assert refactor.historical_view(extra) is extra
