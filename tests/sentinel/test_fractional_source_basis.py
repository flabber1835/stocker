"""The canonical action compiler stays exact; broker fulfillment changes."""
import ast
import hashlib
import inspect
from pathlib import Path
import textwrap

import pytest

from sentinel import fractional_execution_source_basis as basis, economic_manifest
from sentinel.execution import reconcile

PREVIOUS = Path(__file__).parents[1] / 'support/fractional-reconcile-aed1.py.txt'


def qualified_predecessor(module, raw):
    if module != basis.MODULE or hashlib.sha256(raw).hexdigest() != basis._profile()['after']:
        return raw
    prior = PREVIOUS.read_bytes()
    assert hashlib.sha256(prior).hexdigest() == basis.BEFORE
    return prior


def test_only_the_four_execution_functions_change_and_action_input_bytes_stay_exact():
    current = Path(reconcile.__file__).read_bytes()
    prior = qualified_predecessor(basis.MODULE, current)
    assert prior != current
    before, after = ast.parse(prior), ast.parse(current)
    assert len(before.body) == len(after.body)
    allowed = {'_order_command_conflict', '_order_observation_fingerprint',
               'expected_book_from_commands', 'reconcile'}
    changed = set()
    for left, right in zip(before.body, after.body):
        if ast.dump(left) != ast.dump(right):
            assert getattr(left, 'name', None) == getattr(right, 'name', None)
            changed.add(left.name)
        else:
            assert ast.get_source_segment(prior.decode(), left) == ast.get_source_segment(current.decode(), right)
    assert changed == allowed
    assert economic_manifest.local_imports(prior, module_name=basis.MODULE) == economic_manifest.local_imports(current, module_name=basis.MODULE)
    assert basis.contribution(basis.MODULE, current) == basis.BEFORE


def test_unknown_execution_or_action_source_never_inherits_qualified_identity():
    current = Path(reconcile.__file__).read_bytes()
    for changed in (current+b'\n# unknown neighboring change\n',
                    current.replace(b'if effective <= start or effective > end:',
                                    b'if effective < start or effective > end:')):
        assert changed != current
        assert basis.contribution(basis.MODULE, changed) == hashlib.sha256(changed).hexdigest()
    assert basis.contribution('sentinel.unreviewed', current) == hashlib.sha256(current).hexdigest()


def test_account_plan_comparison_keeps_every_canonical_definition_and_unknown_byte():
    from sentinel.core import decision
    raw = Path(decision.__file__).read_bytes()
    prior = basis.decision_predecessor(raw)
    assert prior != raw and hashlib.sha256(prior).hexdigest() == basis._profile()["decision"]["before"]
    before, after = ast.parse(prior), ast.parse(raw)
    assert len(before.body) == len(after.body)
    changed = [getattr(right, "name", None) for left, right in zip(before.body, after.body)
               if ast.dump(left) != ast.dump(right)]
    assert changed == ["build_execution_plan"]
    for edited in (raw+b'\n# unknown\n', raw.replace(b'if negative:', b'if False:')):
        assert edited != raw and basis.decision_predecessor(edited) == edited


def test_account_plan_comparison_preserves_actual_scope_and_hash_guards():
    from sentinel.core import decision
    from sentinel.backed_paper_source import ScopeProof
    raw = Path(decision.__file__).read_bytes()
    actual = {"core/decision.py": hashlib.sha256(raw).hexdigest()}
    scope = ScopeProof({}, {}, actual, "actual-closure")
    comparison, prior = basis.decision_comparison_scope(scope, raw)
    assert comparison is not scope and scope.current_files == actual
    assert comparison.current_files["core/decision.py"] == hashlib.sha256(prior).hexdigest()
    edited = raw+b'\n# unknown\n'
    assert basis.decision_comparison_scope(scope, edited) == (scope, edited)


def test_decision_predecessor_guard_falsifier(monkeypatch):
    from sentinel.core import decision
    prior = basis.decision_predecessor(Path(decision.__file__).read_bytes())
    monkeypatch.setattr(basis, "decision_predecessor", lambda raw: prior)
    with pytest.raises(AssertionError):
        test_account_plan_comparison_keeps_every_canonical_definition_and_unknown_byte()


def test_exact_source_guard_falsifier(monkeypatch):
    raw = textwrap.dedent(inspect.getsource(basis.contribution))
    assert raw.count('actual == value["after"]') == 1
    scope = {}
    exec(raw.replace('actual == value["after"]', 'True'), vars(basis), scope)
    monkeypatch.setattr(basis, 'contribution', scope['contribution'])
    with pytest.raises(AssertionError):
        test_unknown_execution_or_action_source_never_inherits_qualified_identity()


def test_complete_runtime_transition_keeps_exact_pre_fractional_executable():
    from sentinel import url_selected_source_basis as runtime_basis, runtime_admission
    profile = runtime_basis._profile()
    prior = profile['retained_predecessors'][basis.BASE_REVISION]['files']
    assert len(prior) == 476
    assert runtime_admission.source_closure(prior) == 'a765d57aaee204f0e5b734fd6d34ef8092ce4c4c4d0ca29b7f9fdf9b158551d2'
    assert profile['authority_effect'] == 'NONE'
    actual = runtime_admission._source_files(runtime_basis.PROFILE.parent)
    assert runtime_basis.predecessor_view(actual, previous=prior) == prior
    assert set(actual) - set(prior) == {
        'execution/order_amount.py', 'execution/fractional_sizing.py',
        'execution/fractional_progress.py', 'execution/fractional_orders.py',
        'fractional_execution_source_basis.py',
    }
    edited = {**actual, 'execution/fractional_progress.py': 'f' * 64}
    assert runtime_basis.predecessor_view(edited, previous=prior) is edited
