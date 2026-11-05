"""Generic schema7 source predicates and falsifiers; no financial imports."""
import ast
from copy import deepcopy
import importlib.abc
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_distribution_source as m



class Fence(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('stock_strategy_shared','sentinel','research.pooled_','numpy','pandas')):
            raise AssertionError('FORBIDDEN_FINANCIAL_IMPORT:'+fullname)


@pytest.fixture(autouse=True)
def fence():
    guard=Fence();sys.meta_path.insert(0,guard)
    yield
    sys.meta_path.remove(guard)


def fixture(count=2):
    positions={'P':[dict(slot_id=7,ticker='PT',quantity=13,entry_date='2021-04-13')],'C':[]}
    def row(sid,ticker,day):
        return dict(session=day,security_id=sid,ticker=ticker,issuer_id='SEC_UNKNOWN:'+sid,
            listing_first_session='2020-01-02',security_type_eligible='1',raw_open='17.5',raw_close='18',
            dividend_per_share='0',split_ratio='1',tradeable='1')
    observations=[row('P','PT','2021-05-24'),row('P','PT','2021-05-25'),row('C','CT','2021-05-25')]
    spins=[];queries=[]
    for index in range(count):
        raw=dict(effective_session='2021-05-25',security_id='P',ticker='PT',action='spinoff' if not index else 'spinoffdividend',
            vendor_value=str(index+1),canonical_value=str(index+1),authority='PIT_ACTIONS',known_by='2021-05-25',
            disposition='PIT_ACTION_DIRECT',evidence_hash='',sep_derived_value='')
        source_id=m.sha(json.dumps(raw,sort_keys=True).encode())
        native=dict(session='2021-05-25',parent_ticker='PT',parent_security_id='P',child_ticker=None,child_security_id=None,
            source_row_id=source_id,value_evidence=raw['vendor_value'],child_shares_per_parent=None,child_price=None,
            cash_in_lieu_price=None,policy='REQUIRE_REVIEWED_CHILD_OWNERSHIP')
        spins.append((raw,native));queries.append(dict(schema='research.exact-native-distribution-query/1',
            session='2021-05-25',parent_security_id='P',parent_ticker='PT',source_row_id=source_id,
            native_term_sha256=m.digest(native),raw_source_row_sha256=m.digest(raw),maximum_records=1,financial_use_authorized=False))
    scope=dict(schema=m.DISTRIBUTION_ONLY_SCOPE,parent_outer_sha256='a'*64,parent_cursor='2021-04-30',terms=[],
        expected_native_distribution_count=count,native_distribution_queries=queries,
        additional_rows=[dict(session=r['session'],security_id=r['security_id'],ticker=r['ticker'],
            source_observation_sha256=m.digest(r),parent_positions=deepcopy(positions[r['security_id']])) for r in observations])
    binding=dict(arm='SYNTHETIC',outer_sha256='a'*64,selected_session='2021-04-30',base=dict(archive_sha256='b'*64,bundle_sha256='c'*64))
    return [scope,observations,spins,positions],binding


def without_guard(function,label):
    fn=deepcopy(next(n for n in ast.parse(Path(m.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name==function))
    class Remove(ast.NodeTransformer):
        count=0
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Name) and node.value.func.id=='need' and any(
                    isinstance(value,ast.Constant) and value.value==label for value in node.value.args):
                self.count+=1;return None
            return self.generic_visit(node)
        def visit_For(self,node):
            node=self.generic_visit(node)
            if not node.body:node.body=[ast.Pass()]
            return node
    transform=Remove();fn=transform.visit(fn);assert transform.count==1
    namespace=dict(vars(m));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<removed-generic-distribution-source-guard>','exec'),namespace)
    return namespace[function]


def make_payload():
    args,binding=fixture();data=m.distribution_only_material(*args)
    return m.distribution_only_payload(binding,args[0],data,'d'*64),binding,args[0]


def test_preserved_exact_v6_prefix_and_all_function_class_asts():
    after=Path(m.__file__).read_bytes();before=after[:13727]
    assert m.sha(before)=='b7270b94ac02db3d1090c9fc9e799ebe8046c1c74dc4787a972228564a82856f'
    assert after[:len(before)]==before
    def functions(raw):return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(raw).body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
    old,new=functions(before),functions(after);assert len(old)==11
    assert all(new[name]==value for name,value in old.items())
    assert m.SCHEMA=='research.own-parent-frozen-source-witnesses/6'
    assert m.PARSER_SHA=='5381b3b41b14cfc2f9d9d6e97c35929c9acc3d237d6df359a9ad7e6d0e4df7ec'


@pytest.mark.parametrize('count',[1,2,8])
def test_generic_bounded_source_counts_and_public_dispatch(count):
    args,binding=fixture(count);data=m.distribution_only_material(*args)
    payload=m.distribution_only_payload(binding,args[0],data,'d'*64)
    assert m.validate_scope(args[0])==args[0]['native_distribution_queries']
    assert m.validate(payload,binding,args[0],'d'*64)==payload
    assert payload['schema']==m.DISTRIBUTION_ONLY_SCHEMA and payload['terms']==[]
    assert len(payload['native_distributions'])==count and len(payload['additional_rows'])==3
    assert payload['financial_sessions_advanced']==0 and payload['financial_authority']is False



@pytest.mark.parametrize('change',['extra_scope','terminal','expected_bool','expected_zero','expected_nine','missing_query',
    'query_authority','query_bool_max','query_parent','query_date','duplicate_native','consumed_parent',
    'duplicate_row','bad_row_hash','wrong_role','different_parent_ticker'])
def test_scope_shape_count_date_role_and_hash_refusals(change):
    args,_=fixture();scope=args[0]
    if change=='extra_scope':scope['allow_finance']=True
    elif change=='terminal':scope['terms']=[dict(kind='CASH_MERGER')]
    elif change=='expected_bool':scope['expected_native_distribution_count']=True
    elif change=='expected_zero':scope['expected_native_distribution_count']=0
    elif change=='expected_nine':scope=fixture(9)[0][0]
    elif change=='missing_query':scope['native_distribution_queries'].pop()
    elif change=='query_authority':scope['native_distribution_queries'][0]['financial_use_authorized']=True
    elif change=='query_bool_max':scope['native_distribution_queries'][0]['maximum_records']=True
    elif change=='query_parent':scope['native_distribution_queries'][1]['parent_security_id']='OTHER'
    elif change=='query_date':scope['native_distribution_queries'][1]['session']='2021-05-26'
    elif change=='duplicate_native':scope['native_distribution_queries'][1]=deepcopy(scope['native_distribution_queries'][0])
    elif change=='consumed_parent':scope['parent_cursor']='2021-05-25'
    elif change=='duplicate_row':scope['additional_rows'].append(deepcopy(scope['additional_rows'][0]))
    elif change=='bad_row_hash':scope['additional_rows'][1]['source_observation_sha256']='bad'
    elif change=='wrong_role':scope['additional_rows'][1]['parent_positions'][0]['quantity']=12
    else:scope['additional_rows'][1]['ticker']='OTHER'
    with pytest.raises(ValueError):m.distribution_only_scope(scope)


@pytest.mark.parametrize('change',['extra_observation','missing_observation','duplicate_observation','private_price','metadata_upgrade',
    'parent_quantity','child_owned','extra_role','missing_native','extra_native','duplicate_typed_native','typed_price','raw_known_by'])
def test_material_exact_native_full_row_and_own_role_refusals(change):
    args,_=fixture();scope,rows,spins,roles=args
    if change=='extra_observation':rows.append(deepcopy(rows[0]))
    elif change=='missing_observation':rows.pop()
    elif change=='duplicate_observation':rows[2]=deepcopy(rows[1])
    elif change=='private_price':rows[2]['raw_open']='99'
    elif change=='metadata_upgrade':rows[0]['issuer_id']='SEC_CIK:INVENTED'
    elif change=='parent_quantity':roles['P'][0]['quantity']=12
    elif change=='child_owned':roles['C']=[dict(slot_id=1,ticker='CT',quantity=1,entry_date='2021-04-13')]
    elif change=='extra_role':roles['EXTRA']=[]
    elif change=='missing_native':spins.pop()
    elif change=='extra_native':spins.append(deepcopy(spins[0]))
    elif change=='duplicate_typed_native':spins[1]=(spins[1][0],deepcopy(spins[0][1]))
    elif change=='typed_price':spins[1][1]['child_price']=84.55
    else:spins[1][0]['known_by']='2021-05-24'
    with pytest.raises(ValueError):m.distribution_only_material(*args)


@pytest.mark.parametrize('key,value',[('financial_authority',True),('input_adopted',True),('provider_metadata_upgraded',True),
    ('production_contacted',True),('financial_sessions_advanced',1),('financial_sessions_advanced',False),
    ('schema','research.own-parent-frozen-source-witnesses/6'),('arm','OTHER'),('parser_sha256','e'*64),
    ('producer_sha256','e'*64),('distribution_producer_sha256','e'*64),('scope_sha256','e'*64),('archive_sha256','e'*64)])
def test_schema7_reconstruction_rejects_authority_or_source_binding_change(key,value):
    payload,binding,scope=make_payload();payload[key]=value
    with pytest.raises(ValueError):m.validate(payload,binding,scope,'d'*64)


def test_no_terminal_can_be_inserted_into_distribution_only_payload():
    payload,binding,scope=make_payload();payload['terms']=[dict(source_row={})]
    with pytest.raises(ValueError,match='NO_TERMINAL_PAYLOAD'):m.validate(payload,binding,scope,'d'*64)


def test_all_parent_date_rows_counted_before_requested_hashes_guard_falsifier():
    args,_=fixture();scope=args[0];raws=[deepcopy(x[0]) for x in args[2]]
    unrelated=deepcopy(raws[0]);unrelated['security_id']='OTHER'
    assert m.distribution_only_native_rows(scope,[raws[0],unrelated,raws[1]])==raws
    extra=deepcopy(raws[1]);extra['vendor_value']='unexpected third same-parent native'
    assert m.digest(extra) not in {q['raw_source_row_sha256'] for q in scope['native_distribution_queries']}
    with pytest.raises(ValueError,match='NO_HASH_PREFILTER'):m.distribution_only_native_rows(scope,[raws[0],unrelated,raws[1],extra])
    weak=without_guard('distribution_only_native_rows','DISTRIBUTION_ONLY_ALL_PARENT_DATE_NATIVE_COUNT_NO_HASH_PREFILTER')
    assert weak(scope,[raws[0],unrelated,raws[1],extra])==raws+[extra]


def test_native_bound_guard_removal_admits_nine_records():
    scope=fixture(9)[0][0];label='DISTRIBUTION_ONLY_EXPLICIT_BOUNDED_NATIVE_COUNT'
    with pytest.raises(ValueError,match=label):m.distribution_only_scope(scope)
    assert len(without_guard('distribution_only_scope',label)(scope))==9


def test_observation_uniqueness_guard_removal_admits_duplicate_declaration():
    scope=fixture()[0][0];scope['additional_rows'].append(deepcopy(scope['additional_rows'][0]))
    label='DISTRIBUTION_ONLY_BOUNDED_DISTINCT_ROWS_AND_PRIOR_PARENT_IDENTITY'
    with pytest.raises(ValueError,match=label):m.distribution_only_scope(scope)
    assert without_guard('distribution_only_scope',label)(scope)


def test_repeated_role_guard_removal_admits_changed_own_parent_quantity():
    scope=fixture()[0][0];scope['additional_rows'][1]['parent_positions'][0]['quantity']=12
    label='DISTRIBUTION_ONLY_REPEATED_PARENT_ROLE_AND_TICKER'
    with pytest.raises(ValueError,match=label):m.distribution_only_scope(scope)
    assert without_guard('distribution_only_scope',label)(scope)


def test_exact_role_identity_guard_removal_admits_an_extra_unrequested_book_role():
    args,_=fixture();args[3]['EXTRA']=[];label='DISTRIBUTION_ONLY_EXACT_ROLE_IDENTITIES'
    with pytest.raises(ValueError,match=label):m.distribution_only_material(*args)
    assert without_guard('distribution_only_material',label)(*args)['terms']==[]


def test_source_only_reconstruction_guard_removal_admits_false_authority():
    payload,binding,scope=make_payload();payload['financial_authority']=True
    label='DISTRIBUTION_ONLY_EXACT_RECONSTRUCTION_NO_FINANCIAL_AUTHORITY'
    with pytest.raises(ValueError,match=label):m.validate(payload,binding,scope,'d'*64)
    assert without_guard('distribution_only_validate',label)(payload,binding,scope,'d'*64)['financial_authority']is True


@pytest.mark.parametrize('change',['missing','duplicate','wrong_source_id','raw_hash'])
def test_original_parser_output_pairing_is_complete_and_exact(change):
    args,_=fixture();scope=args[0];raws=[x[0] for x in args[2]];natives=[x[1] for x in args[2]]
    assert m.distribution_only_pairing(scope,raws,natives)==args[2]
    if change=='missing':natives.pop()
    elif change=='duplicate':natives[1]=deepcopy(natives[0])
    elif change=='wrong_source_id':natives[1]['source_row_id']='e'*64
    else:raws[1]['known_by']='2021-05-24'
    with pytest.raises(ValueError):m.distribution_only_pairing(scope,raws,natives)


def test_local_schema7_capture_is_denied_before_parser_import_or_output(monkeypatch,tmp_path):
    def denied():raise ValueError('HOSTED_REQUIRED')
    monkeypatch.setitem(sys.modules,'full_system_core',SimpleNamespace(hosted=denied))
    with pytest.raises(ValueError,match='HOSTED_REQUIRED'):m.capture({},tmp_path,'SYNTHETIC',fixture()[0][0],'d'*64)
    assert not list(tmp_path.iterdir())
