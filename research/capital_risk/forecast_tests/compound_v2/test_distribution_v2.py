"""Generic v2 DATA/input/loaded-view tests; canonical finance imports forbidden."""
import ast
from copy import deepcopy
from dataclasses import asdict,dataclass,replace
from datetime import date
from decimal import Decimal
from fractions import Fraction
import importlib.abc
import json
from pathlib import Path
import sys
from typing import Annotated,Literal

import pytest
from pydantic import BaseModel,ConfigDict,Field,PrivateAttr,model_validator

ROOT=Path(__file__).parent/'fixtures'
C=Path(__file__).resolve().parents[2]
class Fence(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('stock_strategy_shared','sentinel','research.pooled_','numpy','pandas')):
            raise AssertionError('FORBIDDEN_CANONICAL_FINANCIAL_IMPORT:'+fullname)
sys.meta_path.insert(0,Fence());sys.path.insert(0,str(C));sys.path.insert(0,str(ROOT))
import system_campaign_financial_compound_input_v2 as m
import system_campaign_financial_compound_v2_support as s

def raw(name):
    if name=='frozen-original-repair-source.py':return pure_repair_container()
    selected=ROOT/name
    return (selected if selected.exists() else C/name).read_bytes()
def data(name):return json.loads(raw(name))
def model():return deepcopy(data('system-campaign-compound-input-v2-facts.json')['records'][0]['research_assumption'])

def witness():
    discovery=data('PPLI-frozen-source-discovery.json');scope=data('P07-source7-scope.json')
    natives=data('PPLI-native-preimages.json')['native_distributions'];rows=[]
    for declared in scope['additional_rows']:
        row=next(v['source_row'] for v in discovery['observations'] if (v['source_row']['session'],v['source_row']['security_id'])==(declared['session'],declared['security_id']))
        w={k:row[k] for k in ('session','security_id','ticker','issuer_id','listing_first_session','security_type_eligible')};w['source_observation_sha256']=m.digest(row)
        rows.append(dict(source_row=row,identity_witness=w,parent_positions=declared['parent_positions']))
    return dict(schema='research.own-parent-frozen-source-witnesses/7',arm='P07',terms=[],additional_rows=rows,
        native_distributions=natives,parent_cursor=scope['parent_cursor'],parent_outer_sha256=scope['parent_outer_sha256'],
        scope=scope,scope_sha256=m.digest(scope),distribution_producer_sha256='8'*64,financial_sessions_advanced=0,
        financial_authority=False,input_adopted=False,provider_metadata_upgraded=False,production_contacted=False,
        synthetic_fixture=True)

def proof(w=None):
    w=w or witness()
    return dict(independent_DATA_passed=True,independent_qualification_passed=True,payload_sha256=m.sha(m.encoded(w)),
        payload_digest=m.digest(w),scope_sha256=w['scope_sha256'],distribution_producer_sha256=w['distribution_producer_sha256'],
        independent_data_review_sha256='a'*64,independent_qualification_sha256='b'*64)

def binding():
    w=witness();return m.build_terms(model(),w,child_security_id='211901312635613499',reference='synthetic disclosed primary/source-bound event',source_proof=proof(w))

@dataclass(frozen=True)
class Spin:
    session:str;parent_ticker:str;parent_security_id:str;child_ticker:str|None;child_security_id:str|None;source_row_id:str;value_evidence:str|None
    child_shares_per_parent:str|None=None;child_price:str|None=None;cash_in_lieu_price:str|None=None;policy:str='REQUIRE_REVIEWED_CHILD_OWNERSHIP'
@dataclass(frozen=True)
class Bar:
    session:str;security_id:str;ticker:str;raw_close:float;raw_open:float;volume:float
    split_ratio:float=1.;dividend_per_share:float=0.;tradeable:bool=True;unresolved_corporate_action:bool=False;signal_close:float|None=None
@dataclass(frozen=True)
class Packet:
    day:str;bars:tuple;terminal:tuple;spins:tuple;other:str='preserved unrelated input'

def vendor(row):return Bar(row['session'],row['security_id'],row['ticker'],float(row['raw_close']),float(row['raw_open']),float(row['raw_compatible_volume']),
    float(row['split_ratio']),float(row['dividend_per_share']),row['tradeable']=='1',False,float(row['signal_close']))

def source_namespace():
    source=raw('frozen-original-repair-source.py');tree=ast.parse(source)
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('_digest','_session')]
    assert len(nodes)==2 and m.sha(source)==PURE_CONTAINER_SHA
    ns=dict(asdict=asdict,replace=replace,Decimal=Decimal,date=date,json=json,hashlib=__import__('hashlib'))
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<exact-original-pure-input-helpers>','exec'),ns)
    return ns

def projection():
    b=binding();p=vendor(b['original_rows'][b['spin']['parent_security_id']]);c=vendor(b['original_rows'][b['spin']['child_security_id']])
    ctx=m.EventSessionProjection(b,parent_bar=p,child_bar=c,source_raw=raw('frozen-original-repair-source.py'),source_namespace=source_namespace(),spin_factory=Spin)
    sibling=Spin('2021-05-25','OTHER','OTHER',None,None,'other native','evidence')
    packet=Packet('2021-05-25',(p,c),('unrelated terminal',),(*ctx.originals,sibling))
    return b,ctx,packet

def drop(module,name,label):
    fn=next(n for n in ast.parse(Path(module.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name==name)
    guard=next(n for n in ast.walk(fn) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and any(isinstance(a,ast.Constant) and a.value==label for a in n.value.args))
    for n in ast.walk(fn):
        for field in ('body','orelse'):
            body=getattr(n,field,None)
            if isinstance(body,list) and guard in body:body[body.index(guard)]=ast.Pass()
    ns=dict(vars(module));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-v2-data-guard>','exec'),ns)
    return ns[name]

def test_one_child_two_original_sources_and_only_parent_cash_proxy_changes():
    b,ctx,packet=projection();before=deepcopy(packet);out=ctx.apply(packet,ctx.descriptor)
    assert packet==before and len(out.spins)==2 and out.spins[0].parent_security_id=='OTHER' and out.spins[1]==ctx.added
    assert len(ctx.local.suppress)==2 and out.bars[0]==replace(packet.bars[0],dividend_per_share=0.) and out.bars[1]==packet.bars[1]
    assert out.terminal==packet.terminal and out.other==packet.other
    assert b['terminal'] is None and b['original_rows'][b['spin']['parent_security_id']]['issuer_id']=='SEC_UNKNOWN:517224929580411308'
    assert ctx.fn.__code__.co_filename=='<source-bound-distribution-packet-codec>'

@pytest.mark.parametrize('change',['missing','duplicate','extra_same_parent','wrong_date','parent_quote','child_quote','parent_proxy'])
def test_packet_and_native_group_substitutions_refuse(change):
    b,ctx,packet=projection()
    if change=='missing':packet=replace(packet,spins=packet.spins[1:])
    elif change=='duplicate':packet=replace(packet,spins=(packet.spins[0],packet.spins[0],packet.spins[2]))
    elif change=='extra_same_parent':packet=replace(packet,spins=packet.spins+(replace(packet.spins[0],source_row_id='new'),))
    elif change=='wrong_date':packet=replace(packet,day='2021-05-26')
    elif change=='parent_quote':packet=replace(packet,bars=(replace(packet.bars[0],raw_open=174.),packet.bars[1]))
    elif change=='child_quote':packet=replace(packet,bars=(packet.bars[0],replace(packet.bars[1],raw_open=48.)))
    else:packet=replace(packet,bars=(replace(packet.bars[0],dividend_per_share=84.54),packet.bars[1]))
    with pytest.raises(ValueError):ctx.apply(packet,ctx.descriptor)

def test_unrelated_and_prior_packets_remain_identical():
    b,ctx,packet=projection()
    prior=replace(packet,day='2021-05-24',spins=())
    later=replace(prior,day='2022-02-23',terminal=('genuine VCRA ordinary input',))
    assert ctx.apply(prior,ctx.descriptor) is prior and ctx.apply(later,ctx.descriptor) is later

def test_other_session_future_different_native_for_same_parent_remains_unchanged():
    b,ctx,packet=projection()
    event=replace(ctx.originals[0],session='2022-01-04',source_row_id='different-future-native')
    later=replace(packet,day=event.session,spins=(event,))
    assert ctx.apply(later,ctx.descriptor) is later

@pytest.mark.parametrize('change',['data','qualification','zero_hash','authority','integer_advance','extra_native','raw_row','identity','held_child','ratio','proxy','settlement'])
def test_unclosed_source_and_unreviewed_model_scope_refuse(change):
    w=witness();p=proof(w);v=model()
    if change=='data':p['independent_DATA_passed']=False
    elif change=='qualification':p['independent_qualification_passed']=False
    elif change=='zero_hash':p['independent_data_review_sha256']='0'*64
    elif change=='authority':w['financial_authority']=True;p=proof(w)
    elif change=='integer_advance':w['financial_sessions_advanced']=False;p=proof(w)
    elif change=='extra_native':w['native_distributions'].append(deepcopy(w['native_distributions'][0]));p=proof(w)
    elif change=='raw_row':w['native_distributions'][0]['raw_source_row']['vendor_value']='2';p=proof(w)
    elif change=='identity':w['additional_rows'][0]['source_row']['issuer_id']='UPGRADED';p=proof(w)
    elif change=='held_child':w['additional_rows'][2]['parent_positions']=[dict(quantity=1)];p=proof(w)
    elif change=='ratio':v['child_shares_per_original_parent']='1.7'
    elif change=='proxy':w['additional_rows'][1]['source_row']['dividend_per_share']='0';p=proof(w)
    else:v['actual_settlement_claimed']=True
    with pytest.raises(ValueError):m.build_terms(v,w,child_security_id='211901312635613499',reference='test',source_proof=p)

def test_source_data_guard_removal_falsifier():
    w=witness();p=proof(w);p['independent_DATA_passed']=False
    with pytest.raises(ValueError):m.require_closed_source(w,p)
    assert drop(m,'require_closed_source','DISTRIBUTION_V2_CLOSED_SOURCE_DATA_PINS_REQUIRED_NO_PLACEHOLDER')(w,p) is None

def test_ratio_cash_proxy_guard_removal_falsifier():
    w=witness();v=model();v['child_shares_per_original_parent']='1.7';p=proof(w)
    with pytest.raises(ValueError):m.build_terms(v,w,child_security_id='211901312635613499',reference='test',source_proof=p)
    assert drop(m,'build_terms','DISTRIBUTION_V2_DECLARED_RATIO_AND_EXACT_EXISTING_PARENT_CASH_PROXY')(v,w,child_security_id='211901312635613499',reference='test',source_proof=p)['spin']['child_shares_per_parent']=='1.7'

def role_state():
    b=binding();return b,dict(wealth_core=dict(episodes={'7':dict(security_id=b['spin']['parent_security_id'],ticker='PPLI',current_shares=13,slot_id=7,entry_date='2021-04-13')},
        slots={'7':dict(occupied_by=b['spin']['parent_security_id'],reserved_for=None)},terminal_pending_terms={},terminal_pending_sessions={},unresolved_terminals={}),ledger=dict(receivables=[]))

@pytest.mark.parametrize('change',['parent_quantity','child_held','pending','reservation','claim','receivable'])
def test_actual_role_exactness_refuses_unqualified_financial_roles(change):
    b,state=role_state();pending=[]
    assert m.actual_role(state,pending,b)
    if change=='parent_quantity':state['wealth_core']['episodes']['7']['current_shares']=12
    elif change=='child_held':state['wealth_core']['episodes']['8']=dict(security_id=b['spin']['child_security_id'],current_shares=1)
    elif change=='pending':pending=[dict(security_id=b['spin']['parent_security_id'])]
    elif change=='reservation':state['wealth_core']['slots']['7']['reserved_for']=b['spin']['child_security_id']
    elif change=='claim':state['wealth_core']['terminal_pending_terms'][b['spin']['parent_security_id']]={}
    else:state['ledger']['receivables']=[dict(security_id=b['spin']['child_security_id'])]
    with pytest.raises(ValueError):m.actual_role(state,pending,b)

def test_role_guard_removal_falsifier():
    b,state=role_state();state['wealth_core']['episodes']['7']['current_shares']=12
    with pytest.raises(ValueError):m.actual_role(state,[],b)
    assert drop(m,'actual_role','DISTRIBUTION_V2_ACTUAL_EXACT_PARENT_ROLE_NO_CHILD_ORDER_RESERVATION_OR_CLAIM')(state,[],b)

def test_independent_exact_child_entitlement_sale_fraction_cost_and_no_extra_proxy_cash():
    b=binding();p=m.consideration(b,Fraction(13),10)
    assert p['child_entitlement']=='42211/2000' and p['child_whole']==21 and p['child_fraction']=='211/2000'
    assert Fraction(p['exact_total_inflow'])==Fraction('994.134175')
    assert Fraction(p['exact_whole_sale_cost'])==Fraction('.99015')
    assert p['child_whole_proceeds']==989.15985 and p['child_fractional_cash']==4.974325
    assert p['parent_units_unchanged']=='13' and p['suppressed_cash_proxy_is_additional_cash'] is False
    assert Fraction(p['exact_total_inflow'])!=Fraction('994.134175')+13*Fraction('84.55')

class LooseTerm(BaseModel):
    model_config=ConfigDict(extra='allow',strict=True)
    session:str;security_id:str
class SourceEvidence(BaseModel):
    reference:str;sha256:str|None;description:str
def original_repair_type():
    tree=ast.parse(raw('frozen-original-repair-source.py'));node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Repair')
    ns=dict(_Strict=BaseModel,Literal=Literal,Field=Field,PrivateAttr=PrivateAttr,model_validator=model_validator,
        Digest=Annotated[str,Field(pattern=r'^[0-9a-f]{64}$')],SourceEvidence=SourceEvidence,Suppression=LooseTerm,AddedTerm=LooseTerm)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<original-nonempty-ordinary-input-data-model>','exec'),ns)
    return ns['Repair']
def loaded():
    record=data('VCRA-unadopted-original-input-evidence.json');t=record['term'];Repair=original_repair_type()
    doc=dict(schema='terminal-repair/1',predecessor_checkpoint_sha256='f'*64,
        source_evidence=[dict(reference='genuine VCRA source fixture',sha256=record['catalog_sha256'],description='original cash fact')],
        suppress=[dict(session=t['native_session'],security_id=t['security_id'],term_sha256=t['native_term_sha256'])],add=[t['added']])
    obj=Repair.model_validate(doc);obj._file_sha256=m.sha(m.encoded(doc));obj._resume_session='2021-04-30';obj._document_sha256=m.digest(obj.model_dump(mode='json',by_alias=True))
    return obj

def test_original_nonempty_parser_guard_and_qualified_view_minimum_boundary():
    Repair=original_repair_type()
    with pytest.raises(ValueError,match='empty terminal repair'):Repair.model_validate(dict(schema='terminal-repair/1',predecessor_checkpoint_sha256='a'*64,
        source_evidence=[dict(reference='x',sha256='b'*64,description='x')],suppress=[],add=[]))
    obj=loaded();b=binding();p=proof();a=s.activation_descriptor(obj,b,p);view=s.qualified_loaded_view(obj,b,p,a)
    assert obj.earliest_affected_session=='2022-02-22' and view.earliest_affected_session=='2021-05-25'
    assert view.model_dump(mode='json',by_alias=True)==obj.model_dump(mode='json',by_alias=True)
    assert view.__pydantic_private__==obj.__pydantic_private__ and view.sha256==obj.sha256 and isinstance(view,type(obj))
    tree=ast.parse(raw('frozen-original-repair-source.py'));fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_loaded')
    ns=dict(Repair=type(obj),_digest=m.digest);exec(compile(ast.Module(body=[fn],type_ignores=[]),'<original-loaded-input-guard>','exec'),ns)
    assert ns['_loaded'](view) is None

@pytest.mark.parametrize('change',['source_data','consumed','descriptor','field','private'])
def test_loaded_view_requires_closed_source_and_preserves_every_commitment(change):
    obj=loaded();b=binding();p=proof();a=s.activation_descriptor(obj,b,p)
    if change=='source_data':
        p['independent_DATA_passed']=False
        with pytest.raises(ValueError):s.qualified_loaded_view(obj,b,p,a)
    elif change=='consumed':
        b['parent_cursor']=obj._resume_session='2021-05-25'
        with pytest.raises(ValueError):s.activation_descriptor(obj,b,p)
    elif change=='descriptor':
        a['earliest_affected_session']='2022-02-22'
        with pytest.raises(ValueError):s.qualified_loaded_view(obj,b,p,a)
    else:
        view=s.qualified_loaded_view(obj,b,p,a)
        if change=='field':view.add[0].session='2022-02-24'
        else:view._file_sha256='0'*64
        with pytest.raises(ValueError):_=view.earliest_affected_session

def test_qualified_view_boundary_guard_removal_falsifier():
    obj=loaded();b=binding();p=proof();b['parent_cursor']=obj._resume_session='2021-05-25'
    with pytest.raises(ValueError):s.activation_descriptor(obj,b,p)
    assert drop(s,'activation_descriptor','COMPOUND_V2_ORIGINAL_NONEMPTY_PARSED_REPAIR_AND_UNCONSUMED_MINIMUM_BOUNDARY')(obj,b,p)['earliest_affected_session']=='2021-05-25'

def test_actual_catalog_placeholder_is_not_selectable(tmp_path,monkeypatch):
    (tmp_path/s.CATALOG_FILE).write_bytes(raw('system-campaign-compound-input-v2-facts.json'))
    monkeypatch.setattr(s,'HERE',tmp_path);monkeypatch.setattr(s,'CATALOG_SHA','0'*64)
    assert data('system-campaign-compound-input-v2-facts.json')['records'][0]['source_proof'] is None
    with pytest.raises(ValueError,match='CLOSED_CATALOG_PIN_REQUIRED'):s.qualified_record()

def test_frozen_v1_and_original_financial_sources_remain_exact():
    assert m.sha(raw('system_campaign_financial_compound_runtime.py'))==s.V1_RUNTIME_SHA
    assert m.sha(raw('system_campaign_financial_compound_input.py'))=='f9e82f17196adf2612616aff929d04500cc45360eb8f2a3687c8078d668c4dce'
    d=data('VCRA-unadopted-original-input-evidence.json')
    assert d['unadopted_in_all_repairs'] is True and d['retained_certificate_rows']==384
    assert d['original_APHA_projection_source_sha256']=='2165e64a961bf0ee44c8f19ac2d6ec65059cc92a2b4154ad735685d29e120777'
    assert not [n for n in sys.modules if n.startswith(('stock_strategy_shared','sentinel','research.pooled_','numpy','pandas'))]


PURE_CONTAINER_SHA='532d8114df672562d8e7604babacb858a50263bd7d3c632632b18ce82a2739cd'
EXPECTED_PURE_NODES={'_session': {'ast_sha256': '4095d75a5f875e615eb5735d10a6763e5778e85a2e10e287603026d0c89c5ee9', 'source_sha256': 'bcb678b1e09394bbc7ed88614457766cbf243ff8d86f904b5275049f42dd3c65'}, '_digest': {'ast_sha256': '64c60de603f484b1a68da7797be91ec81b995917cf7177f652c49bd3be6d3e13', 'source_sha256': '210f362beba7c1b56130626b907ecf2d4bfc47ce9e11c933d0874c82bd6770ef'}, '_apply_spinoff_repair': {'ast_sha256': '9f862d4ff00a8506e76a98970902db65e4c2a4c4ff0585927fcdee0f125f2cca', 'source_sha256': '39b2fd76e400e9d54e165ce2670c1436006da086b81b3b0dc42997d98cdedacf'}, 'Repair': {'ast_sha256': 'bf9acea0da7d9a3057856666a5e7cdaecae2a591ec5c419fb89d636fac2afa65', 'source_sha256': '73595436c2ddaa26c0d9601c5102a9d8b0bbb40c5dbd4f353d75c66d07e70fab'}, '_loaded': {'ast_sha256': '4bd35fce7c49b5379863fa43bcdf2630f638e3153a70b6a58464d7e2889f86ba', 'source_sha256': '478d9541269a47d7d4cd122b0763ef67fcf502460f2e98dcf2a2ae1d146fe183'}}

def pure_repair_container():
    value=data('pure-original-nonempty-input-codec.json')
    assert value['schema']=='research.frozen-pure-nonempty-input-test-codec/1'
    assert value['original_module_sha256']==m.REPAIR_SHA
    assert value['no_financial_runtime_or_book_material'] is True
    assert set(value['functions'])==set(EXPECTED_PURE_NODES)
    for name,expected in EXPECTED_PURE_NODES.items():
        item=value['functions'][name]
        assert {k:item[k] for k in expected}==expected
        assert m.sha(item['source'].encode())==expected['source_sha256']
        node,=ast.parse(item['source']).body
        assert m.sha(ast.dump(node,include_attributes=False).encode())==expected['ast_sha256']
    raw='\n'.join(value['functions'][name]['source'] for name in ('_session','_digest','_apply_spinoff_repair','Repair','_loaded')).encode()
    assert m.sha(raw)==value['container_sha256']==PURE_CONTAINER_SHA
    return raw

@pytest.fixture(autouse=True)
def exact_pure_compiler_fixture(monkeypatch):
    import system_campaign_distribution_facts as compiler
    monkeypatch.setattr(compiler,'REPAIR_SHA',m.sha(pure_repair_container()))
