"""Source-only regression falsifiers; no canonical imports or transitions."""
import ast
from copy import deepcopy
import importlib.abc
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from p10_reentry_policy import CHANGES, VECTOR_CHANGES, source, transform, parent_module
from p10_reentry_job import command, old_inspector, expected_request

HERE = Path(__file__).resolve().parents[1]
# Explicitly noncanonical, inert syntax fixture. Never compiled or executed.
DTO_SOURCE = '''
class SyntheticNativeDTO:
    _schema = 'ramp-free-native/1'
    def descriptive_syntax(self):
        healthy = r20 > 0 and dam <= .63 and green >= .2
        entry = dd <= -.10 and dam >= .88
        if self.fast_age + 1 >= 10 and self.fast_h >= 3:
            fast = False
        if self.slow_age + 1 >= 20 and self.slow_h >= 6:
            slow = False
class SyntheticCandidateDTO:
    _schema = 'ramp-free-ex3-rebound-false/1'
    def descriptive_syntax(self):
        if self.full_streak >= LDRC_REC or concordant:
            reason = 'FULL_RISK_CERTIFIED_PERSISTENCE'
        if self.latched:
            desired = min(desired, .55)
'''


class NoCanonical(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('sentinel', 'stock_strategy_shared', 'research.pooled_vacancy', 'research.pooled_input')):
            raise AssertionError('LOCAL_CANONICAL_IMPORT_FORBIDDEN:' + fullname)


def test_complete_compiler_preserves_other_syntax():
    result = ast.parse(transform(DTO_SOURCE, CHANGES))
    before = ast.parse(DTO_SOURCE)
    for name in ('healthy', 'entry'):
        find = lambda tree: next(n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                                 and isinstance(n.targets[0], ast.Name) and n.targets[0].id == name)
        assert ast.dump(find(before)) == ast.dump(find(result))
    assert "'research-p10-health3-native/1'" in ast.unparse(result)
    assert 'desired = min(desired, 0.55)' in ast.unparse(result)


@pytest.mark.parametrize('index', range(len(CHANGES)))
def test_every_actual_change_site_has_a_missing_site_falsifier(index):
    old, _ = CHANGES[index]
    # Remove the exact required node from an inert syntax DTO; compilation refuses.
    modified = DTO_SOURCE.replace(old, 'False', 1)
    if modified == DTO_SOURCE:
        pytest.fail('falsifier did not change the source')
    with pytest.raises(ValueError, match='EXACT_SINGLE_AST_SITE'):
        transform(modified, CHANGES)


def test_duplicate_site_refuses():
    with pytest.raises(ValueError, match='EXACT_SINGLE_AST_SITE'):
        transform(DTO_SOURCE + '\nx = self.fast_age + 1 >= 10 and self.fast_h >= 3\n', CHANGES)


def test_unknown_original_source_refuses():
    with pytest.raises(ValueError, match='FROZEN_PARENT_BYTES'):
        source(DTO_SOURCE.encode(), True)


def test_canonical_compilation_is_closed_locally(monkeypatch):
    monkeypatch.setenv('FULL_SYSTEM_HOSTED', '1')
    with pytest.raises(ValueError, match='HOSTED_ONLY'):
        parent_module(DTO_SOURCE.encode(), {'id': 'P10_CORE_HEALTH_3'}, 'unused')


def test_independent_vector_exactly_three_recovery_sites():
    raw = (HERE / 'full_system_controller_vector.py').read_bytes()
    changed = transform(raw, VECTOR_CHANGES)
    assert 'release = old & ~new & (fh >= 3)' in changed
    assert 'release = old & (sh >= 3)' in changed
    assert 'clear = episode & (native >= 1)' in changed


@pytest.mark.parametrize('index', range(len(VECTOR_CHANGES)))
def test_independent_vector_site_removal_refuses(index):
    raw = ast.unparse(ast.parse((HERE / 'full_system_controller_vector.py').read_bytes()))
    before, _ = VECTOR_CHANGES[index]
    printed = ast.unparse(ast.parse(before, mode='eval').body)
    assert raw.count(printed) == 1
    with pytest.raises(ValueError, match='EXACT_SINGLE_AST_SITE'):
        transform(raw.replace(printed, 'False', 1), VECTOR_CHANGES)


@pytest.mark.parametrize('review', (False, True))
def test_actual_constructor_arguments_are_exact_without_launch(review, monkeypatch):
    import full_system_trials_job
    monkeypatch.setattr(full_system_trials_job, 'os',
                        SimpleNamespace(getuid=lambda: 1001, getgid=lambda: 1001))
    values = command('capital-full-core-b-' + ('review' if review else 'worker') + '-123-1',
                     Path('/source'), Path('/frozen'), Path('/output'), Path('/original'),
                     Path('/evidence') if review else None)
    assert values[values.index('--network') + 1] == 'none'
    assert values[values.index('--entrypoint') + 1] == 'python'
    assert '/driver/p10_reentry_worker.py' in values
    assert values[-2:] == ['--mode', 'review' if review else 'worker']
    assert values[values.index('--root') + 1] == '/core/book'
    assert values[values.index('--output') + 1] == ('/out/review' if review else '/out/book')


def test_existing_inspector_signature_canary_uses_noncanonical_dto():
    import inspect
    sig = inspect.signature(old_inspector())
    sig.bind('example', 'id', value=object(), run_id='123', user='1001:1001', correlation_prefix=False)
    for keyword in ('value', 'run_id', 'user', 'correlation_prefix'):
        assert keyword in sig.parameters


def test_data_import_probe_under_all_canonical_import_fences():
    finder = NoCanonical()
    sys.meta_path.insert(0, finder)
    try:
        from p10_reentry_job import probe
        request = HERE / 'p10-reentry-request.json'
        assert json.loads(request.read_bytes()) == expected_request()
        assert probe(request)['canonical_runtime_executed'] is False
    finally:
        sys.meta_path.remove(finder)
