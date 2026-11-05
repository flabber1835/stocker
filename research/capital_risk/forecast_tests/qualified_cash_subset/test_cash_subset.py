"""Exact old-source subsets and adapter guard falsifiers; no financial imports."""
import ast
import builtins
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest


class Fence:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('research.pooled_', 'stock_strategy_shared', 'sentinel', 'numpy', 'pandas')):
            raise ImportError('CASH_SUBSET_DATA_ONLY:' + fullname)


sys.meta_path.insert(0, Fence())
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import system_campaign_qualified_cash_subset as data


def catalog(indices=(0, 2)):
    c = json.loads((Path(data.original.__file__).parent / 'system-campaign-p05-seven-cash-inputs.json').read_bytes())
    c['schema'] = 'research.qualified-own-cash-input-subset/1'
    c['loader_sha256'] = data.original.sha(Path(data.__file__).read_bytes())
    c['selected_source_indices'] = list(indices)
    c['terms'] = [c['terms'][i] for i in indices]
    return c


def test_actual_closed_source_subset_preserves_whole_payload_and_review():
    c = catalog()
    original = deepcopy(c['source_data'])
    assert data.validate(c)
    assert c['source_data'] == original and len(original['payload']['terms']) == 7
    assert len(c['terms']) == 2


def test_path_constructor_uses_exact_catalog_bytes(tmp_path):
    c = catalog()
    raw = data.original.encoded(c)
    path = tmp_path / 'subset.json'
    path.write_bytes(raw)
    obj = data.QualifiedCashSubset(path)
    assert obj.catalog == c and obj.catalog_sha == data.original.sha(raw)
    assert obj.compiler_sha == c['loader_sha256']


@pytest.mark.parametrize('change', ['bool_index', 'negative', 'outside', 'duplicate', 'reordered', 'missing_index',
    'wrong_source', 'paid_extra', 'native_change', 'root_change', 'source_authority', 'review_change'])
def test_inexact_subset_or_original_term_refuses(change):
    c = catalog()
    if change == 'bool_index': c['selected_source_indices'][0] = False
    elif change == 'negative': c['selected_source_indices'][0] = -1
    elif change == 'outside': c['selected_source_indices'][1] = 7
    elif change == 'duplicate': c['selected_source_indices'] = [0, 0]
    elif change == 'reordered': c = catalog((2, 0))
    elif change == 'missing_index': c['selected_source_indices'].pop()
    elif change == 'wrong_source': c['selected_source_indices'][1] = 3
    elif change == 'paid_extra': c['terms'][0]['added']['cash_per_share'] = 21.47
    elif change == 'native_change': c['terms'][0]['native_term_sha256'] = '0' * 64
    elif change == 'root_change': c['parent_root_admission_sha256'] = '0' * 64
    elif change == 'source_authority': c['source_data']['payload']['financial_authority'] = True
    else: c['source_data']['review']['passed'] = False
    with pytest.raises((ValueError, KeyError)): data.validate(c)


def test_removing_sorted_selection_guard_really_admits_reordered_inputs(monkeypatch):
    c = catalog((2, 0))
    with pytest.raises(ValueError, match='SORTED_UNIQUE'): data.validate(c)
    fn, = [n for n in ast.parse(Path(data.__file__).read_bytes()).body
           if isinstance(n, ast.FunctionDef) and n.name == 'selected_members']
    fn.body = [n for n in fn.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Call))]
    scope = dict(vars(data))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<removed-subset-selection-guard>', 'exec'), scope)
    monkeypatch.setattr(data, 'selected_members', scope['selected_members'])
    assert data.validate(c)


def test_undoing_member_selection_restores_entire_original_validator_AST(monkeypatch):
    captured = []
    def capture(tree, *args, **kwargs):
        captured.append(deepcopy(tree))
        return builtins.compile(tree, *args, **kwargs)
    monkeypatch.setattr(data, 'compile', capture, raising=False)
    data.validator()
    tree, = captured
    fn, = tree.body
    extra, = [n for n in fn.body if isinstance(n, ast.Assign)
               and ast.unparse(n.targets[0]) == '(captured, declared, checked_members)']
    fn.body.remove(extra)
    class Undo(ast.NodeTransformer):
        def visit_Name(self, node):
            if node.id == 'checked_members':
                return ast.copy_location(ast.parse("review['terms']", mode='eval').body, node)
            return self.generic_visit(node)
    fn = Undo().visit(fn)
    original, = [n for n in ast.parse(Path(data.original.__file__).read_bytes()).body
                 if isinstance(n, ast.FunctionDef) and n.name == 'validate']
    assert ast.dump(fn, include_attributes=False) == ast.dump(original, include_attributes=False)


def wide_catalog():
    return json.loads((Path(data.__file__).parent / 'system-campaign-p05-own1070-supported-cash-inputs.json').read_bytes())


def test_actual91_member_catalog_declares89_original_literals_and_two_new_primary_inputs():
    c = wide_catalog()
    assert data.validate(c)
    assert len(c['terms']) == 91 and len(c['source_data']['payload']['terms']) == 131
    assert len(c['retained_source_indices']) == 89
    assert [t['ticker'] for t in c['terms'] if 'retained_qualified_legal_term' not in t] == ['HMHC', 'ANAT']


@pytest.mark.parametrize('change', ['missing_original', 'wrong_record', 'wrong_catalog', 'changed_consideration', 'unsafe_path'])
def test_original_legal_term_or_source_mode_cannot_change(change):
    c = wide_catalog()
    t = next(t for t in c['terms'] if t['ticker'] == 'XENT')
    if change == 'missing_original': t.pop('retained_qualified_legal_term')
    elif change == 'wrong_record': t['retained_qualified_legal_term']['term_sha256'] = '0' * 64
    elif change == 'wrong_catalog': t['retained_qualified_legal_term']['catalog_sha256'] = '0' * 64
    elif change == 'unsafe_path': t['retained_qualified_legal_term']['catalog_file'] = '../outside.json'
    else:
        t['added']['cash_per_share'] = 29.25
        t['primary_extraction']['cash_per_share'] = '29.25'
    with pytest.raises(ValueError): data.validate(c)


@pytest.mark.parametrize('label', ['CASH_SUBSET_EXACT_DECLARED_RETAINED_SOURCE_MODES',
    'CASH_SUBSET_ALL_ORIGINAL_ECONOMIC_FIELDS_AND_HELD_AUTHORITY'])
def test_removing_retained_source_guard_really_admits_changed_provenance_or_amount(label):
    c = wide_catalog()
    t = next(t for t in c['terms'] if t['ticker'] == 'XENT')
    if label.endswith('SOURCE_MODES'): t.pop('retained_qualified_legal_term')
    else:
        t['added']['cash_per_share'] = 29.25
        t['primary_extraction']['cash_per_share'] = '29.25'
    with pytest.raises(ValueError, match=label): data.validate(c)
    fn, = [n for n in ast.parse(Path(data.__file__).read_bytes()).body
           if isinstance(n, ast.FunctionDef) and n.name == 'validate']
    class Remove(ast.NodeTransformer):
        def visit_Expr(self, node):
            if isinstance(node.value, ast.Call) and any(isinstance(v, ast.Constant) and v.value == label for v in node.value.args):
                return None
            return self.generic_visit(node)
    fn = Remove().visit(fn); scope = dict(vars(data))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<removed-original-legal-source-guard>', 'exec'), scope)
    assert scope['validate'](c)


@pytest.mark.parametrize('prefix', ['research.pooled_', 'stock_strategy_shared', 'sentinel', 'numpy', 'pandas'])
def test_import_fence(prefix):
    with pytest.raises(ImportError): Fence().find_spec(prefix)
