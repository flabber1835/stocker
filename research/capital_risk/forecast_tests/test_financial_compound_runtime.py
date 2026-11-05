"""Portable synthetic runtime/retention/oracle guards; no financial imports."""
import ast
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass,replace,make_dataclass
from fractions import Fraction
import importlib.abc
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


class Fence(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in ('stock_strategy_shared','sentinel','numpy','pandas') or fullname.startswith('research.pooled_'):
            raise AssertionError('FORBIDDEN_CANONICAL_IMPORT:'+fullname)


guard=Fence();sys.meta_path.insert(0,guard)
try:
    import system_campaign_financial_compound_runtime as module
finally:sys.meta_path.remove(guard)


@pytest.fixture(autouse=True)
def imports():
    fence=Fence();sys.meta_path.insert(0,fence)
    yield
    sys.meta_path.remove(fence)


def binding():
    return dict(spin=dict(session='2019-03-20',parent_security_id='P',parent_ticker='PT',child_security_id='C',child_ticker='CT',
        child_shares_per_parent='1/3',cash_in_lieu_price='39.85',source_row_id='source'),
        terminal=dict(session='2019-03-20',security_id='P',delivered_security_id='D',reference='disclosed research',
            cash_per_share=37.33255745678,exchange_ratio=0.005842221993,cash_in_lieu_price_per_delivered_share=110.31),
        parent_positions=[dict(slot_id=12,ticker='PT',quantity=34,entry_date='2018-12-28')],original_rows={'P':dict(raw_open='49.61')})


def snapshots():
    b=binding();proof=module.consideration(b,Fraction(34),10)
    before=dict(cash=1000.,episodes={'12':dict(security_id='P',current_shares=34,entry_split_adjusted_price=47.96,
        episode_peak_split_adjusted_close=50.83,source_lots=[])},slots={'12':dict(occupied_by='P',reserved_for=None)},
        terminal_pending_terms={},terminal_pending_sessions={},unresolved_terminals={})
    lb=dict(events=[],receivables=[]);after=deepcopy(before);after['cash']=before['cash']+proof['child_cash']
    scale=49.61/(49.61+float(Fraction('39.85')/3))
    after['episodes']['12']['entry_split_adjusted_price']*=scale
    after['episodes']['12']['episode_peak_split_adjusted_close']*=scale
    after['episodes']['12']['source_lots']=[dict(kind='SPINOFF_CHILD_LIQUIDATION',session='2019-03-20',source_row_id='source',
        parent_security_id='P',child_security_id='C',child_ticker='CT',child_shares_per_parent='1/3',child_open=39.85,reference_scale=scale)]
    events=[dict(event_type='SPINOFF_RECEIPT',security_id='C',session='2019-03-20',shares_delta=11,
        cash_before=1000.,cash_after=1000.,detail=dict(fractional_entitlement='1/3')),
        dict(event_type='SPINOFF_LIQUIDATION',security_id='C',session='2019-03-20',shares_delta=-11,
            cash_before=1000.,cash_delta=proof['child_cash'],cash_after=after['cash'],price=39.85,fees=11*39.85-437.91165)]
    la=dict(events=events,receivables=[])
    result=[dict(parent_security_id='P',child_security_id='C',whole_child_shares=11,fractional_child_shares='1/3',cash_proceeds=proof['child_cash'])]
    return b,before,after,lb,la,result,proof


def terminal_snapshots():
    b,before,spin_after,lb,la,result,p=snapshots();before=spin_after;lb=la;after=deepcopy(before)
    after['cash']=before['cash']+p['terminal_cash'];after['episodes']={};after['slots']['12']['occupied_by']=None
    event=dict(event_type='CONVERSION',security_id='P',shares_delta=-34,cash_before=before['cash'],cash_after=after['cash'],
        cash_delta=after['cash']-before['cash'],detail=dict(exact_fractional_entitlement=p['delivered_entitlement'],reference=b['terminal']['reference']))
    la=dict(events=lb['events']+[event],receivables=[])
    result=dict(applied=True,converted=False,cash_consideration=p['cash_leg'],cash_in_lieu=p['stock_cil'])
    return b,before,after,lb,la,result,p


def test_independent_rational_package_values_and_canonical_float_boundaries():
    b,before,after,lb,la,result,p=snapshots()
    assert p['child_entitlement']=='34/3' and p['child_whole']==11 and p['child_fraction']=='1/3'
    assert p['child_whole_proceeds']==437.91165
    assert p['delivered_entitlement']==str(Fraction('0.198635547762')) and p['delivered_whole']==0
    expected=Fraction('1269.30695353052')+Fraction('0.198635547762')*Fraction('110.31')+Fraction('437.91165')+Fraction('39.85')/3
    assert Fraction(p['exact_total_inflow'])==expected
    assert module.spin_postcondition(b,before,after,lb,la,result,10)==p
    b,before,after,lb,la,result,p=terminal_snapshots()
    assert module.terminal_postcondition(b,before,after,lb,la,result)==p


@pytest.mark.parametrize('which',range(10))
def test_actual_child_receipt_sale_fraction_fee_and_other_state_falsifiers(which):
    b,before,after,lb,la,result,p=snapshots()
    if which==0:la['events'][0]['shares_delta']=10
    elif which==1:la['events'][0]['detail']['fractional_entitlement']='0.3333'
    elif which==2:la['events'][1]['cash_delta']+=.01
    elif which==3:la['events'][1]['fees']=0.
    elif which==4:la['events'][1]['price']=38.
    elif which==5:after['cash']+=.01
    elif which==6:result[0]['whole_child_shares']=12
    elif which==7:after['episodes']['12']['current_shares']=33
    elif which==8:after['slots']['12']['occupied_by']='C'
    elif which==9:la['receivables']=[dict(security_id='D',amount=1)]
    with pytest.raises(ValueError):module.spin_postcondition(b,before,after,lb,la,result,10)


@pytest.mark.parametrize('which',range(8))
def test_actual_mixed_ledger_retirement_claim_and_delivery_falsifiers(which):
    b,before,after,lb,la,result,p=terminal_snapshots()
    if which==0:result['cash_consideration']+=.01
    elif which==1:result['cash_in_lieu']=0.
    elif which==2:la['events'][-1]['detail']['exact_fractional_entitlement']='0.1986'
    elif which==3:la['events'][-1]['detail']['reference']='changed model'
    elif which==4:after['episodes']={'12':dict(security_id='D',current_shares=1)}
    elif which==5:after['terminal_pending_terms']['P']={}
    elif which==6:after['cash']+=1
    elif which==7:la['events'][-1]['cash_delta']+=1
    with pytest.raises(ValueError):module.terminal_postcondition(b,before,after,lb,la,result)


def mutant(name,code):
    fn=next(n for n in ast.parse(Path(module.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name==name)
    before=len(fn.body);fn.body=[n for n in fn.body if not any(isinstance(v,ast.Constant) and v.value==code for v in ast.walk(n))]
    assert len(fn.body)==before-1
    scope=dict(vars(module));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-compound-runtime-guard>','exec'),scope)
    return scope[name]


def test_actual_child_cash_guard_removal_falsifier():
    b,before,after,lb,la,result,p=snapshots();la['events'][1]['cash_delta']+=.01
    with pytest.raises(ValueError):module.spin_postcondition(b,before,after,lb,la,result,10)
    fn=mutant('spin_postcondition','COMPOUND_EXACT_CANONICAL_CHILD_RECEIPT_SALE_FRACTION_CASH')
    assert fn(b,before,after,lb,la,result,10)==p


def test_actual_terminal_cash_guard_removal_falsifier():
    b,before,after,lb,la,result,p=terminal_snapshots();result['cash_in_lieu']=0.
    with pytest.raises(ValueError):module.terminal_postcondition(b,before,after,lb,la,result)
    fn=mutant('terminal_postcondition','COMPOUND_EXACT_CANONICAL_MIXED_CASH_FRACTION_LEDGER')
    assert fn(b,before,after,lb,la,result)==p


def configure(monkeypatch,tmp_path):
    monkeypatch.setattr(module,'HERE',tmp_path)
    source=b'pure closed source producer fixture\n';(tmp_path/module.SOURCE_V1).write_bytes(source)
    monkeypatch.setattr(module,'SOURCE_V1_SHA',module.sha(source))
    scope=dict(parent_outer_sha256='a'*64,parent_cursor='2019-02-28')
    proof=dict(independent_DATA_passed=True,independent_qualification_passed=True,independent_qualification_sha256='8'*64,
        run_id=1,artifact_id=2,head='e'*40,zip_sha256='1'*64,payload_sha256='2'*64,
        payload_digest='3'*64,producer_sha256='4'*64,independent_data_review_sha256='5'*64,scope_sha256=module.digest(scope),distribution_producer_sha256=module.SOURCE_V1_SHA)
    record=dict(arm='P06',parent_cursor='2019-02-28',parent_outer_sha256='a'*64,parent_inner_sha256='b'*64,
        parent_input_sha256='c'*64,parent_root_admission_sha256='d'*64,source_bindings_sha256='6'*64,
        status='CLOSED_SOURCE_DATA_QUALIFIED_INPUT',source_scope=scope,source_proof=proof)
    catalog=dict(schema='research.selected-compound-distribution-terminal/1',records=[record],canonical_financial_source_changed=False,production_contacted=False)
    raw=module.encoded(catalog);(tmp_path/module.CATALOG_FILE).write_bytes(raw);monkeypatch.setattr(module,'CATALOG_SHA',module.sha(raw))
    return catalog,record


def test_closed_catalog_and_all_proof_pins_required(monkeypatch,tmp_path):
    catalog,record=configure(monkeypatch,tmp_path);assert module.qualified_record()==record
    monkeypatch.setattr(module,'CATALOG_SHA','0'*64)
    with pytest.raises(ValueError,match='CATALOG_PIN_REQUIRED'):module.qualified_record()


@pytest.mark.parametrize('field,value', [('independent_DATA_passed',False),('payload_sha256',None),('independent_data_review_sha256','0'*64),
    ('producer_sha256',None),('distribution_producer_sha256','6'*64),('scope_sha256','7'*64),
    ('independent_qualification_passed',False),('independent_qualification_sha256',None)])
def test_missing_or_changed_closed_source_proof_refuses(monkeypatch,tmp_path,field,value):
    catalog,record=configure(monkeypatch,tmp_path);record['source_proof'][field]=value
    raw=module.encoded(catalog);(tmp_path/module.CATALOG_FILE).write_bytes(raw);monkeypatch.setattr(module,'CATALOG_SHA',module.sha(raw))
    with pytest.raises(ValueError):module.qualified_record()


def test_closed_source_admission_guard_removal_falsifier(monkeypatch,tmp_path):
    catalog,record=configure(monkeypatch,tmp_path);record['source_proof']['independent_DATA_passed']=False
    raw=module.encoded(catalog);(tmp_path/module.CATALOG_FILE).write_bytes(raw);monkeypatch.setattr(module,'CATALOG_SHA',module.sha(raw))
    with pytest.raises(ValueError):module.qualified_record()
    assert mutant('qualified_record','COMPOUND_CLOSED_SOURCE_DATA_ALL_PROVENANCE_PINS_REQUIRED')()==record


def activation_context(tmp_path):
    raw=b'activated ordinary input\n';path=tmp_path/'activation.json';path.write_bytes(raw)
    ctx=module.ProjectionContext.__new__(module.ProjectionContext);ctx.overlay=path;ctx.overlay_sha=module.sha(raw)
    ctx.payload=dict(original_parent=dict(cursor='2019-02-28',inner_sha256='b'*64));ctx.bound_objects=[];ctx.changed_packets=0
    ctx.original_load=lambda *a,**k:SimpleNamespace(source_evidence=[SimpleNamespace(reference=module.CATALOG_REF)],sha256=ctx.overlay_sha)
    ctx.original_apply=lambda packet,obj:packet
    ctx.projection=SimpleNamespace(descriptor={'selected':True},apply=lambda packet,activation:replace(packet,value=packet.value+1))
    return ctx,path


@dataclass(frozen=True)
class Packet:
    value:int=0


def test_exact_loader_object_activation_and_unrelated_loader_delegation(tmp_path):
    ctx,path=activation_context(tmp_path)
    obj=ctx.load(path,resume_session='2019-02-28',predecessor_checkpoint_sha256='b'*64)
    assert ctx.apply(Packet(),obj)==Packet(1)
    foreign=SimpleNamespace(source_evidence=[],sha256='c'*64)
    original=Packet();assert ctx.apply(original,foreign) is original
    forged=SimpleNamespace(source_evidence=obj.source_evidence,sha256=obj.sha256)
    with pytest.raises(ValueError,match='ACTUAL_QUALIFIED_LOADER_OBJECT'):ctx.apply(original,forged)


def test_wrong_activation_parent_or_file_refuses(tmp_path):
    ctx,path=activation_context(tmp_path)
    with pytest.raises(ValueError):ctx.load(path,resume_session='2019-03-20',predecessor_checkpoint_sha256='b'*64)
    with pytest.raises(ValueError):ctx.load(path,resume_session='2019-02-28',predecessor_checkpoint_sha256='c'*64)
    path.write_bytes(b'changed activation\n')
    with pytest.raises(ValueError):ctx.load(path,resume_session='2019-02-28',predecessor_checkpoint_sha256='b'*64)


def test_retention_requires_committed_repair_and_keeps_original_boundary(monkeypatch,tmp_path):
    repairs=tmp_path/'book/repairs';repairs.mkdir(parents=True)
    doc=dict(source_evidence=[dict(reference=module.CATALOG_REF)])
    raw=module.encoded(doc);name=module.sha(raw)+'.json';(repairs/name).write_bytes(raw)
    cp=dict(repairs=[dict(filename=name,sha256=module.sha(raw),resume_session='2019-02-28',predecessor_checkpoint_sha256='b'*64)],
        source_cursor='2020-01-31',base={'same':'generation'})
    payload=dict(base=cp['base'],original_parent=dict(cursor='2019-02-28',inner_sha256='b'*64))
    monkeypatch.setattr(module,'verify_payload',lambda root:(payload,b'payload'))
    (tmp_path/'source-bindings.json').write_bytes(b'own parameter binding')
    monkeypatch.setattr(module,'qualified_record',lambda:dict(source_bindings_sha256=module.sha(b'own parameter binding')))
    monkeypatch.setattr(module,'ProjectionContext',lambda *a,**k:(a,k))
    got=module.retained_activation(tmp_path,cp)
    assert got[1]['payload'][0]['original_parent']['cursor']=='2019-02-28'
    cp['repairs'][0]['resume_session']='2019-03-29'
    with pytest.raises(ValueError):module.retained_activation(tmp_path,cp)


def test_cannot_capture_or_prepare_finance_locally(monkeypatch,tmp_path):
    def denied():raise ValueError('HOSTED_REQUIRED')
    monkeypatch.setattr(module,'hosted',denied)
    with pytest.raises(ValueError,match='HOSTED_REQUIRED'):module.prepare({},tmp_path,'P06')
    with pytest.raises(ValueError,match='HOSTED_REQUIRED'):module.reconstruct_source({}, {})
    with pytest.raises(ValueError,match='HOSTED_REQUIRED'):module.ProjectionContext.__enter__(SimpleNamespace())
    assert not list(tmp_path.iterdir())


def source_observer(selected=True):
    b=binding();o=module.Observer('.',dict(binding=b));o.current={}
    prior=SimpleNamespace(wealth_core={'same':'original'},pending=[],ledger={},median5={'selected':['P'] if selected else []},
        feed={'series':{'P':{'signal_basis_anchor':('2019-03-19',49.61,49.61)}}},last_processed_session='2019-03-19')
    term=make_dataclass('SyntheticQualifiedTerm',[(k,object) for k in b['terminal']])(**b['terminal'])
    published=SimpleNamespace(session='2019-03-20',terminal_events=(term,),bars=(SimpleNamespace(security_id='D',raw_close=109.99),))
    expected=float(Fraction('37.332557456780')+Fraction('0.005842221993')*Fraction('109.99'))
    calls=[]
    def original(*,prior,published):calls.append((prior,published));return {'P':expected} if selected else {}
    o.source_original=original
    def kernel(env,published):return o.source_values(prior=env,published=published)
    o.kernel_code=kernel.__code__
    return o,prior,published,kernel,expected,calls


@pytest.mark.parametrize('selected',[True,False])
def test_actual_original_notional_delegation_for_selected_and_unselected_parent(selected):
    o,prior,published,kernel,expected,calls=source_observer(selected)
    assert kernel(prior,published)==({'P':expected} if selected else {})
    assert calls==[(prior,published)] and o.current['source_notional']['original_delegated'] is True
    assert o.current['source_notional']['returned_notional']==(expected if selected else None)


def test_actual_notional_wrong_value_or_mutating_source_refuses():
    o,prior,published,kernel,expected,calls=source_observer()
    o.source_original=lambda **kwargs:{'P':expected+1}
    with pytest.raises(ValueError,match='ORIGINAL_CONTROLLER_MIXED_NOTIONAL'):kernel(prior,published)
    def mutating(*,prior,published):prior.wealth_core['mutated']=True;return {'P':expected}
    o.source_original=mutating
    with pytest.raises(ValueError,match='CONTROLLER_NOTIONAL_READONLY'):kernel(prior,published)


def test_actual_notional_guard_removal_falsifier():
    o,prior,published,kernel,expected,calls=source_observer();o.source_original=lambda **kwargs:{'P':expected+1}
    with pytest.raises(ValueError):kernel(prior,published)
    cls=next(n for n in ast.parse(Path(module.__file__).read_bytes()).body if isinstance(n,ast.ClassDef) and n.name=='Observer')
    fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='source_values')
    fn.body=[n for n in fn.body if not any(isinstance(v,ast.Constant) and v.value=='COMPOUND_ACTUAL_ORIGINAL_CONTROLLER_MIXED_NOTIONAL' for v in ast.walk(n))]
    scope=dict(vars(module));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-actual-controller-notional-guard>','exec'),scope)
    o.source_values=scope['source_values'].__get__(o,type(o))
    assert kernel(prior,published)=={'P':expected+1}


def test_reference_rebase_guard_removal_falsifier():
    b,before,after,lb,la,result,p=snapshots();after['episodes']['12']['episode_peak_split_adjusted_close']+=1
    with pytest.raises(ValueError,match='PARENT_REFERENCE_REBASE'):module.spin_postcondition(b,before,after,lb,la,result,10)
    fn=next(n for n in ast.parse(Path(module.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='spin_postcondition')
    loop=next(n for n in fn.body if isinstance(n,ast.For))
    loop.body=[n for n in loop.body if not any(isinstance(v,ast.Constant) and v.value=='COMPOUND_EXACT_ORIGINAL_CANONICAL_PARENT_REFERENCE_REBASE_AND_LOT' for v in ast.walk(n))]
    scope=dict(vars(module));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-parent-reference-scale-guard>','exec'),scope)
    assert scope['spin_postcondition'](b,before,after,lb,la,result,10)==p
