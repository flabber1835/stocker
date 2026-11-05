"""Exact frozen pure-codec tests on synthetic packets only; no canonical imports."""
import ast
from copy import deepcopy
from dataclasses import asdict,dataclass,replace
from datetime import date
from decimal import Decimal
from fractions import Fraction
import hashlib,json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import pytest
import system_campaign_financial_compound_input as module
from forecast_tests.test_financial_distribution_source import fixture,Fence
import system_campaign_financial_distribution_source as source

FIXTURE=Path(__file__).parent/'fixtures/pure-distribution-input-functions.json'
CONTAINER_SHA='c75ab4890f26af2186117918588dcced4302ae7ca1143a2dac7f0cd721e000e0'
ORIGINAL_MODULE_SHAS={'repair': '1112f91ab01c6b633fd6e7b2c089aa02367d2fc7fbc152a654da6620d753b152', 'spinoffs': '3ee01881e21a984c80cbdae1e2323fb42dc87f69dfe19f613b7141554e7ffeb2'}
EXPECTED_FUNCTIONS={'_session': {'origin': 'repair', 'original_module_sha256': '1112f91ab01c6b633fd6e7b2c089aa02367d2fc7fbc152a654da6620d753b152', 'source_sha256': 'bcb678b1e09394bbc7ed88614457766cbf243ff8d86f904b5275049f42dd3c65', 'ast_sha256': '4095d75a5f875e615eb5735d10a6763e5778e85a2e10e287603026d0c89c5ee9'}, '_digest': {'origin': 'repair', 'original_module_sha256': '1112f91ab01c6b633fd6e7b2c089aa02367d2fc7fbc152a654da6620d753b152', 'source_sha256': '210f362beba7c1b56130626b907ecf2d4bfc47ce9e11c933d0874c82bd6770ef', 'ast_sha256': '64c60de603f484b1a68da7797be91ec81b995917cf7177f652c49bd3be6d3e13'}, '_apply_spinoff_repair': {'origin': 'repair', 'original_module_sha256': '1112f91ab01c6b633fd6e7b2c089aa02367d2fc7fbc152a654da6620d753b152', 'source_sha256': '39b2fd76e400e9d54e165ce2670c1436006da086b81b3b0dc42997d98cdedacf', 'ast_sha256': '9f862d4ff00a8506e76a98970902db65e4c2a4c4ff0585927fcdee0f125f2cca'}, '_positive_fraction': {'origin': 'spinoffs', 'original_module_sha256': '3ee01881e21a984c80cbdae1e2323fb42dc87f69dfe19f613b7141554e7ffeb2', 'source_sha256': '7afd8843983b2796a87f433dde38df70f10a22ad621afcf2e28c628c0fa53872', 'ast_sha256': 'bf1f7b5adfb5e3b1ba42a2e789f6be95091ff3f62295f885e8d0c8dcfdcd23a3'}}

def pure_fixture():
    value=json.loads(FIXTURE.read_bytes())
    assert value['schema']=='research.frozen-pure-distribution-input-test-functions/1'
    assert value['no_financial_runtime_or_book_material'] is True
    assert set(value['functions'])==set(EXPECTED_FUNCTIONS)
    for label,expected in ORIGINAL_MODULE_SHAS.items():
        assert value['origins'][label]['module_sha256']==expected
    for name,expected in EXPECTED_FUNCTIONS.items():
        item=value['functions'][name]
        assert {k:item[k] for k in expected}==expected
        assert source.sha(item['source'].encode())==expected['source_sha256']
        tree=ast.parse(item['source']);fn,=tree.body
        assert isinstance(fn,ast.FunctionDef) and fn.name==name
        assert source.sha(ast.dump(fn,include_attributes=False).encode())==expected['ast_sha256']
    return value

def repair_container():
    value=pure_fixture()
    raw='\n'.join(value['functions'][n]['source'] for n in ('_session','_digest','_apply_spinoff_repair')).encode()
    assert source.sha(raw)==value['repair_container_sha256']==CONTAINER_SHA
    return raw


@pytest.fixture(autouse=True)
def fence(monkeypatch):
    import system_campaign_distribution_facts as original_compiler
    # Only the synthetic container hash changes. Its function ASTs and the
    # production compiler's exact five identity-literal sites remain enforced.
    monkeypatch.setattr(original_compiler,'REPAIR_SHA',source.sha(repair_container()))
    guard=Fence();sys.meta_path.insert(0,guard)
    yield
    sys.meta_path.remove(guard)


@dataclass(frozen=True)
class Bar:
    session:str
    security_id:str
    ticker:str
    raw_open:float
    dividend_per_share:float=0.
    tradeable:bool=True


@dataclass(frozen=True)
class Spin:
    session:str
    parent_ticker:str
    parent_security_id:str
    child_ticker:str|None
    child_security_id:str|None
    source_row_id:str
    value_evidence:str|None
    child_shares_per_parent:str|None=None
    child_price:str|None=None
    cash_in_lieu_price:str|None=None
    policy:str='REQUIRE_REVIEWED_CHILD_OWNERSHIP'


@dataclass(frozen=True)
class Term:
    session:str
    security_id:str
    kind:str
    reference:str
    cash_per_share:float|None=None
    delivered_security_id:str|None=None
    delivered_ticker:str|None=None
    delivered_issuer_id:str|None=None
    exchange_ratio:float|None=None
    cash_in_lieu_price_per_delivered_share:float|None=None
    entitlement_aggregation:str='HOLDER'


@dataclass(frozen=True)
class Packet:
    day:str
    bars:tuple=()
    terminal:tuple=()
    spins:tuple=()


def model():
    return dict(schema=module.MODEL,actual_distribution_session='2019-03-19',actual_merger_session='2019-03-20',
        recognition_session='2019-03-20',cash_election_assumed=True,actual_election_claimed=False,
        original_carried_unit='PRE_DISTRIBUTION_PARENT_SHARE',remaining_parent_fraction='0.736817',
        cash_per_remaining_parent_share='50.667340',delivered_ratio_per_remaining_parent_share='0.007929',
        cash_per_original_carried_share='37.332557456780',delivered_ratio_per_original_carried_share='0.005842221993',
        distributed_child_ratio_per_original_carried_share='1/3',opening_availability_assumed=True,actual_settlement_claimed=False,
        fractional_cash_proxy='FROZEN_DELIVERED_RAW_OPEN_NOT_ACTUAL_SETTLEMENT_RATE',settlement_fees='IGNORED_FOR_RESEARCH',
        continuing_delivered_whole_shares_supported=False)


def binding():
    args,identity=fixture();data=source.material(*args);witness=source.payload(identity,args[0],data,'d'*64)
    return module.build_terms(model(),witness,child_security_id='C',delivered_security_id='D',reference='declared research fixture')


def namespace():
    raw=repair_container();assert source.sha(raw)==CONTAINER_SHA
    funcs=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name in ('_session','_digest')]
    assert len(funcs)==2
    scope=dict(date=date,hashlib=hashlib,json=json,asdict=asdict,replace=replace,Decimal=Decimal)
    exec(compile(ast.fix_missing_locations(ast.Module(body=funcs,type_ignores=[])),'<frozen-pure-input-helpers>','exec'),scope)
    return raw,scope


def projection():
    b=binding();raw,scope=namespace()
    parent=Bar('2019-03-20','P','PT',49.61);child=Bar('2019-03-20','C','CT',39.85)
    p=module.EventSessionProjection(b,parent_bar=parent,child_bar=child,source_raw=raw,source_namespace=scope,spin_factory=Spin)
    return p,parent,child


def packet(p,parent,child):
    other=Spin('2019-03-20','OTHER','O',None,None,'other-row','other source')
    return Packet('2019-03-20',(parent,child), (Term(**p.binding['terminal']),),(other,))


def test_exact_unit_formula_and_literal_numbers():
    b=binding()
    assert b['spin']['child_shares_per_parent']=='1/3'
    assert Fraction(str(b['terminal']['cash_per_share']))==Fraction('37.332557456780')
    assert Fraction(str(b['terminal']['exchange_ratio']))==Fraction('0.005842221993')
    assert b['terminal']['delivered_issuer_id']=='SEC_UNKNOWN:D'
    assert Fraction(34)*Fraction('0.005842221993')==Fraction('0.198635547762')
    assert Fraction(34,3)==11+Fraction(1,3)


def test_original_positive_fraction_accepts_exact_one_third():
    raw=pure_fixture()['functions']['_positive_fraction']['source'].encode()
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='_positive_fraction']
    scope=dict(Fraction=Fraction,SpinoffTermsRequired=ValueError)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<frozen-rational-source-validator>','exec'),scope)
    assert scope['_positive_fraction']('1/3','child ratio')==Fraction(1,3)


def test_original_codec_projects_only_exact_event_and_keeps_every_bar_terminal_and_other_spin():
    p,parent,child=projection();original=packet(p,parent,child);before=source.digest(asdict(original))
    changed=p.apply(original,deepcopy(p.descriptor))
    assert source.digest(asdict(original))==before
    assert changed.bars==original.bars and changed.terminal==original.terminal
    assert changed.spins==original.spins+(p.added,)
    native_packet=Packet('2019-03-21',(),(),(p.original,replace(original.spins[0],session='2019-03-21')))
    cleared=p.apply(native_packet,p.descriptor)
    assert cleared.spins==native_packet.spins[1:]
    for day in ('2019-02-27','2019-02-28','2019-03-19','2019-03-22','2026-07-31'):
        untouched=Packet(day,(),(),());assert p.apply(untouched,p.descriptor) is untouched


@pytest.mark.parametrize('change',range(10))
def test_projection_causal_source_date_quote_and_activation_falsifiers(change):
    p,parent,child=projection();original=packet(p,parent,child);activation=deepcopy(p.descriptor)
    if change==0: activation['parent_outer_sha256']='b'*64
    elif change==1: activation['recognition_session']='2019-03-21'
    elif change==2: original=replace(original,bars=(replace(parent,raw_open=49.62),child))
    elif change==3: original=replace(original,bars=(parent,replace(child,ticker='FOXA')))
    elif change==4: original=replace(original,terminal=())
    elif change==5: original=replace(original,terminal=(Term(**p.binding['original_terminal']),))
    elif change==6: original=replace(original,spins=original.spins+(p.projected,))
    elif change==7: original=Packet('2019-03-21',(),(),(p.original,p.original))
    elif change==8: original=Packet('2019-03-22',(),(),(replace(p.original,session='2019-03-22'),))
    elif change==9: p.local.cash_proxy_per_parent='1.0'
    with pytest.raises(ValueError):p.apply(original,activation)


@pytest.mark.parametrize('key,value', [('remaining_parent_fraction','1'),('cash_per_original_carried_share','50.667340'),
    ('delivered_ratio_per_original_carried_share','0.007929'),('recognition_session','2019-03-21'),('actual_election_claimed',True),
    ('continuing_delivered_whole_shares_supported',True)])
def test_wrong_unit_timing_or_unsupported_economic_authority_refuses(key,value):
    value0=model();value0[key]=value
    with pytest.raises(ValueError):module.validate_model(value0)


def role():
    return dict(wealth_core=dict(episodes={'12':dict(slot_id=12,ticker='PT',security_id='P',current_shares=34,entry_date='2018-12-28')},
        slots={'12':dict(occupied_by='P',reserved_for=None)},terminal_pending_terms={},terminal_pending_sessions={},unresolved_terminals={}),
        ledger=dict(receivables=[]))


@pytest.mark.parametrize('which',range(6))
def test_actual_role_guards(which):
    b=binding();state=role();pending=[]
    assert module.actual_role(state,pending,b)
    if which==0:state['wealth_core']['episodes']['12']['current_shares']=33
    elif which==1:state['wealth_core']['episodes']['1']=dict(slot_id=1,ticker='CT',security_id='C',current_shares=1,entry_date='2018-12-01')
    elif which==2:pending=[dict(delivery=dict(security_id='D'))]
    elif which==3:state['wealth_core']['slots']['12']['reserved_for']='C'
    elif which==4:state['wealth_core']['terminal_pending_terms']['P']={}
    elif which==5:state['ledger']['receivables']=[dict(security_id='D',amount=1)]
    with pytest.raises(ValueError):module.actual_role(state,pending,b)


def test_unit_guard_removal_falsifier():
    from forecast_tests.test_financial_distribution_source import without_guard
    fn=next(n for n in ast.parse(Path(module.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='validate_model')
    fn.body=[n for n in fn.body if not any(isinstance(v,ast.Constant) and v.value=='COMPOUND_EXACT_ORIGINAL_UNIT_CONSIDERATION' for v in ast.walk(n))]
    scope=dict(vars(module));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-original-unit-guard>','exec'),scope)
    wrong=model();wrong['delivered_ratio_per_original_carried_share']='0.007929'
    with pytest.raises(ValueError):module.validate_model(wrong)
    assert scope['validate_model'](wrong).delivered_ratio_per_original_carried_share=='0.007929'


def test_no_continuing_whole_dis_guard_removal_falsifier():
    args,identity=fixture();args[-1]['P'][0]['quantity']=200
    args[0]['terms'][0]['parent_positions'][0]['quantity']=200
    args[0]['additional_rows'][0]['parent_positions'][0]['quantity']=200
    witness=source.payload(identity,args[0],source.material(*args),'d'*64)
    with pytest.raises(ValueError,match='CONTINUING_DELIVERED'):module.build_terms(model(),witness,child_security_id='C',delivered_security_id='D',reference='test')
    fn=next(n for n in ast.parse(Path(module.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='build_terms')
    fn.body=[n for n in fn.body if not any(isinstance(v,ast.Constant) and v.value=='COMPOUND_NO_UNQUALIFIED_CONTINUING_DELIVERED_EPISODE' for v in ast.walk(n))]
    scope=dict(vars(module));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-continuing-episode-refusal>','exec'),scope)
    assert scope['build_terms'](model(),witness,child_security_id='C',delivered_security_id='D',reference='test')['parent_positions'][0]['quantity']==200
