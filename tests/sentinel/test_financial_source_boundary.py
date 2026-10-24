"""Exact structural financial extractions preserve the admitted economic book."""
import hashlib
import inspect
from pathlib import Path

import pytest

from sentinel import semantic_source_basis as semantics
from sentinel import structural_refactor_source_basis as basis
from sentinel.execution import held_targets, target_reprojection
from tests.support.financial_source_proofs import prove_factor_body, prove_full_reconstruction
from tests.support.publisher_source_proofs import baseline_catalog

MODULES = (
    ('sentinel.execution.held_targets', 'execution/held_targets.py', held_targets),
    ('sentinel.execution.target_reprojection', 'execution/target_reprojection.py', target_reprojection),
)


@pytest.mark.parametrize('module,path,implementation', MODULES)
def test_complete_current_module_mechanically_reconstructs_authenticated_git_baseline(module, path, implementation):
    raw = Path(implementation.__file__).read_bytes()
    prove_full_reconstruction(path, raw)
    assert basis.economic_contribution(module, raw) == baseline_catalog()['files'][path]
    value = semantics.economic_sources([module], schema='exact-financial-extraction-test')
    assert value['files'] == [{'module': module, 'sha256': baseline_catalog()['files'][path]}]


def test_extracted_public_factor_has_the_complete_original_exact_arithmetic_body():
    prove_factor_body()


@pytest.mark.parametrize('module,path,implementation', MODULES)
def test_unknown_neighbor_edits_keep_actual_economic_identity(module, path, implementation):
    raw = Path(implementation.__file__).read_bytes()
    changes = [raw + b'\n# unknown economic bytes\n']
    if implementation is held_targets:
        changes.append(raw.replace(b'if expected != basis:', b'if False:', 1))
        changes.append(raw.replace(b'previous.fingerprint()', b'previous.plan_id', 1))
    else:
        changes.append(raw.replace(b'multiplier <= 0', b'multiplier < 0', 1))
        changes.append(raw.replace(b'return exact\n', b'return published\n', 1))
    for changed in changes:
        assert changed != raw
        assert basis.economic_contribution(module, changed) == hashlib.sha256(changed).hexdigest()
        with pytest.raises((AssertionError, ValueError)):
            prove_full_reconstruction(path, changed)


def test_no_unlisted_module_can_gain_structural_economic_mapping():
    raw = Path(held_targets.__file__).read_bytes()
    assert basis.economic_contribution('sentinel.execution.unknown', raw) == hashlib.sha256(raw).hexdigest()


def test_unknown_financial_source_flows_through_real_semantic_bundle(monkeypatch):
    path = Path(held_targets.__file__).resolve()
    original = Path.read_bytes
    changed = original(path) + b'\n# unknown held target bytes\n'
    monkeypatch.setattr(Path, 'read_bytes', lambda p: changed if p == path else original(p))
    value = semantics.economic_sources(['sentinel.execution.held_targets'], schema='actual-financial-edit-test')
    assert value['files'] == [{'module': 'sentinel.execution.held_targets',
                               'sha256': hashlib.sha256(changed).hexdigest()}]


def test_financial_source_mapping_is_required_for_original_signed_strategy(monkeypatch):
    from sentinel.strategy import production_strategy
    from sentinel.feed.rolling_contract import digest
    expected = 'caab7a1872fe4ec178aec659716a4bc70c0cd5ea79a88e33ffacd2ae0c7cf095'
    assert digest(production_strategy()[1]) == expected
    monkeypatch.setattr(basis, 'economic_contribution', lambda _module, raw: hashlib.sha256(raw).hexdigest())
    assert digest(production_strategy()[1]) != expected


def test_closed_financial_mapping_has_behavioral_falsifier(monkeypatch):
    source = inspect.getsource(basis.economic_contribution)
    needle = "actual == value['candidate_files'].get(path)"
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, 'True'), 'unclosed-financial-map', 'exec'), basis.__dict__, namespace)
    monkeypatch.setattr(basis, 'economic_contribution', namespace['economic_contribution'])
    with pytest.raises(AssertionError):
        test_unknown_neighbor_edits_keep_actual_economic_identity(*MODULES[0])
