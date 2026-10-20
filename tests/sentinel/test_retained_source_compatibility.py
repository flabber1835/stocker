"""Actual source mutations and authenticated old-source/environment closure."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sentinel import runtime_admission as admission, semantic_source_basis as basis
from sentinel.feed.rolling_contract import digest


import inspect
from sentinel import protected_cohort_upgrade as upgrade

@pytest.mark.parametrize('module', list(basis.HOOKS) + ['sentinel.core.decision'])
def test_forward_policy_changes_economic_identity_and_never_masks_neighbor_mutation(module):
    import importlib
    path = Path(importlib.import_module(module).__file__)
    raw = path.read_bytes()
    expected = basis.basis()['seams'][module]['source_sha256']
    assert basis.canonical_contribution(module, raw) == hashlib.sha256(raw).hexdigest()
    assert basis.canonical_contribution(module, raw) != expected
    # Change a real neighboring guard/algorithm, not the hook being masked.
    needle = {'sentinel.core.decision': b'if negative:',
              'sentinel.rolling_checkpoint': b'if payload != checkpoint.model_dump',
              'sentinel.rolling_daily_checkpoint': b'if alien:'}[module]
    assert needle in raw
    broken = raw.replace(needle, b'if False:' if needle.endswith(b':') else b'if False and payload != checkpoint.model_dump', 1)
    assert basis.canonical_contribution(module, broken) != basis.canonical_contribution(module, raw)


@pytest.mark.parametrize('module', list(basis.HOOKS))
def test_altered_admission_hook_is_not_ignored(module):
    import importlib
    raw = Path(importlib.import_module(module).__file__).read_bytes()
    broken = raw.replace(b'bind_context(conn, context)', b'bind_context(None, context)', 1)
    assert basis.canonical_contribution(module, broken) != basis.basis()['seams'][module]['source_sha256']


@pytest.mark.parametrize('header', [
    'def data_semantics_source_identity(argument=None) -> dict[str, object]:',
    '@changed\ndef data_semantics_source_identity() -> dict[str, object]:',
    'def data_semantics_source_identity() -> changed:',
])
def test_source_identity_recipe_header_cannot_hide_executable_changes(header):
    from sentinel.core import decision
    raw = Path(decision.__file__).read_bytes()
    needle = b'def data_semantics_source_identity() -> dict[str, object]:'
    assert raw.count(needle) == 1
    changed = raw.replace(needle, header.encode())
    assert basis.canonical_contribution('sentinel.core.decision', changed) != basis.basis()['seams']['sentinel.core.decision']['source_sha256']


def test_baseline_file_is_pinned(monkeypatch, tmp_path):
    path = tmp_path/'wrong.json'
    path.write_text('{}')
    monkeypatch.setattr(basis, 'BASIS_PATH', path)
    with pytest.raises(RuntimeError, match='baseline changed'):
        basis.basis()


@pytest.fixture
def closure(tmp_path, monkeypatch):
    root = tmp_path/'sentinel'
    root.mkdir()
    from sentinel import shadow_ui_upgrade as worker_upgrade
    reviewed_supervisor = (Path(worker_upgrade.__file__).parent/'shadow_supervisor.py').read_bytes()
    original = {'strategy.py': b'# exact economic source\n', 'shadow_supervisor.py': reviewed_supervisor}
    old_files = {name: hashlib.sha256(raw).hexdigest() for name, raw in original.items()}
    old_files['shadow_supervisor.py'] = worker_upgrade.profile()['files']['shadow_supervisor.py']['before'][0]
    current = {**original,
                'runtime_admission.py': Path(admission.__file__).read_bytes()}
    from sentinel import native_read_upgrade, clock_sampling_upgrade, idle_leader_upgrade, opening_latency_upgrade, protected_cohort_upgrade
    current.update({name: (Path(admission.__file__).parent / name).read_bytes()
                    for name in native_read_upgrade.ADDITIONS | clock_sampling_upgrade.ADDITIONS | idle_leader_upgrade.ADDITIONS | opening_latency_upgrade.ADDITIONS | protected_cohort_upgrade.ADDITIONS})
    for name, raw in current.items():
        path = root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    files = {name: hashlib.sha256(raw).hexdigest() for name, raw in current.items()}
    env = {'compatible': True, 'sentinel_source': {'root': 'sentinel', 'path': str(root),
        'files': len(files), 'hash': admission.source_closure(files)},
        'wealth_core_source': {'hash': '2'*64}, 'distributions_hash': '3'*64}
    previous_env = deepcopy(env)
    previous_env['sentinel_source'].update(files=len(old_files), hash=admission.source_closure(old_files))
    previous_hash = hashlib.sha256(json.dumps(previous_env, sort_keys=True).encode()).hexdigest()
    config = {'observation_id': 'primary', 'starting_cash': '50000', 'validated_source_identity_sha256': previous_hash}
    runtime = {'git_commit': '4'*40, 'sentinel_source_sha256': admission.source_closure(old_files),
        'wealth_core_source_sha256': '2'*64, 'environment_identity_sha256': previous_hash,
        'reviewed_shadow_config': config}
    checkpoint = SimpleNamespace(observation_id='primary', starting_cash='50000', strategy_identity={'strategy': 'same'}, runtime_identity=runtime)
    context = {'observation_id': 'primary', 'starting_cash': '50000', 'strategy': {'strategy': 'same'},
        'runtime': {**runtime, 'sentinel_source_sha256': admission.source_closure(files),
                    'reviewed_shadow_config': {**config, 'validated_source_identity_sha256': '5'*64}}}
    manifest = {'schema': 'sentinel.retained-source-manifest/1', 'revision': '4'*40, 'files': old_files}
    monkeypatch.setattr(admission.identity, '_imported_package_root', lambda _: root)
    return root, checkpoint, context, manifest, {'environment': env}


def test_authenticated_non_economic_upgrade_has_exact_environment_proof(closure):
    _, checkpoint, context, manifest, source = closure
    assert admission.prove_compatibility(manifest, checkpoint, context, source=source) == digest(
        admission.SourceManifest.model_validate(manifest).model_dump(by_alias=True))


@pytest.mark.parametrize('defect', ['manifest_hash', 'administrative_manifest_hash', 'revision', 'missing_file', 'foreign_addition',
    'removed_file', 'economic_change', 'environment_drift', 'wealth_drift', 'capital', 'observation', 'strategy'])
def test_compatibility_refuses_every_unproven_change(closure, defect):
    root, checkpoint, context, manifest, source = closure
    if defect == 'manifest_hash': manifest['files']['strategy.py'] = 'f'*64
    elif defect == 'administrative_manifest_hash': manifest['files']['shadow_supervisor.py'] = 'f'*64
    elif defect == 'revision': manifest['revision'] = 'f'*40
    elif defect == 'missing_file': del manifest['files']['strategy.py']
    elif defect == 'foreign_addition': (root/'new_economics.py').write_text('x=1')
    elif defect == 'removed_file': (root/'strategy.py').unlink()
    elif defect == 'economic_change':
        (root/'strategy.py').write_text('x=2')
        # Model an internally consistent new executable. A stale declared hash
        # would test only source attestation, not economic compatibility.
        files = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*.py')}
        context['runtime']['sentinel_source_sha256'] = admission.source_closure(files)
        source['environment']['sentinel_source']['hash'] = admission.source_closure(files)
    elif defect == 'environment_drift': source['environment']['distributions_hash'] = 'f'*64
    elif defect == 'wealth_drift': source['environment']['wealth_core_source']['hash'] = 'f'*64
    elif defect == 'capital': context['starting_cash'] = '1'
    elif defect == 'observation': context['observation_id'] = 'foreign'
    elif defect == 'strategy': context['strategy']['economic_policy'] = 'different'
    with pytest.raises(admission.Refused):
        admission.prove_compatibility(manifest, checkpoint, context, source=source)


@pytest.mark.parametrize('path', ['/absolute.py', '../escape.py', 'a/../escape.py', 'a\\b.py', 'x.txt', '__pycache__/x.py'])
def test_source_manifest_rejects_path_aliases(path):
    with pytest.raises(admission.Refused, match='PATH_INVALID'):
        admission.source_closure({path: 'a'*64})

# TestProtectedCohortSourceTransition owns the permanent cohort source contract.


class TestProtectedCohortSourceTransition:
    'Closed reviewed source transitions preserve retained book provenance.'

    @pytest.fixture(autouse=True)
    def _runtime_schema_test_double_compat(self):
        """Keep these cases' original real guards and explicit fixture inputs."""
        return None

    @pytest.fixture(autouse=True)
    def isolated_image_backup_policy(self):
        """Keep these cases' original real guards and explicit fixture inputs."""
        return None

    def test_profile_scope_predecessors_and_current_bytes_are_exact(self):
        value = upgrade.profile()
        assert value['authority_effect'] == 'NONE'
        assert value['base_revision'] == upgrade.BASE_REVISION
        for name, record in value['files'].items():
            actual = hashlib.sha256((upgrade.PROFILE.parent / name).read_bytes()).hexdigest()
            assert actual == record['after']
            assert upgrade.BASE_FILES[name] in record['before']
            assert all(upgrade.source_allowed(name, previous, actual) for previous in record['before'])
            assert not upgrade.source_allowed(name, 'f' * 64, actual)
            assert not upgrade.source_allowed(name, record['before'][0], 'f' * 64)
        assert not upgrade.source_allowed('core/kernel.py', 'f' * 64, 'f' * 64)

    @pytest.mark.parametrize('name', sorted(upgrade.SCOPE))
    def test_reviewed_base_transition_has_complete_authenticated_source_closure(self, closure, name):
        from tests.sentinel.test_paper_composition_upgrade import _execution_closure
        from tests.sentinel.test_clock_sampling_upgrade import _prior_binding
        _, checkpoint, context, manifest, source = _execution_closure(closure, name, source_profile=upgrade)
        manifest['files'][name] = upgrade.BASE_FILES[name]
        _prior_binding(checkpoint, manifest, source)
        assert admission.prove_compatibility(manifest, checkpoint, context, source=source)

    @pytest.mark.parametrize('name', sorted(upgrade.SCOPE))
    def test_adjacent_current_source_tamper_refuses_even_in_manifest(self, closure, name):
        from tests.sentinel.test_paper_composition_upgrade import _execution_closure
        from tests.sentinel.test_clock_sampling_upgrade import _prior_binding
        from tests.sentinel.test_paper_composition_upgrade import _refresh_current
        root, checkpoint, context, manifest, source = _execution_closure(closure, name, source_profile=upgrade)
        path = root / name
        path.write_bytes(path.read_bytes() + b'\nUNREVIEWED = True\n')
        manifest['files'][name] = hashlib.sha256(path.read_bytes()).hexdigest()
        _refresh_current(root, context, source)
        _prior_binding(checkpoint, manifest, source)
        with pytest.raises(admission.Refused, match='RETAINED_SOURCE_CLOSURE_CHANGED'):
            admission.prove_compatibility(manifest, checkpoint, context, source=source)

    @pytest.mark.parametrize('name', sorted(upgrade.ADDITIONS))
    def test_missing_addition_cannot_keep_a_current_source_closure(self, closure, name):
        from tests.sentinel.test_paper_composition_upgrade import _refresh_current
        root, checkpoint, context, manifest, source = closure
        (root / name).unlink()
        _refresh_current(root, context, source)
        with pytest.raises(admission.Refused, match='RETAINED_SOURCE_CLOSURE_CHANGED'):
            admission.prove_compatibility(manifest, checkpoint, context, source=source)

    @pytest.mark.parametrize('name', sorted(upgrade.ADDITIONS))
    @pytest.mark.parametrize('already_present', [False, True])
    def test_addition_tamper_refuses_even_when_claimed_in_prior_manifest(self, closure, name, already_present):
        from tests.sentinel.test_clock_sampling_upgrade import _prior_binding
        from tests.sentinel.test_paper_composition_upgrade import _refresh_current
        root, checkpoint, context, manifest, source = closure
        path = root / name
        if already_present:
            manifest['files'][name] = hashlib.sha256(path.read_bytes()).hexdigest()
        path.write_bytes(path.read_bytes() + b'\nUNREVIEWED = True\n')
        _refresh_current(root, context, source)
        _prior_binding(checkpoint, manifest, source)
        with pytest.raises(admission.Refused, match='RETAINED_SOURCE_CLOSURE_CHANGED'):
            admission.prove_compatibility(manifest, checkpoint, context, source=source)

    def test_atomic_additions_do_not_permit_a_missing_existing_source(self, closure):
        from tests.sentinel.test_paper_composition_upgrade import _refresh_current
        root, checkpoint, context, manifest, source = closure
        (root / 'strategy.py').unlink()
        _refresh_current(root, context, source)
        with pytest.raises(admission.Refused, match='RETAINED_SOURCE_CLOSURE_CHANGED'):
            admission.prove_compatibility(manifest, checkpoint, context, source=source)

    def test_new_neighbor_is_not_part_of_the_atomic_addition_set(self, closure):
        from tests.sentinel.test_paper_composition_upgrade import _refresh_current
        root, checkpoint, context, manifest, source = closure
        (root / 'execution/protected_neighbor.py').write_text('# unreviewed addition\n')
        _refresh_current(root, context, source)
        with pytest.raises(admission.Refused, match='RETAINED_SOURCE_CLOSURE_CHANGED'):
            admission.prove_compatibility(manifest, checkpoint, context, source=source)

    @pytest.mark.parametrize('defect', ['profile', 'module', 'retained_profile', 'predecessor', 'authority', 'witness', 'opening_checker',
                                      'missing_file', 'missing_addition', 'extra_file',
                                      'existing_as_addition', 'addition_as_existing'])
    def test_new_digest_cannot_widen_profile(self, tmp_path, monkeypatch, defect):
        for name in (*upgrade.RETAINED_PROFILES, upgrade.PROFILE.name):
            (tmp_path / name).write_bytes(upgrade.PROFILE.with_name(name).read_bytes())
        path = tmp_path / upgrade.PROFILE.name
        if defect == 'profile':
            path.write_bytes(path.read_bytes() + b' ')
        elif defect == 'module':
            module = tmp_path / 'protected_cohort_upgrade.py'
            module.write_bytes(Path(upgrade.__file__).read_bytes() + b'\nUNREVIEWED = True\n')
            monkeypatch.setattr(upgrade, '__file__', str(module))
        elif defect == 'retained_profile':
            prior = tmp_path / next(iter(upgrade.RETAINED_PROFILES))
            prior.write_bytes(prior.read_bytes() + b' ')
        else:
            value = deepcopy(json.loads(path.read_bytes()))
            if defect == 'predecessor':
                value['files']['paper/recovery.py']['before'] = ['f' * 64]
            elif defect == 'authority':
                value['authority_effect'] = 'LIVE'
            elif defect == 'opening_checker':
                value['opening_checker_normalized_sha256'] = 'f' * 64
            elif defect == 'missing_file':
                value['files'].pop('execution/executor.py')
            elif defect == 'missing_addition':
                value['additions'].pop('protected_cohort_upgrade.py')
            elif defect == 'extra_file':
                value['files']['core/unreviewed.py'] = value['files']['execution/executor.py']
            elif defect == 'existing_as_addition':
                value['additions']['execution/executor.py'] = value['files'].pop('execution/executor.py')['after']
            elif defect == 'addition_as_existing':
                added = value['additions'].pop('protected_cohort_upgrade.py')
                value['files']['protected_cohort_upgrade.py'] = {'before': [added], 'after': added}
            else:
                value['predecessor_witnesses'][0]['manifest_sha256'] = 'f' * 64
            raw = json.dumps(value).encode()
            path.write_bytes(raw)
            monkeypatch.setattr(upgrade, 'PROFILE_SHA256', hashlib.sha256(raw).hexdigest())
        monkeypatch.setattr(upgrade, 'PROFILE', path)
        with pytest.raises(ValueError, match='PROTECTED_COHORT_'):
            upgrade.profile()

    def test_complete_predecessor_manifests_are_independently_pinned(self, closure, monkeypatch):
        from tests.sentinel.test_operational_liveness_upgrade import test_complete_historical_source_manifest_is_admitted as _historical
        for witness in upgrade.profile()['predecessor_witnesses']:
            revision = witness['revision'][:8]
            fixture = Path(__file__).parent / 'fixtures/retained-source-history' / (revision + '.json')
            raw = fixture.read_bytes()
            assert hashlib.sha256(raw).hexdigest() == witness['manifest_sha256']
            value = json.loads(raw)
            assert {name: value['files'][name] for name in upgrade.SCOPE if name in value['files']} == witness['files']
            _historical(closure, monkeypatch, revision, witness['manifest_sha256'])

    @pytest.mark.parametrize('name', sorted(upgrade.ADDITIONS))
    def test_required_addition_has_behavioral_falsifier(self, closure, monkeypatch, name):
        # Isolate the admission backstop from the independently tested atomic
        # checker; either intact guard is sufficient to reject a missing member.
        monkeypatch.setattr(upgrade, 'additions_allowed', lambda actual: set(upgrade.ADDITIONS) & set(actual))
        source = inspect.getsource(admission.prove_compatibility)
        needle = '            or protected_cohort_upgrade.ADDITIONS - set(actual)\n'
        assert source.count(needle) == 1
        namespace = {}
        exec(compile(source.replace(needle, ''), 'opening-checker-falsifier', 'exec'), admission.__dict__, namespace)
        monkeypatch.setattr(admission, 'prove_compatibility', namespace['prove_compatibility'])
        with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
            self.test_missing_addition_cannot_keep_a_current_source_closure(closure, name)

    @pytest.mark.parametrize('name', sorted(upgrade.ADDITIONS))
    @pytest.mark.parametrize('damage', ['missing', 'changed'])
    def test_atomic_additions_unit_requires_all_exact_members(self, monkeypatch, name, damage):
        actual = {item: hashlib.sha256((Path(upgrade.__file__).parent / item).read_bytes()).hexdigest()
                  for item in upgrade.ADDITIONS}
        expected = dict(actual)
        expected['protected_cohort_upgrade.py'] = upgrade._normalized(Path(upgrade.__file__).read_bytes())
        monkeypatch.setattr(upgrade, 'profile', lambda: {'additions': expected})
        assert upgrade.additions_allowed(actual) == set(upgrade.ADDITIONS)
        if damage == 'missing':
            actual.pop(name)
        else:
            actual[name] = 'f' * 64
        assert upgrade.additions_allowed(actual) == set()

    def test_unknown_predecessor_guard_has_behavioral_falsifier(self, monkeypatch):
        source = inspect.getsource(upgrade.source_allowed)
        before = "previous in record['before']"
        assert source.count(before) == 1
        namespace = {}
        exec(compile(source.replace(before, 'True'), 'unknown-predecessor-falsifier', 'exec'), upgrade.__dict__, namespace)
        monkeypatch.setattr(upgrade, 'source_allowed', namespace['source_allowed'])
        with pytest.raises(AssertionError):
            self.test_profile_scope_predecessors_and_current_bytes_are_exact()

    def test_opening_checker_successor_is_exactly_pinned(self):
        from sentinel import opening_latency_upgrade
        normalized = opening_latency_upgrade._normalized(Path(opening_latency_upgrade.__file__).read_bytes())
        assert normalized == upgrade.OPENING_CHECKER_NORMALIZED_SHA256
        upgrade.require_opening_checker_successor(normalized)
        with pytest.raises(ValueError, match='OPENING_LATENCY_IMPLEMENTATION_CHANGED'):
            upgrade.require_opening_checker_successor('f' * 64)

    def test_opening_checker_normalization_guard_has_behavioral_falsifier(self, monkeypatch):
        self.test_opening_checker_successor_is_exactly_pinned()
        source = inspect.getsource(upgrade.require_opening_checker_successor)
        before = 'normalized_sha != OPENING_CHECKER_NORMALIZED_SHA256'
        assert source.count(before) == 1
        namespace = {}
        exec(compile(source.replace(before, 'False'), 'opening-checker-pin-falsifier', 'exec'),
             upgrade.__dict__, namespace)
        monkeypatch.setattr(upgrade, 'require_opening_checker_successor', namespace['require_opening_checker_successor'])
        with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
            self.test_opening_checker_successor_is_exactly_pinned()

    def _stage_changed_witness_projection(self, directory, monkeypatch, damage):
        original = upgrade.profile()
        value = deepcopy(original)
        added_paths = {'feed/readers.py', 'feed/rolling_go_health.py'}
        witness = value['predecessor_witnesses'][0]
        assert added_paths <= witness['files'].keys()
        fixture = (Path(__file__).parent / 'fixtures/retained-source-history'
                   / (witness['revision'][:8] + '.json'))
        full_raw = fixture.read_bytes()
        assert hashlib.sha256(full_raw).hexdigest() == witness['manifest_sha256']
        full = json.loads(full_raw)
        assert {name: full['files'][name] for name in added_paths} == {
            name: witness['files'][name] for name in added_paths}

        if damage == 'missing':
            for name in added_paths:
                witness['files'].pop(name)
        elif damage == 'changed':
            for name in added_paths:
                assert witness['files'][name] != 'f' * 64
                witness['files'][name] = 'f' * 64
        else:
            assert damage == 'foreign'
            assert 'feed/unreviewed_neighbor.py' not in upgrade.SCOPE
            witness['files']['feed/unreviewed_neighbor.py'] = 'f' * 64

        # Mutate only the current projection. Full-manifest identities and the
        # accepted predecessor hash sets retain their original exact values.
        assert value['files'] == original['files']
        assert [(item['revision'], item['manifest_sha256'])
                for item in value['predecessor_witnesses']] == [
            (item['revision'], item['manifest_sha256'])
            for item in original['predecessor_witnesses']]
        assert hashlib.sha256(json.dumps(value['predecessor_witnesses'],
            sort_keys=True, separators=(',', ':')).encode()).hexdigest() != upgrade.WITNESSES_SHA256

        directory.mkdir(exist_ok=True)
        for name, expected in upgrade.RETAINED_PROFILES.items():
            raw = upgrade.PROFILE.with_name(name).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == expected
            (directory / name).write_bytes(raw)
        path = directory / upgrade.PROFILE.name
        raw = json.dumps(value, sort_keys=True).encode()
        path.write_bytes(raw)
        monkeypatch.setattr(upgrade, 'PROFILE', path)
        monkeypatch.setattr(upgrade, 'PROFILE_SHA256', hashlib.sha256(raw).hexdigest())
        return value

    @pytest.mark.parametrize('damage', ['missing', 'changed', 'foreign'])
    def test_current_witness_projection_requires_both_new_paths_and_no_foreign_path(
            self, tmp_path, monkeypatch, damage):
        self._stage_changed_witness_projection(tmp_path, monkeypatch, damage)
        with pytest.raises(ValueError, match='^PROTECTED_COHORT_PROFILE_SHAPE_CHANGED$'):
            upgrade.profile()

    def test_witness_digest_guard_has_behavioral_falsifier(self, tmp_path, monkeypatch):
        source = inspect.getsource(upgrade.profile)
        needle = ("or hashlib.sha256(json.dumps(value['predecessor_witnesses'],\n"
                  "                sort_keys=True,separators=(',',':')).encode()).hexdigest() != WITNESSES_SHA256")
        assert source.count(needle) == 1
        # Both mutations leave the independent before-union checks intact:
        # the two historical values are already represented by retained
        # profiles, while a foreign path is outside the admitted source scope.
        for damage in ('missing', 'foreign'):
            with monkeypatch.context() as patch:
                changed = self._stage_changed_witness_projection(
                    tmp_path / damage, patch, damage)

                def require_exact_projection_refusal():
                    with pytest.raises(ValueError, match='^PROTECTED_COHORT_PROFILE_SHAPE_CHANGED$'):
                        upgrade.profile()

                require_exact_projection_refusal()
                namespace = {}
                exec(compile(source.replace(needle, 'or False'),
                    'removed-witness-digest-guard', 'exec'), upgrade.__dict__, namespace)
                patch.setattr(upgrade, 'profile', namespace['profile'])
                # Require actual acceptance of precisely this altered payload;
                # unrelated exceptions cannot satisfy the falsifier.
                assert upgrade.profile() == changed
                with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
                    require_exact_projection_refusal()
