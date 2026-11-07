"""Pure source capability checks, with guard-removal falsifiers; no finance imports."""
import ast
from copy import deepcopy
import importlib.abc
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_distribution_source as module


class Fence(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('stock_strategy_shared', 'sentinel', 'numpy', 'pandas') or fullname.startswith('research.pooled_'):
            raise AssertionError('FORBIDDEN_FINANCIAL_IMPORT:' + fullname)


@pytest.fixture(autouse=True)
def import_fence():
    guard=Fence();sys.meta_path.insert(0,guard)
    yield
    sys.meta_path.remove(guard)


def fixture():
    parent,child,delivered='P','C','D'
    def row(sid,ticker,day):
        return dict(session=day,security_id=sid,ticker=ticker,issuer_id='SEC_UNKNOWN:'+sid,
            listing_first_session='2000-01-03',security_type_eligible='0' if sid=='P' else '1',
            raw_open='49.61' if sid=='P' else '39.85' if sid=='C' else '110.31',
            raw_close='49.61',split_ratio='1',dividend_per_share='0',tradeable='1')
    source=row(parent,'PT','2019-03-19')
    additional=[row(parent,'PT','2019-03-20'),row(child,'CT','2019-03-20'),row(delivered,'DT','2019-03-20')]
    raw=dict(effective_session='2019-03-21',security_id=parent,ticker='PT',action='spinoff',vendor_value='0.33333000000000002',
        canonical_value='0.33333000000000002',disposition='PIT_ACTION_DIRECT',sep_derived_value='',known_by='2019-03-21',authority='PIT_ACTIONS',evidence_hash='')
    native=dict(session='2019-03-21',parent_security_id=parent,parent_ticker='PT',child_security_id=None,
        child_ticker=None,source_row_id=module.sha(module.json.dumps(raw,sort_keys=True).encode()),value_evidence=raw['vendor_value'],
        child_shares_per_parent=None,child_price=None,cash_in_lieu_price=None,policy='REQUIRE_REVIEWED_CHILD_OWNERSHIP')
    term=dict(session='2019-03-20',security_id=parent,kind='CASH_MERGER',reference='incomplete source',
        cash_per_share=None,delivered_security_id=None,delivered_ticker=None,delivered_issuer_id=None,
        exchange_ratio=None,cash_in_lieu_price_per_delivered_share=None,entitlement_aggregation='HOLDER')
    positions={parent:[dict(slot_id=12,ticker='PT',quantity=34,entry_date='2018-12-28')],child:[],delivered:[]}
    scope=dict(parent_outer_sha256='a'*64,parent_cursor='2019-02-28',terms=[dict(session='2019-03-19',
        native_session='2019-03-20',security_id=parent,ticker='PT',native_term_sha256=module.digest(term),parent_positions=positions[parent])],
        additional_rows=[dict(session=r['session'],security_id=r['security_id'],ticker=r['ticker'],
            source_observation_sha256=module.digest(r),parent_positions=positions[r['security_id']]) for r in additional],
        native_distribution_queries=[dict(schema='research.exact-native-distribution-query/1',session='2019-03-21',
            parent_security_id=parent,parent_ticker='PT',source_row_id=native['source_row_id'],native_term_sha256=module.digest(native),
            raw_source_row_sha256=module.digest(raw),maximum_records=1,financial_use_authorized=False)])
    binding=dict(arm='P06',outer_sha256='a'*64,selected_session='2019-02-28',base=dict(archive_sha256='b'*64,bundle_sha256='c'*64))
    args=[scope,[term],[source],additional,[(raw,native)],deepcopy(positions)]
    return args,binding


def payload():
    args,binding=fixture();data=module.material(*args)
    return module.payload(binding,args[0],data,'d'*64),binding,args[0]


def test_both_natives_three_additional_rows_are_source_only_and_exact():
    value,binding,scope=payload()
    assert module.validate(value,binding,scope,'d'*64)==value
    assert value['terms'][0]['parent_positions'][0]['quantity']==34
    assert len(value['additional_rows'])==3 and len(value['native_distributions'])==1
    assert value['financial_sessions_advanced']==0 and value['financial_authority'] is False
    assert value['additional_rows'][1]['identity_witness']['issuer_id']=='SEC_UNKNOWN:C'


@pytest.mark.parametrize('which',range(13))
def test_source_scope_native_quote_and_actual_role_falsifiers(which):
    args,_=fixture()
    scope,terminals,rows,additional,spins,roles=args
    if which==0: roles['P'][0]['quantity']=33
    elif which==1: roles['C']=[dict(slot_id=1,ticker='CT',quantity=1,entry_date='2018-12-01')]
    elif which==2: additional[1]['issuer_id']='SEC_CIK:invented'
    elif which==3: additional[1]['raw_open']='38'
    elif which==4: terminals[0]['cash_per_share']=0
    elif which==5: terminals[0]['session']='2019-03-19'
    elif which==6: spins[0][1]['session']='2019-03-20'
    elif which==7: spins[0][0]['vendor_value']='1/3'
    elif which==8: spins.append(deepcopy(spins[0]))
    elif which==9: additional.pop()
    elif which==10: additional[-1]=deepcopy(additional[0])
    elif which==11: scope['native_distribution_queries'][0]['financial_use_authorized']=True
    elif which==12: scope['parent_cursor']='2019-03-20'
    with pytest.raises(ValueError):module.material(*args)


@pytest.mark.parametrize('key,value', [('financial_authority',True),('input_adopted',True),('production_contacted',True),
    ('provider_metadata_upgraded',True),('financial_sessions_advanced',False),('financial_sessions_advanced',1),
    ('archive_sha256','e'*64),('producer_sha256','e'*64),('distribution_producer_sha256','e'*64),
    ('scope_sha256','e'*64),('arm','P00'),('parent_outer_sha256','e'*64)])
def test_reconstruction_rejects_false_authority_or_wrong_binding(key,value):
    result,binding,scope=payload();result[key]=value
    with pytest.raises(ValueError):module.validate(result,binding,scope,'d'*64)


def without_guard(name, code):
    fn=next(n for n in ast.parse(Path(module.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name==name)
    before=len(fn.body)
    fn.body=[n for n in fn.body if not any(isinstance(v,ast.Constant) and v.value==code for v in ast.walk(n))]
    assert len(fn.body)==before-1
    scope=dict(vars(module));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-source-guard>','exec'),scope)
    return scope[name]


def test_full_row_guard_removal_exposes_changed_private_price():
    args,_=fixture();row=args[3][1];declared=args[0]['additional_rows'][1]
    row['raw_open']='38'
    with pytest.raises(ValueError,match='FULL_OBSERVATION_DIGEST'):module.identity(row,declared,[])
    mutant=without_guard('identity','DISTRIBUTION_SOURCE_FULL_OBSERVATION_DIGEST')
    assert mutant(row,declared,[])['source_row']['raw_open']=='38'


def test_raw_native_hash_guard_removal_exposes_changed_source_action():
    args,_=fixture();raw,spin=args[4][0];query=args[0]['native_distribution_queries'][0]
    raw['known_by']='2019-03-20'
    with pytest.raises(ValueError,match='EXACT_RAW_ROW'):module.distribution_material(query,raw,spin)
    mutant=without_guard('distribution_material','DISTRIBUTION_SOURCE_EXACT_RAW_ROW_AND_ORIGINAL_PARSER_HASH')
    assert mutant(query,raw,spin)['raw_source_row']['known_by']=='2019-03-20'


def test_typed_native_guard_removal_exposes_changed_child_contract():
    args,_=fixture();raw,spin=args[4][0];query=args[0]['native_distribution_queries'][0]
    spin['child_ticker']='invented'
    with pytest.raises(ValueError,match='UNRESOLVED_NATIVE'):module.distribution_material(query,raw,spin)
    mutant=without_guard('distribution_material','DISTRIBUTION_SOURCE_EXACT_UNRESOLVED_NATIVE_PREIMAGE')
    assert mutant(query,raw,spin)['native_distribution']['child_ticker']=='invented'


def test_no_local_capture_imports_or_creates_output(monkeypatch,tmp_path):
    def denied():raise ValueError('HOSTED_REQUIRED')
    monkeypatch.setitem(sys.modules,'full_system_core',SimpleNamespace(hosted=denied))
    with pytest.raises(ValueError,match='HOSTED_REQUIRED'):module.capture({},tmp_path,'P06',{},'d'*64)
    assert not list(tmp_path.iterdir())


def test_no_financial_authority_reconstruction_guard_removal_falsifier():
    value,binding,scope=payload();value['financial_authority']=True
    with pytest.raises(ValueError,match='EXACT_RECONSTRUCTION_NO_FINANCIAL_AUTHORITY'):
        module.validate(value,binding,scope,'d'*64)
    mutant=without_guard('validate','DISTRIBUTION_SOURCE_EXACT_RECONSTRUCTION_NO_FINANCIAL_AUTHORITY')
    assert mutant(value,binding,scope,'d'*64)['financial_authority'] is True


def test_unconsumed_two_legs_guard_removal_falsifier():
    args,_=fixture();scope=args[0];scope['parent_cursor']='2019-03-20'
    # Keep the independent additional-row future guard satisfied, isolating the
    # consumed terminal/identity leg that this specific guard must reject.
    for row in scope['additional_rows']:row['session']='2019-03-21'
    with pytest.raises(ValueError,match='EXACT_UNCONSUMED_TWO_LEGS'):module.validate_scope(scope)
    mutant=without_guard('validate_scope','DISTRIBUTION_SOURCE_EXACT_UNCONSUMED_TWO_LEGS')
    assert mutant(scope)[0]['native_session']==scope['parent_cursor']


def capture_selection_function(remove_guard=False):
    """Execute the unchanged capture selection/count AST on synthetic rows only."""
    tree=ast.parse(Path(module.__file__).read_bytes())
    capture=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='capture')
    loop=deepcopy(next(n for n in ast.walk(capture) if isinstance(n,ast.For)
        and isinstance(n.target,ast.Name) and n.target.id=='row'
        and any(isinstance(v,ast.Attribute) and v.attr=='append' and isinstance(v.value,ast.Name)
                and v.value.id=='raw_spins' for v in ast.walk(n))))
    loop.iter=ast.Name(id='rows',ctx=ast.Load())
    guard=deepcopy(next(n for n in ast.walk(capture) if isinstance(n,ast.Expr)
        and isinstance(n.value,ast.Call) and any(isinstance(v,ast.Constant)
        and v.value=='DISTRIBUTION_SOURCE_ONE_ORIGINAL_ACTION_PREIMAGE' for v in ast.walk(n))))
    fn=ast.parse('def select(rows,query):\n raw_spins=[]\n return raw_spins\n').body[0]
    fn.body.insert(1,loop)
    if not remove_guard:fn.body.insert(2,guard)
    namespace=dict(vars(module));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<exact-capture-selection-and-count-on-synthetic-rows>','exec'),namespace)
    return namespace['select']


def test_capture_rejects_extra_same_parent_native_count_guard_removal_falsifier():
    args,_=fixture();raw=args[4][0][0];query=args[0]['native_distribution_queries'][0]
    unrelated=deepcopy(raw);unrelated['security_id']='OTHER'
    select=capture_selection_function();assert select([raw,unrelated],query)==[raw]
    # A second same-parent event with a different raw-row hash must be counted,
    # rather than hidden by matching only the requested original source-row ID.
    extra=deepcopy(raw);extra['vendor_value']='different unresolved distribution'
    with pytest.raises(ValueError,match='ONE_ORIGINAL_ACTION_PREIMAGE'):select([raw,unrelated,extra],query)
    assert capture_selection_function(remove_guard=True)([raw,unrelated,extra],query)==[raw,extra]
