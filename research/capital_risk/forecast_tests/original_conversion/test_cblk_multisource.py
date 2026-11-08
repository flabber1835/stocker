"""Portable multi-source cash selection tests using source/input facts only."""
import ast
from copy import deepcopy
from datetime import date
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Annotated, Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field

P = Path(__file__).resolve().parent
C = P.parents[1]
SOURCE = C / 'system_campaign_financial_future.py'
CATALOG = C / 'system-campaign-selected-own-cash-terminal-facts.json'
FIXTURE = P / 'cblk-three-source-facts.json'


class Fence:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('stock_strategy_shared', 'sentinel', 'research.pooled_', 'numpy', 'pandas')):
            raise ImportError('CASH_SOURCE_DATA_ONLY:' + fullname)


@pytest.fixture(scope='module', autouse=True)
def fence_financial_imports():
    fence = Fence()
    sys.meta_path.insert(0, fence)
    try:
        yield
    finally:
        sys.meta_path.remove(fence)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())


def need(value, label):
    if not value:
        raise ValueError(label)


def facts():
    return json.loads(FIXTURE.read_bytes())


def chosen():
    return deepcopy(next(t for t in json.loads(CATALOG.read_bytes())['terms']
                         if (t['arm'], t['parent_cursor']) == ('P03', '2019-09-30')))


def constructor(name, class_name):
    # Execute the unchanged original factual constructor only, never hydrate/overlay.
    raw = (C / (name + '.py')).read_bytes()
    node = deepcopy(next(n for n in ast.parse(raw).body if isinstance(n, ast.ClassDef) and n.name == class_name))
    node.body = [n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == '__init__']
    env = dict(Path=Path, __file__=str(C / (name + '.py')), json=json, need=need, sha=sha)
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<original-factual-constructor-only>', 'exec'), env)
    return env[class_name]


def functions():
    return {n.name: n for n in ast.parse(SOURCE.read_bytes()).body if isinstance(n, ast.FunctionDef)}


def logic():
    tree = ast.parse(SOURCE.read_bytes())
    env = dict(Path=Path, __file__=str(C / 'system_campaign_financial_future.py'), need=need,
               sha=sha, digest=digest, json=json, deepcopy=deepcopy, SimpleNamespace=SimpleNamespace,
               math=math, Fraction=Fraction, date=date, Annotated=Annotated, Literal=Literal,
               BaseModel=BaseModel, ConfigDict=ConfigDict, Field=Field)
    # Metadata is source-only; include original normalization loops as well as assignments.
    nodes = [n for n in tree.body if isinstance(n, (ast.Assign, ast.For))
             or isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)]
    exec(compile(ast.Module(body=deepcopy(nodes), type_ignores=[]), '<source-catalog-metadata-only>', 'exec'), env)
    env['HERE'] = C
    names = {'ResearchCashAssumption', 'research_cash_term', 'completion_session', 'catalog_terms',
             'supplemental_selection', 'merge_selected_terms', 'remaining_ordinary_terms'}
    nodes = [n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name in names]
    exec(compile(ast.Module(body=deepcopy(nodes), type_ignores=[]), '<cash-source-and-input-predicates-only>', 'exec'), env)
    return env


def scoped_binding(env):
    """Extract the exact selector branch and its original capture/parent guard."""
    fn = functions()['own_cash_selection']
    loop = next(n for n in fn.body if isinstance(n, ast.For)
                and isinstance(n.target, ast.Name) and n.target.id == 'term')
    branch = next(n for n in loop.body if isinstance(n, ast.If)
                  and "len(scope['terms'])" in ast.unparse(n.test))
    guard = next(n for n in loop.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                 and any(isinstance(v, ast.Constant) and v.value == 'OWN_CASH_EXACT_CLOSED_SOURCE_CAPTURE_AND_PARENT_SCOPE'
                         for v in n.value.args))
    initial = ast.parse("phase = term['arm'], term['parent_cursor']\nsource = term['source_capture']\n").body
    node = ast.FunctionDef(name='binding', args=ast.arguments(posonlyargs=[],
        args=[ast.arg(arg=x) for x in ('term', 'scope', 'parent')], kwonlyargs=[], kw_defaults=[], defaults=[]),
        body=initial + [deepcopy(branch), deepcopy(guard), ast.Return(ast.Name(id='declared', ctx=ast.Load()))],
        decorator_list=[], returns=None, type_comment=None)
    ns = dict(env)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), '<exact-own-cash-source-binding>', 'exec'), ns)
    return ns, node


def remove_guard(env, node, label):
    class Remove(ast.NodeTransformer):
        count = 0
        def visit_Expr(self, n):
            if isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name) and n.value.func.id == 'need' and any(
                    isinstance(a, ast.Constant) and a.value == label for a in n.value.args):
                self.count += 1
                return ast.Pass()
            return self.generic_visit(n)
    remove = Remove()
    changed = remove.visit(deepcopy(node))
    assert remove.count == 1
    ns = dict(env)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[changed], type_ignores=[])), '<removed-source-input-guard>', 'exec'), ns)
    return ns[node.name]


@pytest.fixture
def ns(monkeypatch):
    env = logic()
    modules = {}
    for name, cls in [('system_campaign_medicines_facts', 'MedicinesFacts'), ('system_campaign_arqule_facts', 'ArQuleFacts')]:
        modules[name] = SimpleNamespace(**{cls: constructor(name, cls), '__file__': str(C / (name + '.py'))})
    import importlib
    original = importlib.import_module
    monkeypatch.setattr(importlib, 'import_module', lambda name: modules[name] if name in modules else original(name))
    return env


def test_exact_chosen_member_preserves_all_three_authenticated_scope_terms(ns):
    term, value = chosen(), facts()
    scope = value['scope']
    before = deepcopy(scope)
    env, _ = scoped_binding(ns)
    selected = env['binding'](term, scope, dict(outer_sha256=scope['parent_outer_sha256'], selected_session=scope['parent_cursor']))
    assert selected['security_id'] == term['security_id'] == '325066623134917949'
    assert scope == before and len(scope['terms']) == 3
    assert digest(scope) == term['source_capture']['scope_sha256']
    assert term['parent_positions'] == []  # Current own439 role only, no future-holding assumption.


def test_single_member_branch_preserves_existing_selection(ns):
    term = chosen()
    scope = facts()['scope']
    scope['terms'] = [scope['terms'][0]]
    term['source_capture']['scope_sha256'] = digest(scope)
    env, _ = scoped_binding(ns)
    assert env['binding'](term, scope, dict(outer_sha256=scope['parent_outer_sha256'], selected_session=scope['parent_cursor'])) == scope['terms'][0]


def test_duplicate_unselected_scope_member_needs_the_new_unique_guard(ns):
    term = chosen()
    scope = facts()['scope']
    scope['terms'].append(deepcopy(scope['terms'][1]))
    term['source_capture']['scope_sha256'] = digest(scope)
    env, node = scoped_binding(ns)
    parent = dict(outer_sha256=scope['parent_outer_sha256'], selected_session=scope['parent_cursor'])
    label = 'OWN_CASH_UNIQUE_MULTI_SOURCE_SECURITY_AND_NATIVE_KEYS'
    with pytest.raises(ValueError, match=label):
        env['binding'](term, scope, parent)
    assert remove_guard(env, node, label)(term, scope, parent)['security_id'] == term['security_id']


def test_missing_chosen_member_refuses_at_exact_membership_guard(ns):
    term = chosen()
    scope = facts()['scope']
    scope['terms'] = scope['terms'][1:]
    term['source_capture']['scope_sha256'] = digest(scope)
    env, _ = scoped_binding(ns)
    with pytest.raises(ValueError, match='EXACT_SELECTED_MEMBER_OF_MULTI_SOURCE_SCOPE'):
        env['binding'](term, scope, dict(outer_sha256=scope['parent_outer_sha256'], selected_session=scope['parent_cursor']))


@pytest.mark.parametrize('change', ['positions', 'native', 'identity', 'clock', 'review', 'parent'])
def test_existing_scope_capture_guards_remain_meaningful(ns, change):
    term = chosen()
    scope = facts()['scope']
    parent = dict(outer_sha256=scope['parent_outer_sha256'], selected_session=scope['parent_cursor'])
    if change == 'positions':
        term['parent_positions'] = [dict(slot_id=1, ticker='CBLK', quantity=1, entry_date='2019-09-01')]
    elif change == 'native':
        term['native_term_sha256'] = '0' * 64
    elif change == 'identity':
        term['identity_witness']['session'] = '2019-10-03'
    elif change == 'clock':
        term['source_capture']['artifact_id'] += 1
    elif change == 'review':
        term['source_capture']['independent_data_review_sha256'] = ''
    else:
        parent['outer_sha256'] = '0' * 64
    env, node = scoped_binding(ns)
    label = 'OWN_CASH_EXACT_CLOSED_SOURCE_CAPTURE_AND_PARENT_SCOPE'
    with pytest.raises(ValueError, match=label):
        env['binding'](term, scope, parent)
    assert remove_guard(env, node, label)(term, scope, parent)['security_id'] == chosen()['security_id']


def test_CBLK_uses_existing_cash_model_and_exact_frozen_daily_axis(ns):
    term = chosen()
    assert ns['research_cash_term'](term) is None
    assert ns['completion_session'](term, facts()['axis_sessions']) is None
    assert term['added']['cash_per_share'] == 26.0
    assert term['preopen_completion_confirmed'] is False
    assert term['research_assumption']['opening_availability_assumed'] is True
    assert term['research_assumption']['actual_settlement_claimed'] is False


def test_cash_model_guard_removal_would_accept_wrong_published_cash(ns):
    term = chosen()
    term['added']['cash_per_share'] = 25.0
    node = functions()['research_cash_term']
    label = 'OWN_INPUT_EXPLICIT_RESEARCH_CASH_AMOUNT_AND_DAILY_RECOGNITION'
    with pytest.raises(ValueError, match=label):
        ns['research_cash_term'](term)
    assert remove_guard(ns, node, label)(term) is None


def test_calendar_guard_removal_would_accept_a_missing_recognition_day(ns):
    term = chosen()
    dates = [d for d in facts()['axis_sessions'] if d != '2019-10-08']
    node = functions()['completion_session']
    label = 'OWN_INPUT_RESEARCH_EXACT_NEXT_FROZEN_DAILY_BOUNDARY'
    with pytest.raises(ValueError, match=label):
        ns['completion_session'](term, dates)
    assert remove_guard(ns, node, label)(term, dates) is None


@pytest.mark.parametrize('change', ['preopen', 'settlement', 'availability'])
def test_research_disclosures_cannot_be_upgraded(ns, change):
    term = chosen()
    if change == 'preopen':
        term['preopen_completion_confirmed'] = True
    elif change == 'settlement':
        term['research_assumption']['actual_settlement_claimed'] = True
    else:
        term['research_assumption']['opening_availability_assumed'] = False
    with pytest.raises(ValueError):
        ns['research_cash_term'](term)


def test_actual_original_MDCO_ARQL_constructors_compose_all_three(ns):
    primary = [chosen()]
    extra, sources = ns['supplemental_selection']('P03', '2019-09-30')
    terms = ns['merge_selected_terms'](primary, extra)
    assert [t['ticker'] for t in terms] == ['CBLK', 'MDCO', 'ARQL']
    assert [t['added']['cash_per_share'] for t in terms] == [26., 85., 20.]
    assert min(t['native_session'] for t in terms) == '2019-10-07'
    assert sum(len({t['native_session'], t['added']['session']}) for t in terms) == 6
    assert [s['selected_tickers'] for s in sources] == [['MDCO'], ['ARQL']]
    rows = {(r['source_row']['session'], r['source_row']['security_id']): r['source_row'] for r in facts()['source_rows']}
    for term in terms:
        witness = term['identity_witness']
        assert digest(rows[witness['session'], witness['security_id']]) == witness['source_observation_sha256']
    for source in sources:
        assert sha((C / source['catalog_file']).read_bytes()) == source['catalog_sha256']
        assert sha((C / source['validator_file']).read_bytes()) == source['validator_sha256']


def test_unrelated_future_input_is_preserved_byte_for_byte(ns, tmp_path):
    old = facts()['unrelated_forward_input']  # Tiny synthetic input, never a financial checkpoint.
    raw = (json.dumps(old, indent=2, sort_keys=True) + '\n').encode()
    hashed = sha(raw)
    folder = tmp_path / 'book/repairs'
    folder.mkdir(parents=True)
    path = folder / (hashed + '.json')
    path.write_bytes(raw)
    cp = dict(source_cursor='2019-09-30', repairs=[dict(filename=path.name, sha256=hashed,
              predecessor_checkpoint_sha256=old['predecessor_checkpoint_sha256'])])
    extra = ns['supplemental_selection']('P03', '2019-09-30')[0]
    primary = [chosen()]
    expected = ns['merge_selected_terms'](primary, extra)
    before = deepcopy(cp)
    remaining, inherited = ns['remaining_ordinary_terms'](cp, expected, tmp_path)
    assert remaining == expected and inherited == [] and cp == before and path.read_bytes() == raw
    assert old['add'][0]['security_id'] not in {t['security_id'] for t in remaining}


def test_supplemental_catalog_and_validator_pins_are_enforced(ns):
    plans = list(ns['SUPPLEMENTAL_PHASES']['P03', '2019-09-30'])
    broken = list(plans[0])
    broken[4] = '0' * 64
    plans[0] = tuple(broken)
    ns['SUPPLEMENTAL_PHASES']['P03', '2019-09-30'] = tuple(plans)
    label = 'FUTURE_SUPPLEMENT_EXACT_ORIGINAL_SOURCE_BYTES'
    with pytest.raises(ValueError, match=label):
        ns['supplemental_selection']('P03', '2019-09-30')
    assert len(remove_guard(ns, functions()['supplemental_selection'], label)('P03', '2019-09-30')[0]) == 2


def test_generic_merge_collision_falsifier(ns):
    term = chosen()
    label = 'FUTURE_ORIGINAL_ORDINARY_DISJOINT_SELECTED_TERMS'
    with pytest.raises(ValueError, match=label):
        ns['merge_selected_terms']([term], [deepcopy(term)])
    assert len(remove_guard(ns, functions()['merge_selected_terms'], label)([term], [deepcopy(term)])) == 2


@pytest.mark.parametrize('name', ['stock_strategy_shared', 'sentinel', 'research.pooled_input_support', 'numpy', 'pandas'])
def test_financial_import_fence(name):
    with pytest.raises(ImportError, match='CASH_SOURCE_DATA_ONLY'):
        Fence().find_spec(name)
