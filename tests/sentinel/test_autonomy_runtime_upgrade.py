from sentinel import protected_cohort_upgrade
from collections import Counter
from copy import deepcopy
import hashlib
import importlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sentinel import autonomy_runtime_upgrade as upgrade, runtime_admission as admission
from sentinel import opening_latency_upgrade
from sentinel.feed.rolling_contract import digest
from tests.sentinel.test_retained_source_compatibility import closure
from tests.sentinel.test_paper_composition_upgrade import _execution_closure, _refresh_current


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
    value = upgrade.profile()
    assert set(value['files']) == upgrade.SCOPE
    assert set(value['additions']) == upgrade.ADDITIONS


@pytest.mark.parametrize('name', sorted(upgrade.SCOPE))
def test_exact_predecessors_and_full_authenticated_closure(closure, name):
    record = upgrade.profile()['files'][name]
    actual = hashlib.sha256((Path(upgrade.__file__).parent / name).read_bytes()).hexdigest()
    assert (actual == record['after']
            or (opening_latency_upgrade.source_allowed(name, record['after'], actual) or protected_cohort_upgrade.source_allowed(name, record['after'], actual)))
    assert all(upgrade.source_allowed(name, old, record['after']) for old in record['before'])
    assert not upgrade.source_allowed(name, 'f' * 64, actual)
    assert not upgrade.source_allowed(name, record['before'][0], 'f' * 64)
    assert not upgrade.source_allowed('core/kernel.py', record['before'][0], actual)
    root, checkpoint, context, manifest, source = _execution_closure(
        closure, name, source_profile=upgrade)
    assert admission.prove_compatibility(manifest, checkpoint, context, source=source) == digest(
        admission.SourceManifest.model_validate(manifest).model_dump(by_alias=True))
    path = root / name
    path.write_bytes(path.read_bytes() + b'\nUNREVIEWED_CHANGE=True\n')
    _refresh_current(root, context, source)
    with pytest.raises(admission.Refused):
        admission.prove_compatibility(manifest, checkpoint, context, source=source)


@pytest.mark.parametrize('kind', ['profile', 'module', 'admission'])
def test_profile_module_and_admission_implementation_authentication(tmp_path, monkeypatch, kind):
    if kind == 'module':
        path = tmp_path / 'module.py'
        path.write_bytes(Path(upgrade.__file__).read_bytes() + b'\nUNREVIEWED=True\n')
        monkeypatch.setattr(upgrade, '__file__', str(path))
    else:
        path = tmp_path / upgrade.PROFILE.name
        path.write_bytes(upgrade.PROFILE.read_bytes() + (b' ' if kind == 'profile' else b''))
        (tmp_path / 'runtime_admission.py').write_bytes(
            Path(admission.__file__).read_bytes() + (b'\nUNREVIEWED=True\n' if kind == 'admission' else b''))
        monkeypatch.setattr(upgrade, 'PROFILE', path)
    with pytest.raises(ValueError, match='PROFILE_CHANGED|IMPLEMENTATION_CHANGED'):
        upgrade.profile()


@pytest.mark.parametrize('defect', ['extra_file', 'missing_file', 'extra_addition', 'bad_predecessor'])
def test_descriptor_structure_stays_closed_even_when_its_digest_is_supplied(tmp_path, monkeypatch, defect):
    value = deepcopy(upgrade.profile())
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
    (tmp_path / 'runtime_admission.py').write_bytes(Path(admission.__file__).read_bytes())
    monkeypatch.setattr(upgrade, 'PROFILE', path)
    monkeypatch.setattr(upgrade, 'PROFILE_SHA256', hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError, match='SHAPE_CHANGED|SOURCE_RECORD_CHANGED'):
        upgrade.profile()


@pytest.mark.parametrize('name', sorted(upgrade.ADDITIONS))
@pytest.mark.parametrize('already_in_manifest', [False, True])
def test_additions_need_exact_bytes_including_when_previously_present(closure, name, already_in_manifest):
    root, checkpoint, context, manifest, source = closure
    path = root / name
    path.write_bytes((Path(upgrade.__file__).parent / name).read_bytes())
    if already_in_manifest:
        previous = hashlib.sha256(path.read_bytes()).hexdigest()
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
    assert upgrade.additions_allowed({name: hashlib.sha256(path.read_bytes()).hexdigest()}) == {name}
    assert upgrade.additions_allowed({name: 'f' * 64}) == set()
    assert admission.prove_compatibility(manifest, checkpoint, context, source=source)
    path.write_bytes(path.read_bytes() + b'\nUNREVIEWED=True\n')
    _refresh_current(root, context, source)
    with pytest.raises(admission.Refused, match='CLOSURE_CHANGED'):
        admission.prove_compatibility(manifest, checkpoint, context, source=source)


def test_source_matching_reuses_validated_profiles_for_many_changed_files(closure, monkeypatch):
    root, checkpoint, context, manifest, source = closure
    for name in ('shadow_worker.py', 'execution/contract.py', 'feed/alpaca_source.py'):
        _execution_closure(closure, name, source_profile=upgrade)
    modules = ('economic_migration', 'execution_upgrade', 'retained_readiness_upgrade',
               'dual_plan_renewal_upgrade', 'operational_liveness_upgrade',
               'operational_runtime_upgrade', 'callback_liveness_upgrade',
               'startup_contention_upgrade', 'unsent_recovery_upgrade',
               'shadow_ui_upgrade', 'dashboard_monitor_upgrade', 'open_time_upgrade',
               'close_cycle_upgrade', 'autonomy_runtime_upgrade')
    addition_modules = {'operational_runtime_upgrade', 'unsent_recovery_upgrade',
                        'shadow_ui_upgrade', 'dashboard_monitor_upgrade',
                        'open_time_upgrade', 'close_cycle_upgrade', 'autonomy_runtime_upgrade'}
    calls = Counter()
    for name in modules:
        module = importlib.import_module('sentinel.' + name)
        original = module.profile
        def counted(name=name, original=original):
            calls[name] += 1
            return original()
        monkeypatch.setattr(module, 'profile', counted)
    economic = importlib.import_module('sentinel.economic_migration')
    original_legacy = economic.legacy_profile
    def counted_legacy():
        calls['legacy_economic'] += 1
        return original_legacy()
    monkeypatch.setattr(economic, 'legacy_profile', counted_legacy)
    assert admission.prove_compatibility(manifest, checkpoint, context, source=source)
    assert calls == ({name: 1 + (name in addition_modules) for name in modules}
                     | {'legacy_economic': 1})


@pytest.mark.parametrize('name', ['core/kernel.py', 'core/session.py', 'rolling_runtime.py',
                                 'strategy.py', 'shadow_observation.py', 'core/rolling_inputs.py'])
def test_original_cash_source_transitions_survive_v2_without_rewriting_history(closure, name):
    from sentinel import economic_migration
    original = economic_migration.legacy_profile()
    source_profile = SimpleNamespace(profile=lambda: original)
    _, checkpoint, context, manifest, source = _execution_closure(
        closure, name, source_profile=source_profile)
    assert admission.prove_compatibility(manifest, checkpoint, context, source=source)


def test_v2_changed_paths_bridge_only_the_authenticated_original_transitions():
    from sentinel import economic_migration
    legacy = economic_migration.legacy_profile()
    current = economic_migration.profile()
    for name in set(legacy['files']) & set(current['files']):
        record = legacy['files'][name]
        actual = hashlib.sha256((Path(upgrade.__file__).parent / name).read_bytes()).hexdigest()
        for previous in (*record['before'], record['after']):
            assert (economic_migration.source_allowed(name, previous, actual)
                    or protected_cohort_upgrade.source_allowed(name, previous, actual))
            assert not (economic_migration.source_allowed(name, previous, 'f' * 64)
                        or protected_cohort_upgrade.source_allowed(name, previous, 'f' * 64))
        assert not (economic_migration.source_allowed(name, 'f' * 64, actual)
                    or protected_cohort_upgrade.source_allowed(name, 'f' * 64, actual))


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
    source = inspect.getsource(admission.prove_compatibility)
    needle = "record is not None and previous in record['before']"
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'record is not None'),
                 'predecessor-falsifier', 'exec'), admission.__dict__, namespace)
    monkeypatch.setattr(admission, 'prove_compatibility', namespace['prove_compatibility'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_full_proof_refuses_an_unreviewed_predecessor_even_with_matching_origin(closure)


def test_reintroducing_per_file_profile_reads_is_detected(closure, monkeypatch):
    source = inspect.getsource(admission.prove_compatibility)
    needle = '        for value in records:'
    assert source.count(needle) == 1
    replacement = ('        from sentinel.economic_migration import profile as reparse\n'
                   '        reparse()\n' + needle)
    namespace = {}
    exec(compile(source.replace(needle, replacement), 'profile-read-falsifier', 'exec'),
         admission.__dict__, namespace)
    monkeypatch.setattr(admission, 'prove_compatibility', namespace['prove_compatibility'])
    with pytest.raises(AssertionError):
        test_source_matching_reuses_validated_profiles_for_many_changed_files(closure, monkeypatch)
