"""A read-only native query resolves exact bytes without financial authority."""
import ast
from copy import deepcopy
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_future as f
import system_campaign_financial_partial as p
from research.capital_risk.forecast_tests.test_financial_source_witnesses import source_fixture,spec


def fixture():
    cp,scope,natives,rows=source_fixture()
    native=natives[0]
    native.update(reference='actual frozen incomplete native',entitlement_aggregation='HOLDER',
                  delivered_security_id=None,delivered_ticker=None,delivered_issuer_id=None,
                  exchange_ratio=None,cash_in_lieu_price_per_delivered_share=None)
    scope['terms'][0]['native_term_sha256']=None
    scope['native_preimage_query']=dict(schema='research.unconsumed-cash-native-preimage-query/1',
        native_kind='CASH_MERGER',maximum_terms=1,financial_use_authorized=False)
    return cp,scope,natives,rows


def test_query_resolves_only_native_hash_and_preserves_original_query_and_state():
    cp,scope,natives,rows=fixture();before=deepcopy((cp,scope,natives,rows))
    value=f.witness_payload(cp,'P04',scope,natives,rows)
    assert f.validate_witness_capture(value,spec(cp),scope)==value
    assert value['schema']==f.SOURCE_WITNESS_DISCOVERY_SCHEMA
    assert value['query_scope']==scope and value['query_scope_sha256']==f.digest(scope)
    expected=deepcopy(scope);del expected['native_preimage_query']
    expected['terms'][0]['native_term_sha256']=f.digest(natives[0])
    assert value['scope']==expected and value['scope_sha256']==f.digest(expected)
    assert value['terms'][0]['native_term']==natives[0]
    assert value['financial_authority'] is value['input_adopted'] is False and value['financial_sessions_advanced']==0
    assert (cp,scope,natives,rows)==before


@pytest.mark.parametrize('change',['mode','authority','integer_false','boolean_count','count','multiple',
                                   'hash','consumed','pending','extra_rows','kind','cash','delivery',
                                   'missing_field','extra_field','reference','native_day','native_sid'])
def test_discovery_cannot_qualify_other_native_shapes_or_consumed_state(change):
    cp,scope,natives,rows=fixture();q=scope['native_preimage_query'];n=natives[0]
    if change=='mode':q['schema']='research.other/1'
    elif change=='authority':q['financial_use_authorized']=True
    elif change=='integer_false':q['financial_use_authorized']=0
    elif change=='boolean_count':q['maximum_terms']=True
    elif change=='count':q['maximum_terms']=2
    elif change=='multiple':scope['terms'].append(deepcopy(scope['terms'][0]));natives.append(deepcopy(n))
    elif change=='hash':scope['terms'][0]['native_term_sha256']='0'*64
    elif change=='consumed':scope['parent_cursor']=n['session']
    elif change=='pending':scope['terms'][0]['pending_at_parent']={}
    elif change=='extra_rows':scope['additional_rows']=[dict(invalid=True)]
    elif change=='kind':n['kind']='CONVERSION'
    elif change=='cash':n['cash_per_share']=100.
    elif change=='delivery':n['delivered_security_id']='other'
    elif change=='missing_field':del n['exchange_ratio']
    elif change=='extra_field':n['new_field']='unreviewed'
    elif change=='reference':n['reference']=''
    elif change=='native_day':n['session']='2022-07-22'
    else:n['security_id']='other'
    with pytest.raises(ValueError):f.resolved_query_scope(scope,natives)


@pytest.mark.parametrize('change',['query','query_hash','resolved','resolved_hash','native','schema','finance'])
def test_captured_query_and_resolved_preimage_cannot_be_substituted(change):
    cp,scope,natives,rows=fixture();value=f.witness_payload(cp,'P04',scope,natives,rows)
    if change=='query':value['query_scope']['terms'][0]['ticker']='OTHER'
    elif change=='query_hash':value['query_scope_sha256']='0'*64
    elif change=='resolved':value['scope']['terms'][0]['native_term_sha256']='0'*64
    elif change=='resolved_hash':value['scope_sha256']='0'*64
    elif change=='native':value['terms'][0]['native_term']['reference']='substituted'
    elif change=='schema':value['schema']=f.SOURCE_WITNESS_SCHEMA
    else:value['financial_authority']=True
    with pytest.raises(ValueError):f.validate_witness_capture(value,spec(cp),scope)


def test_unguessed_hash_is_never_accepted_by_the_original_exact_preimage_validator():
    cp,scope,natives,rows=fixture();del scope['native_preimage_query']
    with pytest.raises(ValueError):f.witness_payload(cp,'P04',scope,natives,rows)


def test_discovery_native_shape_guard_removal_allows_consideration():
    cp,scope,natives,rows=fixture();natives[0]['cash_per_share']=100.
    with pytest.raises(ValueError):f.resolved_query_scope(scope,natives)
    fn=next(n for n in ast.parse(Path(f.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='resolved_query_scope')
    guard=next(n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
               and any(isinstance(a,ast.Constant) and a.value=='SOURCE_DISCOVERY_EXACT_FROZEN_INCOMPLETE_CASH_NATIVE_SHAPE' for a in n.value.args))
    fn.body.remove(guard);ns=dict(vars(f))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-native-discovery-shape-guard>','exec'),ns)
    assert ns['resolved_query_scope'](scope,natives)['terms'][0]['native_term_sha256']==f.digest(natives[0])


def test_existing_source_terms_predicates_are_byte_for_byte_ast_identical():
    old=subprocess.check_output(['git','show','08382e11758c1813f5d40747108564064638cbbb:research/capital_risk/system_campaign_financial_future.py'])
    def fn(raw):return next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='source_terms')
    assert ast.dump(fn(old),include_attributes=False)==ast.dump(fn(Path(f.__file__).read_bytes()),include_attributes=False)


def test_actual_gbt_query_uses_the_new1196_root_and_closes_old_five_term_catalog():
    scope=f.DISCOVERY_WITNESS_SCOPES['P04'];root=p.root_spec('P04');term,=scope['terms']
    assert root['measured_closes']==1196 and root['selected_session']==scope['parent_cursor']=='2022-09-30'
    assert root['outer_sha256']==scope['parent_outer_sha256'] and term['native_term_sha256'] is None
    assert term['ticker']=='GBT' and term['native_session']=='2022-10-04' and term['parent_positions']==[]
    assert f.CLOSED_CASH_GENERATIONS['5a917388cfa61ed86d60792e263260fca876eaf3d8f3606ad95744d7a5ed7ed7']==5


def without_guard(name,label):
    fn=next(n for n in ast.parse(Path(f.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name==name)
    guard=next(n for n in ast.walk(fn) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
               and any(isinstance(a,ast.Constant) and a.value==label for a in n.value.args))
    for node in ast.walk(fn):
        for field in ('body','orelse'):
            body=getattr(node,field,None)
            if isinstance(body,list) and guard in body:body[body.index(guard)]=ast.Pass()
    ns=dict(vars(f));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-query-scope-guard>','exec'),ns)
    return ns[name]


def test_removed_unconsumed_query_guard_resolves_an_already_consumed_native():
    cp,scope,natives,rows=fixture();scope['parent_cursor']=natives[0]['session']
    with pytest.raises(ValueError):f.resolved_query_scope(scope,natives)
    assert without_guard('resolved_query_scope','SOURCE_DISCOVERY_ONLY_ONE_EXPLICIT_UNCONSUMED_NATIVE_QUERY')(scope,natives)


def test_removed_original_query_guard_accepts_a_substituted_query_commitment():
    cp,scope,natives,rows=fixture();payload=f.witness_payload(cp,'P04',scope,natives,rows)
    payload['query_scope_sha256']='0'*64
    with pytest.raises(ValueError):f.validate_witness_capture(payload,spec(cp),scope)
    assert without_guard('validate_witness_capture','SOURCE_DISCOVERY_ORIGINAL_QUERY_AND_RESOLVED_SCOPE_BOUND')(payload,spec(cp),scope)


def test_removed_extra_row_guard_silently_drops_an_undeclared_observation():
    cp,scope,natives,rows=fixture()
    with pytest.raises(ValueError):f.witness_payload(cp,'P04',scope,natives,rows,[dict(extra=True)])
    value=without_guard('witness_payload','SOURCE_DISCOVERY_NO_UNDECLARED_ADDITIONAL_ROWS')(cp,'P04',scope,natives,rows,[dict(extra=True)])
    assert 'additional_rows' not in value
