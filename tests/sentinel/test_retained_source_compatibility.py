"""Actual source mutations and authenticated old-source/environment closure."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sentinel import runtime_admission as admission, semantic_source_basis as basis
from sentinel.feed.rolling_contract import digest


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
    original = {'strategy.py': b'# exact economic source\n', 'shadow_supervisor.py': b'# original supervision\n'}
    old_files = {name: hashlib.sha256(raw).hexdigest() for name, raw in original.items()}
    current = {**original, 'shadow_supervisor.py': b'# reviewed supervision fix\n',
               'runtime_admission.py': b'# reviewed admission module\n'}
    for name, raw in current.items():
        (root/name).write_bytes(raw)
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
