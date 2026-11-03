"""Direct pure/stub tests; canonical component execution is hosted only."""
import ast
from copy import deepcopy
from fractions import Fraction
import gzip
import importlib.util
import json
import math
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

HERE = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('factual_component_tested', HERE / 'p01_factual_batch_component.py')
component = importlib.util.module_from_spec(spec)
spec.loader.exec_module(component)


@pytest.mark.parametrize('ratio,current,initial,whole,each', [
    ('0.8000', [5, 10], [5, 10], 12, [4., 8.]),
    ('0.55', [10, 10], [20, 20], 11, [5.5, 5.5]),
    ('1.3125', [8, 8], [16, 16], 21, [10.5, 10.5]),
    ('0.5165', [1000, 1000], [2000, 2000], 1033, [516.5, 516.5]),
])
def test_four_exact_holder_and_episode_representations(ratio, current, initial, whole, each):
    result = component.exact_representation(current, initial, ratio)
    assert result['holder_delivered_shares'] == whole
    assert [x['delivered'] for x in result['episodes']] == each
    assert sum(Fraction.from_float(x) for x in each) == whole


@pytest.mark.parametrize('current,initial,ratio,reason', [
    ([1, 1], [20, 20], '0.55', 'AGGREGATE_REQUIRES_CIL'),
    ([1, 4], [5, 5], '0.8', 'INEXACT_CANONICAL_EPISODE'),
    ([10, 10], [10, 10], '0.55', 'INITIAL_REFERENCE_ROUNDING'),
    ([2**53 + 1], [2**53 + 1], '1', 'AGGREGATE_REQUIRES_CIL'),
])
def test_aggregate_fraction_binary_allocation_and_initial_rounding_are_distinct_refusals(current, initial, ratio, reason):
    with pytest.raises(ValueError, match=reason):
        component.exact_representation(current, initial, ratio)


def test_import_has_no_top_level_canonical_dependencies():
    tree = ast.parse((HERE / 'p01_factual_batch_component.py').read_bytes())
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or '').startswith(('sentinel', 'stock_strategy_shared', 'research.pooled'))
        if isinstance(node, ast.Import):
            assert all(not x.name.startswith(('sentinel', 'stock_strategy_shared', 'research.pooled')) for x in node.names)


def test_hosted_fence_runs_before_any_canonical_import(monkeypatch, tmp_path):
    fake = ModuleType('full_system_core')
    def denied():
        raise ValueError('ACTUAL_HOSTED_FENCE_REFUSES_LOCAL')
    fake.hosted = denied
    monkeypatch.setitem(sys.modules, 'full_system_core', fake)
    with pytest.raises(ValueError, match='ACTUAL_HOSTED_FENCE_REFUSES_LOCAL'):
        component.qualify_components(None, None, tmp_path)


def test_source_prefix_compiler_is_bounded_without_executing_canonical_body():
    source = (Path.cwd() / 'shared/stock_strategy_shared/wealth_core/adapter.py').read_bytes()
    function = component.action_prefix(source, {'PortfolioState': object, 'Ledger': object,
        'PendingOrder': object, 'WealthCoreConfig': object, 'Sequence': list, 'DailyBar': object,
        'SecurityBar': object, 'Mapping': dict, 'SessionResult': object})
    # Compiling a function does not execute it or import its canonical body dependencies.
    assert function.__name__ == '_qualified_component_action_prefix'
    names = function.__code__.co_names
    assert '_resolved_open_equity' in names and '_transform_pending_for_terminal' in names
    assert not {'apply_entry', 'apply_exit', 'decide'} & set(names)


def test_source_pending_transform_compiler_has_exact_site_without_execution():
    source = (Path.cwd() / 'shared/stock_strategy_shared/wealth_core/adapter.py').read_bytes()
    mutated = component.target_identity_mutation(source, {'PortfolioState': object, 'PendingOrder': object})
    assert 'delivered_security_id' in mutated.__code__.co_names


def test_mutation_falsifier_changes_only_disposable_stub_namespace():
    source = '''
def _transform_pending_for_terminal(state, pending, *, terms, result, session):
    keep=[]
    for po in pending:
        if po.security_id != terms.security_id:
            keep.append(po)
            continue
    return keep
'''
    original_ns = {}
    exec(source, original_ns)
    original = original_ns['_transform_pending_for_terminal']
    mutated = component.target_identity_mutation(source, original_ns)
    order = SimpleNamespace(security_id='TARGET')
    terms = SimpleNamespace(security_id='SOURCE', delivered_security_id='TARGET')
    assert original(None, [order], terms=terms, result={}, session='STUB') == [order]
    assert mutated(None, [order], terms=terms, result={}, session='STUB') == []
    assert original_ns['_transform_pending_for_terminal'] is original


def test_complete_state_comparison_detects_pending_or_reservation_change():
    original = {'pending': [{'security_id': 'TARGET', 'intended_dollars': 500.}],
                'wealth_core': {'slots': {'0': {'reserved_for': 'TARGET'}}}, 'ledger': {'events': []}}
    component.same_state(deepcopy(original), original, 'STUB')
    changed = deepcopy(original)
    changed['wealth_core']['slots']['0']['reserved_for'] = None
    with pytest.raises(ValueError, match='ENTIRE_SESSIONSTATE_AND_LEDGER'):
        component.same_state(changed, original, 'STUB')


def test_progress_is_one_durable_cumulative_proof_with_prior_cases(tmp_path):
    value = dict(status='STARTED', target_cases={})
    path = component.write_progress(tmp_path, value)
    value['target_cases']['FIRST'] = dict(passed=True)
    component.write_progress(tmp_path, value)
    value['status'] = 'PARTIAL_REFUSAL'
    component.write_progress(tmp_path, value)
    assert json.loads(gzip.decompress(path.read_bytes())) == value
    assert sorted(x.name for x in tmp_path.iterdir()) == ['target-independence-component.json.gz']


def test_failed_progress_replace_preserves_previous_proof(tmp_path, monkeypatch):
    path = component.write_progress(tmp_path, {'status': 'FIRST_CASE_COMPLETE'})
    prior = path.read_bytes()
    def fail(*args):
        raise OSError('SYNTHETIC_REPLACE_FAILURE')
    monkeypatch.setattr(component.os, 'replace', fail)
    with pytest.raises(OSError, match='SYNTHETIC_REPLACE_FAILURE'):
        component.write_progress(tmp_path, {'status': 'SECOND_CASE_INFLIGHT'})
    assert path.read_bytes() == prior
    assert (tmp_path / 'target-independence-component.inflight').exists()


def guard_functions():
    raw = (HERE / 'p01_factual_batch_guard.py').read_bytes()
    nodes = [n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name in ('roles', 'require_scope')]
    ns = dict(deepcopy=deepcopy, Fraction=Fraction, math=math, need=component.need)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<pure-outside-driver-role-guards>', 'exec'), ns)
    return raw, ns


def role_stub(current, initial, *, pending=None, exiting=False):
    return SimpleNamespace(wealth_core={'episodes': {str(i): dict(security_id='SOURCE', current_shares=q,
        initial_shares=original, exit_pending=exiting) for i, (q, original) in enumerate(zip(current, initial))}},
        pending=[] if pending is None else pending, median5={'selected': []})


def test_actual_allocation_guard_removal_falsifier_on_pure_driver_stub():
    raw, ns = guard_functions()
    bad = role_stub([1, 4], [5, 5])
    action = dict(source_security_id='SOURCE', exchange_ratio='0.8', clock_scope='KNOWN_COMPLETION_BEFORE_OPEN')
    with pytest.raises(ValueError, match='UNSUPPORTED_INEXACT_CANONICAL_EPISODE_ALLOCATION'):
        ns['require_scope'](bad, action)
    broken = component.removed_scope_guard(raw, ns)
    assert broken(bad, action)['episodes'] == bad.wealth_core['episodes']


@pytest.mark.parametrize('pending,exiting,reason', [
    ([{'security_id': 'SOURCE', 'intended_dollars': 500.}], False, 'SOURCE_PENDING_INTENT'),
    ([], True, 'SOURCE_EPISODE_EXIT_FLAG'),
])
def test_actual_source_intents_and_exit_flags_refuse_before_mutation(pending, exiting, reason):
    raw, ns = guard_functions()
    state = role_stub([5], [5], pending=pending, exiting=exiting)
    before = deepcopy(state.__dict__)
    with pytest.raises(ValueError, match=reason):
        ns['require_scope'](state, dict(source_security_id='SOURCE', exchange_ratio='0.8', clock_scope='KNOWN_COMPLETION_BEFORE_OPEN'))
    assert state.__dict__ == before


def test_existing_target_roles_do_not_trigger_source_pending_guard():
    raw, ns = guard_functions()
    state = role_stub([], [], pending=[{'security_id': 'TARGET', 'intended_dollars': 500.}])
    assert ns['require_scope'](state, dict(source_security_id='SOURCE', exchange_ratio='0.8',
                                        clock_scope='KNOWN_COMPLETION_BEFORE_OPEN'))['pending'] == state.pending


def test_configuration_uses_exact_parent_funding_policy_and_configured_slots():
    policy = 'EXPLICIT_RESEARCH_POLICY_STUB'
    binding = SimpleNamespace(parent={'base': {'policy': policy}})
    calls = []
    def factory(selected):
        calls.append(selected)
        return SimpleNamespace(economic_profile=selected, n_slots=30)
    value = component.configuration(binding, factory)
    assert calls == [policy] and value.n_slots == 30


def test_default_profile_cannot_substitute_for_parent_research_configuration():
    binding = SimpleNamespace(parent={'base': {'policy': 'EXPLICIT_RESEARCH_POLICY_STUB'}})
    with pytest.raises(ValueError, match='EXACT_PARENT_FUNDING_POLICY_CONFIGURATION'):
        component.configuration(binding, lambda selected: SimpleNamespace(economic_profile='DEFAULT_V5', n_slots=20))
