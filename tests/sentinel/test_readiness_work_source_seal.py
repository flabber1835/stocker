"""The reviewed performance successor is exact; unknown neighbors stay unknown."""
import hashlib
import inspect
from pathlib import Path

import pytest

from sentinel import structural_refactor_source_basis as basis


def _current():
    root = Path(basis.__file__).parent
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*.py') if '__pycache__' not in path.parts}


def test_complete_optimized_runtime_preserves_only_the_authenticated_baseline():
    actual = _current()
    profile = basis._profile()
    expected = dict(profile['candidate_files'])
    expected[Path(basis.__file__).name] = actual[Path(basis.__file__).name]
    assert actual == expected
    assert basis.historical_view(actual) == profile['baseline_files']
    assert basis._closure(profile['baseline_files']) == (
        '56890ee50268961357faf2f6a8c2dc66ca76eb74c7440c832ba3a7bd06a09e15')
    assert profile['authority_effect'] == 'NONE'


def _every_unknown_neighbor_refuses():
    actual = _current()
    for name in actual:
        changed = dict(actual)
        changed[name] = hashlib.sha256((actual[name] + 'unreviewed').encode()).hexdigest()
        assert basis.historical_view(changed) == changed, name


def test_every_single_file_unknown_successor_keeps_its_actual_identity():
    _every_unknown_neighbor_refuses()


@pytest.mark.parametrize('defect', ['missing', 'extra'])
def test_incomplete_or_extended_runtime_cannot_borrow_the_seal(defect):
    changed = _current()
    if defect == 'missing':
        del changed['panel/read_projection.py']
    else:
        changed['unreviewed.py'] = '0' * 64
    assert basis.historical_view(changed) == changed


def test_removed_complete_source_guard_is_detected(monkeypatch):
    source = inspect.getsource(basis.historical_view)
    guard = 'if actual != expected:'
    assert source.count(guard) == 1
    namespace = dict(basis.__dict__)
    exec(compile(source.replace(guard, 'if False:'), '<source-seal-falsifier>', 'exec'), namespace)
    monkeypatch.setattr(basis, 'historical_view', namespace['historical_view'])
    with pytest.raises(AssertionError):
        _every_unknown_neighbor_refuses()
