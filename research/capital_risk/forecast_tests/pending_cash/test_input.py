"""Actual authenticated source/input metadata only, with runtime imports fenced."""
import ast, gzip, json, sys
from copy import deepcopy
from pathlib import Path
import pytest

class Fence:

    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('research.pooled_', 'stock_strategy_shared', 'sentinel', 'numpy', 'pandas')):
            raise ImportError('PENDING_CASH_DATA_ONLY:' + fullname)
sys.meta_path.insert(0, Fence())
sys.path.insert(0, str(Path(__file__).parent))
import system_campaign_qualified_pending_cash as data
import system_campaign_pending_cash_api as api

@pytest.fixture(scope='module')
def catalog():
    return json.loads((data.HERE / api.CATALOG).read_bytes())

@pytest.mark.parametrize('change', ['amount', 'completion', 'last_trade', 'source_clock', 'native_cash', 'native_hash', 'identity', 'positions', 'schema', 'loader', 'provider_upgrade', 'production', 'preopen', 'primary_hash', 'stock_fact', 'additional'])
def test_wrong_input_primary_role_or_source_refuses(catalog, change):
    c = deepcopy(catalog)
    t = c['terms'][0]
    if change == 'amount':
        t['added']['cash_per_share'] = 54.0
    elif change == 'completion':
        t['added']['session'] = t['actual_completion_date'] = '2022-06-30'
    elif change == 'last_trade':
        t['last_trading_session'] = '2022-06-29'
    elif change == 'source_clock':
        t['source_capture']['run_id'] -= 1
    elif change == 'native_cash':
        t['native']['cash_per_share'] = 55.0
    elif change == 'native_hash':
        t['native_term_sha256'] = '0' * 64
    elif change == 'identity':
        t['identity_witness']['issuer_id'] = 'FOREIGN'
    elif change == 'positions':
        t['parent_positions'][0]['quantity'] = 36
    elif change == 'schema':
        c['schema'] = 'research.qualified-own-cash-input-batch/1'
    elif change == 'loader':
        c['loader_sha256'] = '0' * 64
    elif change == 'provider_upgrade':
        c['provider_metadata_upgraded'] = True
    elif change == 'production':
        c['production_contacted'] = True
    elif change == 'preopen':
        t['preopen_completion_confirmed'] = False
    elif change == 'primary_hash':
        t['primary_extraction']['qualified_cash_only_primary_fact_sha256'] = '0' * 64
    elif change == 'stock_fact':
        t['primary_extraction']['no_stock_or_contingent_rights_in_common_consideration'] = False
    else:
        c['source_data']['payload']['additional_rows'] = [{}]
    with pytest.raises(ValueError):
        data.validate(c)

def test_whole_original_validator_and_source_binding_AST_undo():
    original = ast.parse(data.original_source())
    before = next((n for n in original.body if isinstance(n, ast.FunctionDef) and n.name == 'validate'))
    after = data.validate_tree()

    class Undo(ast.NodeTransformer):
        count = 0

        def visit_Call(self, node):
            if isinstance(node.func, ast.Name) and node.func.id == 'pending_clock':
                self.count += 1
                return ast.parse("catalog['parent_cursor'] < term['native_session']", mode='eval').body
            return self.generic_visit(node)
    undo = Undo()
    after = undo.visit(after)
    assert undo.count == 1 and ast.dump(after, include_attributes=False) == ast.dump(before, include_attributes=False)
    before = next((n for n in original.body if isinstance(n, ast.FunctionDef) and n.name == 'source_binding'))
    after = data.source_binding_tree()
    after.body.insert(0, deepcopy(before.body[0]))

    class OldSchema(ast.NodeTransformer):

        def visit_Constant(self, node):
            if node.value == 'research.own-parent-frozen-source-witnesses/2':
                node.value = 'research.own-parent-frozen-source-witnesses/1'
            return node
    assert ast.dump(OldSchema().visit(after), include_attributes=False) == ast.dump(before, include_attributes=False)
    assert data.QualifiedPendingCash._dict_init.__code__ is data.original.QualifiedCashBatch.__init__.__code__

def test_all_original_api_code_objects_and_only_one_private_registry_addition():
    bound = api.private_api()
    for name in api.FUNCTIONS:
        assert getattr(bound, name).__code__ is getattr(api.original, name).__code__
    phases = bound.selected.__globals__['FUTURE_LITERAL_PHASES']
    assert ('P05', '2022-06-30') not in api.original.FUTURE_LITERAL_PHASES
    assert {k: v for k, v in phases.items() if k != ('P05', '2022-06-30')} == api.original.FUTURE_LITERAL_PHASES
    assert bound.hydrate.__globals__['__file__'] == api.__file__
    assert api.for_parent(dict(source_cursor='2022-05-31'), 'P05') is api.original

def rebind_source_digests(c):
    source = c['source_data']
    p, r, q = (source[k] for k in ('payload', 'review', 'qualification'))
    r['payload_sha256'] = data.sha(data.encoded(p))
    q['payload_sha256'] = r['payload_sha256']
    q['review_sha256'] = data.sha(data.encoded(r))
    c['terms'][0]['source_capture'].update(payload_sha256=r['payload_sha256'], independent_data_review_sha256=q['review_sha256'], independent_qualification_sha256=data.sha(data.encoded(q)))

def test_removing_pending_clock_accepts_bool_age_and_is_detected(catalog, monkeypatch):
    c = deepcopy(catalog)
    for name in ('payload', 'review'):
        c['source_data'][name]['terms'][0]['pending_context']['pending_sessions'] = False
    rebind_source_digests(c)
    with pytest.raises(ValueError, match='EXACT_SOURCE_NATIVE_ROLE_AND_CLOCK'):
        data.validate(c)
    monkeypatch.setattr(data, 'pending_clock', lambda *a: True)
    assert data.validate(c)

def test_original_pending_cases_delegate_and_source_runtime_stays_unmodified(monkeypatch):
    calls = []
    monkeypatch.setattr(api.original, 'pending_completion', lambda *a: calls.append(a))
    cp = {'synthetic': True}
    t = {'arm': 'P00', 'security_id': 'SYNTHETIC_MNTA'}
    api.pending_completion(cp, t)
    assert calls == [(cp, t)]

@pytest.mark.parametrize('name', ['research.pooled_', 'stock_strategy_shared', 'sentinel', 'numpy', 'pandas'])
def test_financial_runtime_import_fence(name):
    with pytest.raises(ImportError):
        Fence().find_spec(name)
