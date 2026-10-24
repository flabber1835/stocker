from collections import Counter
from copy import deepcopy
from dataclasses import replace
import hashlib
import inspect
import json
from pathlib import Path
import textwrap
from types import SimpleNamespace

import pytest

from sentinel import autonomy_runtime_upgrade as upgrade, runtime_admission as admission
from sentinel import transition_registry as registry
from sentinel.feed.rolling_contract import digest
from tests.sentinel.test_retained_source_compatibility import closure
from tests.sentinel.test_paper_composition_upgrade import _execution_closure, _refresh_current
from tests.support import historical_transition_fixture as historical


def test_profile_has_closed_scope_and_named_additions():
    assert upgrade.SCOPE == frozenset({
        'config.py', 'dual_reconciliation.py', 'execution/alpaca.py', 'execution/contract.py',
        'execution/feed_inputs.py', 'execution/fill_integrity.py',
        'execution/guarded.py', 'execution/journal.py', 'execution/reconcile.py',
        'feed/acquisition_part_schema.py', 'feed/acquisition_parts.py',
        'feed/action_history.py', 'feed/alpaca_observation.py', 'feed/alpaca_source.py',
        'feed/alpaca_transport.py', 'feed/history_retention_catalog.py',
        'feed/preparation_wait.py', 'feed/retention_schema.py',
        'feed/rolling_builder.py', 'feed/runtime_schema.py', 'schema.py', 'shadow_worker.py',
    })
    assert upgrade.ADDITIONS == {'trading_environment.py', 'autonomy_runtime_upgrade.py'}
    value = historical.profile(upgrade)
    assert set(value['files']) == upgrade.SCOPE
    assert set(value['additions']) == upgrade.ADDITIONS


@pytest.mark.parametrize('name', sorted(upgrade.SCOPE))
def test_exact_predecessors_and_full_authenticated_closure(closure, name):
    record = historical.profile(upgrade)['files'][name]
    actual = historical.target()[name]
    transitions = registry.load()
    assert (actual == record['after']
            or transitions.source_allowed(name, record['after'], actual,
                ('opening_latency','protected_cohort')))
    assert all(historical.source_allowed(upgrade,name,old,record['after']) for old in record['before'])
    assert not historical.source_allowed(upgrade,name,'f' * 64,actual)
    assert not historical.source_allowed(upgrade,name,record['before'][0],'f' * 64)
    assert not historical.source_allowed(upgrade,'core/kernel.py',record['before'][0],actual)
    root, checkpoint, context, manifest, source = _execution_closure(
        closure, name, source_profile=upgrade)
    assert admission.prove_compatibility(manifest, checkpoint, context, source=source) == digest(
        admission.SourceManifest.model_validate(manifest).model_dump(by_alias=True))
    path = root / name
    path.write_bytes(path.read_bytes() + b'\nUNREVIEWED_CHANGE=True\n')
    _refresh_current(root, context, source)
    with pytest.raises(admission.Refused):
        admission.prove_compatibility(manifest, checkpoint, context, source=source)


@pytest.mark.parametrize('kind', ['profile', 'module', 'admission_successor'])
def test_current_registry_authenticates_historical_profile_checker_and_admission_successor(
        tmp_path, monkeypatch, kind):
    historical.copy_registry_root(tmp_path)
    names = {'profile':'autonomy-runtime-upgrade.json',
             'module':'autonomy_runtime_upgrade.py',
             'admission_successor':next(spec.filename for spec in registry.PROFILES
                                       if spec.key=='native_read')}
    path = tmp_path/names[kind]
    assert path.is_file()
    path.write_bytes(path.read_bytes()+b'\nUNREVIEWED=True\n')
    monkeypatch.setattr(registry,'ROOT',tmp_path)
    with pytest.raises(ValueError, match='TRANSITION_WITNESS_CHANGED'):
        registry.load()


@pytest.mark.parametrize('defect', ['extra_file', 'missing_file', 'extra_addition', 'bad_predecessor'])
def test_descriptor_structure_stays_closed_even_when_its_digest_is_supplied(tmp_path, monkeypatch, defect):
    historical.copy_registry_root(tmp_path)
    value = deepcopy(historical.profile(upgrade))
    if defect == 'extra_file':
        value['files']['core/kernel.py'] = value['files']['shadow_worker.py']
    elif defect == 'missing_file':
        del value['files']['shadow_worker.py']
    elif defect == 'extra_addition':
        value['additions']['foreign.py'] = 'a' * 64
    else:
        value['files']['shadow_worker.py']['before'] = ['not-a-source-hash']
    raw = json.dumps(value).encode()
    path = tmp_path / upgrade.PROFILE.name
    path.write_bytes(raw)
    monkeypatch.setattr(registry,'ROOT',tmp_path)
    monkeypatch.setattr(registry,'PROFILES',tuple(
        replace(spec,sha256=hashlib.sha256(raw).hexdigest()) if spec.key=='autonomy' else spec
        for spec in registry.PROFILES))
    with pytest.raises(ValueError, match='PROFILE_SHAPE_CHANGED|SOURCE_RECORD_CHANGED|PROFILE_POLICY_CHANGED'):
        registry.load()


@pytest.mark.parametrize('name', sorted(upgrade.ADDITIONS))
@pytest.mark.parametrize('already_in_manifest', [False, True])
def test_additions_need_exact_bytes_including_when_previously_present(closure, name, already_in_manifest):
    root, checkpoint, context, manifest, source = closure
    path = root / name
    historical.write(root,name)
    actual = historical.source_files(root)[name]
    if already_in_manifest:
        previous = actual
        manifest['files'][name] = previous
        previous_env = deepcopy(source['environment'])
        previous_env['sentinel_source'].update(
            files=len(manifest['files']), hash=admission.source_closure(manifest['files']))
        checkpoint.runtime_identity.update(
            sentinel_source_sha256=previous_env['sentinel_source']['hash'],
            environment_identity_sha256=hashlib.sha256(json.dumps(previous_env, sort_keys=True).encode()).hexdigest())
        checkpoint.runtime_identity['reviewed_shadow_config']['validated_source_identity_sha256'] = (
            checkpoint.runtime_identity['environment_identity_sha256'])
    _refresh_current(root, context, source)
    assert historical.additions_allowed(upgrade,{name:actual}) == {name}
    assert historical.additions_allowed(upgrade,{name:'f' * 64}) == set()
    assert admission.prove_compatibility(manifest, checkpoint, context, source=source)
    path.write_bytes(path.read_bytes() + b'\nUNREVIEWED=True\n')
    _refresh_current(root, context, source)
    with pytest.raises(admission.Refused, match='CLOSURE_CHANGED'):
        admission.prove_compatibility(manifest, checkpoint, context, source=source)


def test_source_matching_reuses_validated_profiles_for_many_changed_files(closure, monkeypatch):
    root, checkpoint, context, manifest, source = closure
    for name in ('shadow_worker.py', 'execution/contract.py', 'feed/alpaca_source.py'):
        _execution_closure(closure, name, source_profile=upgrade)
    calls = Counter()
    original = registry.load_profiles
    def counted():
        calls['validated_registry'] += 1
        return original()
    monkeypatch.setattr(registry,'load_profiles',counted)
    assert admission.prove_compatibility(manifest, checkpoint, context, source=source)
    assert calls == {'validated_registry':1}


@pytest.mark.parametrize('name', ['core/kernel.py', 'core/session.py', 'rolling_runtime.py',
                                 'strategy.py', 'shadow_observation.py', 'core/rolling_inputs.py'])
def test_original_cash_source_transitions_survive_v2_without_rewriting_history(closure, name):
    original = registry.load_profiles()['legacy_economic']
    source_profile = SimpleNamespace(profile=lambda: original)
    _, checkpoint, context, manifest, source = _execution_closure(
        closure, name, source_profile=source_profile)
    assert admission.prove_compatibility(manifest, checkpoint, context, source=source)


def test_v2_changed_paths_bridge_only_the_authenticated_original_transitions():
    transitions = registry.load()
    legacy, current = (transitions.profiles[key] for key in ('legacy_economic','economic'))
    for name in set(legacy['files']) & set(current['files']):
        record = legacy['files'][name]
        actual = historical.target()[name]
        for previous in (*record['before'], record['after']):
            assert transitions.source_allowed(name,previous,actual,('economic','protected_cohort'))
            assert not transitions.source_allowed(name,previous,'f' * 64,('economic','protected_cohort'))
        assert not transitions.source_allowed(name,'f' * 64,actual,('economic','protected_cohort'))


def test_original_descriptor_is_independently_pinned(tmp_path, monkeypatch):
    from sentinel import economic_migration
    old = economic_migration.PROFILE.with_name('forward-cash-migration.json')
    (tmp_path / old.name).write_bytes(old.read_bytes() + b' ')
    monkeypatch.setattr(economic_migration, 'PROFILE', tmp_path / economic_migration.PROFILE.name)
    with pytest.raises(ValueError, match='LEGACY_ECONOMIC_MIGRATION_PROFILE_CHANGED'):
        economic_migration.legacy_profile()


def test_full_proof_refuses_an_unreviewed_predecessor_even_with_matching_origin(closure):
    _, checkpoint, context, manifest, source = _execution_closure(
        closure, 'shadow_worker.py', source_profile=upgrade)
    manifest['files']['shadow_worker.py'] = 'f' * 64
    previous_env = deepcopy(source['environment'])
    previous_env['sentinel_source'].update(
        files=len(manifest['files']), hash=admission.source_closure(manifest['files']))
    checkpoint.runtime_identity.update(
        sentinel_source_sha256=previous_env['sentinel_source']['hash'],
        environment_identity_sha256=hashlib.sha256(json.dumps(previous_env, sort_keys=True).encode()).hexdigest())
    checkpoint.runtime_identity['reviewed_shadow_config']['validated_source_identity_sha256'] = (
        checkpoint.runtime_identity['environment_identity_sha256'])
    with pytest.raises(admission.Refused, match='RETAINED_ECONOMIC_SOURCE_CHANGED:shadow_worker.py'):
        admission.prove_compatibility(manifest, checkpoint, context, source=source)


def test_removing_local_predecessor_check_is_detected(closure, monkeypatch):
    source = textwrap.dedent(inspect.getsource(registry.Transitions.source_allowed))
    needle = "record is not None and previous in record['before']"
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'record is not None'),
                 'predecessor-falsifier', 'exec'), registry.__dict__, namespace)
    monkeypatch.setattr(registry.Transitions,'source_allowed',namespace['source_allowed'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_full_proof_refuses_an_unreviewed_predecessor_even_with_matching_origin(closure)


def test_reintroducing_per_file_profile_reads_is_detected(closure, monkeypatch):
    source = textwrap.dedent(inspect.getsource(registry.Transitions.source_allowed))
    needle = '    for key in self.profiles if keys is None else keys:'
    assert source.count(needle) == 1
    replacement = '    load_profiles()\n'+needle
    namespace = {}
    exec(compile(source.replace(needle, replacement), 'profile-read-falsifier', 'exec'),
         registry.__dict__, namespace)
    monkeypatch.setattr(registry.Transitions,'source_allowed',namespace['source_allowed'])
    with pytest.raises(AssertionError):
        test_source_matching_reuses_validated_profiles_for_many_changed_files(closure, monkeypatch)
