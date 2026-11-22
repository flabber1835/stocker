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
    raw = economic_manifest.previous_source(module, raw)
    profile = basis._profile()
    if module != basis.MODULE or hashlib.sha256(raw).hexdigest() not in (
            profile['after'], profile['entitlements_after'], profile['settlement_after'],
            profile['recovery_after'], profile['replay_after'], profile['opening_after']):
        return raw
    prior = PREVIOUS.read_bytes()
    assert hashlib.sha256(prior).hexdigest() == basis.BEFORE
    return prior


def opening_predecessor(raw):
    """Reverse only the reviewed November 17 reconciliation result and refusal edits."""
    profile = basis._profile()
    assert hashlib.sha256(raw).hexdigest() == profile['opening_after']
    changes = (
        (b'    native_fill_integrity_refused: bool = False\n', b''),
        (b"            **({'native_fill_integrity_refused': True}\n"
         b'               if self.native_fill_integrity_refused else {}),\n', b''),
        (b'                detail=f"native fill evidence refused: {exc}",\n'
         b'                native_fill_integrity_refused=True)\n',
         b'                detail=f"native fill evidence refused: {exc}")\n'),
        (b'        raw_native_refusal = (\n'
         b'            isinstance(exc, (alpaca_adapter.MalformedBrokerPayload,\n'
         b'                             alpaca_adapter.ActivityCorrectionRequiresRecovery))\n'
         b'            and exc.raw_event is not None)\n'
         b'        native_fill_integrity_refused = (\n'
         b'            raw_native_refusal\n'
         b'            or isinstance(exc, fill_integrity.NativeFillIdentityRefused))\n'
         b'        if raw_native_refusal:\n',
         b'        if (isinstance(exc, (alpaca_adapter.MalformedBrokerPayload,\n'
         b'                             alpaca_adapter.ActivityCorrectionRequiresRecovery))\n'
         b'                and exc.raw_event is not None):\n'),
        (b'            detail=str(exc),\n'
         b'            native_fill_integrity_refused=native_fill_integrity_refused)\n',
         b'            detail=str(exc))\n'),
    )
    for current, previous in changes:
        assert raw.count(current) == 1
        raw = raw.replace(current, previous)
    assert hashlib.sha256(raw).hexdigest() == profile['replay_after']
    return raw


def test_opening_source_witness_reconstructs_installed_reconcile_exactly():
    current = economic_manifest.previous_source(basis.MODULE, Path(reconcile.__file__).read_bytes())
    prior = opening_predecessor(current)
    before, after = ast.parse(prior), ast.parse(current)
    assert len(before.body) == len(after.body)
    changed = set()
    for left, right in zip(before.body, after.body):
        if ast.dump(left) != ast.dump(right):
            assert getattr(left, 'name', None) == getattr(right, 'name', None)
            changed.add(left.name)
        else:
            assert ast.get_source_segment(prior.decode(), left) == ast.get_source_segment(current.decode(), right)
    assert changed == {'ReconciliationResult', 'reconcile'}
    assert economic_manifest.local_imports(prior, module_name=basis.MODULE) == (
        economic_manifest.local_imports(current, module_name=basis.MODULE))
    assert basis.contribution(basis.MODULE, current) == basis.BEFORE


def test_checkpoint_read_source_reconstructs_both_reviewed_predecessors():
    raw = Path(reconcile.__file__).read_bytes()
    profile = economic_manifest._retired_source_profile()
    delta = profile['reverse'][basis.MODULE]
    retired = economic_manifest._reverse_source_edit(basis.MODULE, raw, delta['successor'])
    assert hashlib.sha256(retired).hexdigest() == (
        'a8dbb42e34b00bbbdfb409b40a928df496807eaeaf95e6252ca6c9d9928ea364')
    before, after = ast.parse(retired), ast.parse(raw)
    assert len(before.body) == len(after.body)
    assert [left.name for left, right in zip(before.body, after.body)
            if ast.dump(left) != ast.dump(right)] == ['reconcile']
    assert economic_manifest.local_imports(retired, module_name=basis.MODULE) == (
        economic_manifest.local_imports(raw, module_name=basis.MODULE))
    prior = economic_manifest.previous_source(basis.MODULE, raw, profile)
    assert prior == economic_manifest.previous_source(basis.MODULE, retired, profile)
    assert hashlib.sha256(prior).hexdigest() == basis._profile()['opening_after']

    neighbor = raw + b'\n# unreviewed change\n'
    assert economic_manifest.previous_source(basis.MODULE, neighbor, profile) == neighbor
    delta['successor']['before'] = '0' * 64
    with pytest.raises(economic_manifest.EconomicManifestRefused, match='ECONOMIC_PREDECESSOR_CHANGED'):
        economic_manifest.previous_source(basis.MODULE, neighbor, profile)


def test_only_execution_definitions_change_and_action_input_bytes_stay_exact():
    current = economic_manifest.previous_source(basis.MODULE, Path(reconcile.__file__).read_bytes())
    prior = qualified_predecessor(basis.MODULE, current)
    assert prior != current
    before, after = ast.parse(prior), ast.parse(current)
    assert len(before.body) == len(after.body)
    allowed = {'ReconciliationResult', '_order_command_conflict', '_order_observation_fingerprint',
               '_position_identity_conflicts', 'expected_book_from_commands', 'reconcile'}
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
        with pytest.raises(AssertionError):
            opening_predecessor(changed)
    assert basis.contribution('sentinel.unreviewed', current) == hashlib.sha256(current).hexdigest()


def test_account_plan_comparison_keeps_every_canonical_definition_and_unknown_byte():
    from sentinel.core import decision
    raw = economic_manifest.previous_source("sentinel.core.decision", Path(decision.__file__).read_bytes())
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
    from sentinel.runtime_admission import _decision_comparison_scope
    comparison, prior = _decision_comparison_scope(scope, raw)
    assert comparison is not scope and scope.current_files == actual
    assert comparison.current_files["core/decision.py"] == hashlib.sha256(prior).hexdigest()
    edited = raw+b'\n# unknown\n'
    assert _decision_comparison_scope(scope, edited) == (scope, edited)
    edited_files = {"core/decision.py": hashlib.sha256(edited).hexdigest()}
    edited_scope = ScopeProof({}, {}, edited_files, "edited-closure")
    assert _decision_comparison_scope(edited_scope, edited) == (edited_scope, edited)
    assert hashlib.sha256(prior).hexdigest() == basis._profile()["decision"]["before"]


def test_decision_predecessor_guard_falsifier(monkeypatch):
    from sentinel.core import decision
    prior = basis.decision_predecessor(economic_manifest.previous_source(
        "sentinel.core.decision", Path(decision.__file__).read_bytes()))
    monkeypatch.setattr(basis, "decision_predecessor", lambda raw: prior)
    with pytest.raises(AssertionError):
        test_account_plan_comparison_keeps_every_canonical_definition_and_unknown_byte()


def test_exact_source_guard_falsifier(monkeypatch):
    raw = textwrap.dedent(inspect.getsource(basis.contribution))
    assert raw.count('actual in after') == 1
    scope = {}
    exec(raw.replace('actual in after', 'True'), vars(basis), scope)
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
    installed = profile['retained_predecessors'][runtime_basis.NOV13_INSTALLED_REVISION]['files']
    assert runtime_basis.predecessor_view(actual, previous=installed) == installed
    assert set(installed) - set(prior) == {'execution/opening_display.py'}
    fractional_release = profile['retained_predecessors'][runtime_basis.ORDER_AMOUNT_INSTALL_PREDECESSOR]['files']
    assert runtime_admission.source_closure(fractional_release) == (
        '53e73eacb67b9c0ae18a264b8b4e3ce2b1b52e2d6ad210e5f736b1cf4a153a10')
    assert runtime_basis.predecessor_view(actual, previous=fractional_release) == fractional_release
    assert set(fractional_release) - set(installed) == {
        'execution/order_amount.py', 'execution/fractional_sizing.py',
        'execution/fractional_progress.py', 'execution/fractional_orders.py',
        'fractional_execution_source_basis.py',
        'paper/policy_replacement.py',
    }
    edited = {**actual, 'execution/fractional_progress.py': 'f' * 64}
    assert runtime_basis.predecessor_view(edited, previous=prior) is edited
    installed_fractional = profile['retained_predecessors'][runtime_basis.FRACTIONAL_INSTALLED_REVISION]['files']
    assert runtime_admission.source_closure(installed_fractional) == (
        'da2df8d1d087682342464e8a9f2c5553fcd987c37d99c889c8e5506ef2d14eee')
    assert installed_fractional['execution/reconcile.py'] == basis._profile()['after']
    assert runtime_basis.predecessor_view(actual, previous=installed_fractional) == installed_fractional
    assert runtime_basis.predecessor_view(edited, previous=installed_fractional) is edited
    local_patch = profile["retained_predecessors"][runtime_basis.FRACTIONAL_LOCAL_PREDECESSOR]["files"]
    assert local_patch["execution/reconcile.py"] == basis._profile()["entitlements_after"]
    assert runtime_basis.predecessor_view(actual, previous=local_patch) == local_patch
    assert runtime_basis.predecessor_view(edited, previous=local_patch) is edited
    settlement = profile["retained_predecessors"][runtime_basis.FRACTIONAL_SETTLEMENT_PREDECESSOR]["files"]
    assert settlement["execution/reconcile.py"] == basis._profile()["settlement_after"]
    assert runtime_basis.predecessor_view(actual, previous=settlement) == settlement
    assert runtime_basis.predecessor_view(edited, previous=settlement) is edited
    recovery = profile["retained_predecessors"][runtime_basis.FRACTIONAL_RECOVERY_PREDECESSOR]["files"]
    assert recovery["execution/reconcile.py"] == basis._profile()["recovery_after"]
    raw = Path(reconcile.__file__).read_bytes()
    assert actual["execution/reconcile.py"] == hashlib.sha256(raw).hexdigest()
    predecessor = economic_manifest.previous_source(basis.MODULE, raw)
    assert hashlib.sha256(predecessor).hexdigest() == basis._profile()["opening_after"]
    assert runtime_basis.predecessor_view(actual, previous=recovery) == recovery
    assert runtime_basis.predecessor_view(edited, previous=recovery) is edited
