"""Detached final-event packets and endpoint falsifiers; no financial replay."""
import ast
from dataclasses import make_dataclass, replace
from enum import Enum
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

CAP=Path(__file__).resolve().parents[1];sys.path.insert(0,str(CAP))
import p01_iac_namespace_continue as m

class Kind(str,Enum):
    CASH_MERGER='CASH_MERGER'
    CONVERSION='CONVERSION'

def state():return dict(wealth_core=dict(episodes={},slots={}),pending=[],ledger=dict(events=[],receivables=[]))

def packet():
    raw=(CAP/m.FINAL_INPUT).read_bytes();doc=m.FinalStockInput.model_validate(json.loads(raw))
    c=m.FinalStockCodec.__new__(m.FinalStockCodec);c.expected_raw=raw;c.document=doc
    c.origin=dict(source_cursor='2026-07-30');c.objects=[];c.applied=[];c.zero_value_checks=[]
    loaded=c.load(CAP/m.FINAL_INPUT,resume_session='2026-07-30',predecessor_checkpoint_sha256=doc.predecessor_checkpoint_sha256)
    native=dict(session=m.END,security_id=m.ORLA,kind='CASH_MERGER',cash_per_share=None,delivered_security_id=None,
        delivered_ticker=None,delivered_issuer_id=None,exchange_ratio=None,cash_in_lieu_price_per_delivered_share=None,
        reference='actions/acquisitionby deal_value_musd=3265.6',entitlement_aggregation='HOLDER')
    assert m.digest(native)==doc.native_term_sha256
    T=make_dataclass('Terminal',[(k,object) for k in native],frozen=True)
    P=make_dataclass('Packet',[('day',str),('terminal',tuple),('spins',tuple),('bars',tuple)],frozen=True)
    return c,loaded,P(m.END,(T(**dict(native,kind=Kind.CASH_MERGER)),),(),(object(),))

def test_stock_plus_nominal_cash_preserves_native_enum_and_other_fields():
    c,d,p=packet();other=replace(p.terminal[0],security_id='other');p=replace(p,terminal=(*p.terminal,other))
    result=c.apply(p,d);t=result.terminal[0]
    assert (t.kind.value,t.delivered_security_id,t.delivered_ticker,t.exchange_ratio,t.cash_per_share)==('CONVERSION',m.EQX,'EQX','1.00',0.0001)
    assert type(t.kind) is Kind and t.cash_in_lieu_price_per_delivered_share is None
    assert result.bars is p.bars and result.spins is p.spins and result.terminal[1] is other
    assert c.apply(p,d)==result and len(c.applied)==1
    with pytest.raises(ValueError,match='NATIVE_TERMINAL_PREIMAGE'):c.apply(result,d)

@pytest.mark.parametrize('role',['held','pending','slot','receivable','history','claim'])
def test_orla_ownership_or_claim_is_not_supported(role):
    s=state();record=dict(security_id=m.ORLA)
    if role=='held':s['wealth_core']['episodes']['1']=record
    elif role=='pending':s['pending'].append(record)
    elif role=='slot':s['wealth_core']['slots']['1']=record
    elif role=='receivable':s['ledger']['receivables'].append(record)
    elif role=='history':s['ledger']['events'].append(record)
    else:s['wealth_core']['unresolved_terminals']={m.ORLA:record}
    with pytest.raises(ValueError,match='ORLA_'):m.unheld_final_scope(s)

def test_actual_use_cannot_add_cash_or_shares():
    c,d,p=packet();c.apply(p,d);s=SimpleNamespace(**state());start=c.before(s,m.END)
    c.after(s,m.END,start);assert c.zero_value_checks==[dict(session=m.END,no_source_financial_value_added=True)]
    s.ledger['events'].append(dict(security_id=m.ORLA,cash_delta=0.0001,shares_delta=0))
    with pytest.raises(ValueError,match='CANNOT_ADD_PORTFOLIO'):c.after(s,m.END,start)

def test_zero_value_guard_removal_falsifier():
    c,d,p=packet();c.apply(p,d);s=SimpleNamespace(**state());start=c.before(s,m.END)
    s.ledger['events'].append(dict(security_id=m.ORLA,cash_delta=0.0001,shares_delta=0))
    with pytest.raises(ValueError):c.after(s,m.END,start)
    owner,=[n for n in ast.parse(Path(m.__file__).read_bytes()).body if isinstance(n,ast.ClassDef) and n.name=='FinalStockCodec']
    fn,=[n for n in owner.body if isinstance(n,ast.FunctionDef) and n.name=='after']
    fn.body=[n for n in fn.body if not (isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and len(n.value.args)==2
        and isinstance(n.value.args[1],ast.Constant) and n.value.args[1].value=='ORLA_CANNOT_ADD_PORTFOLIO_CASH_OR_SHARES')]
    scope=dict(vars(m));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<zero-value-guard-removed>','exec'),scope)
    scope['after'](c,s,m.END,start)

@pytest.mark.parametrize('change',['native','delivery','spin','unregistered'])
def test_conflicting_native_event_or_unregistered_input_refuses(change):
    c,d,p=packet()
    if change=='native':p=replace(p,terminal=(replace(p.terminal[0],reference='changed'),))
    elif change=='delivery':p=replace(p,terminal=(*p.terminal,replace(p.terminal[0],security_id='other',delivered_security_id=m.ORLA)))
    elif change=='spin':p=replace(p,spins=({'child_security_id':m.ORLA},))
    else:c.objects=[]
    with pytest.raises(ValueError,match='ORLA_'):c.apply(p,d)

@pytest.mark.parametrize('change',['cash','ratio','parent','held','native'])
def test_literal_input_rejects_altered_terms_or_authority(change):
    d=json.loads((CAP/m.FINAL_INPUT).read_bytes())
    key,value={'cash':('cash_per_share',0),'ratio':('exchange_ratio','0'),'parent':('parent_outer_sha256','0'*64),
        'held':('held_settlement_supported',True),'native':('native_term_sha256','0'*64)}[change]
    d[key]=value
    with pytest.raises(ValueError):m.FinalStockInput.model_validate(d)

def endpoint():
    return json.loads((CAP/m.SPEC).read_bytes()),m.expected_request()

def test_only_final_endpoint_uses_one_new_qualification_session():
    s,r=endpoint();assert m.event_qualification_count(s,r)==1
    assert m.event_qualification_count({},dict(new_input_file=m.STOCK_INPUT))==2

def test_exact_current_final_request_and_qualification_gate():
    s,r=endpoint()
    assert (r['original_sessions'],r['remaining_sessions'],r['original_inputs'],r['successor_inputs'])==(2155,1,16,17)
    assert r['new_input_file']==m.FINAL_INPUT and r['new_event_qualification_required']
    proof=dict(passed=True,parent_sha256=s['outer_sha256'],old_qualification_reexecuted=False,qualification_state_adopted=False,
        components=[{}],final_stock_input_sha256=r['new_input_sha256'],final_stock_applications=[{}],
        final_stock_zero_value_checks=[dict(session=m.END,no_source_financial_value_added=True)])
    m.validate_event_qualification(proof,s,r)
    for key,value in [('components',[{},{}]),('final_stock_input_sha256','wrong'),('final_stock_zero_value_checks',[])]:
        with pytest.raises(ValueError):m.validate_event_qualification({**proof,key:value},s,r)

@pytest.mark.parametrize('field,value',[('completed',2154),('selected_session','2026-07-29'),('next_session','2026-07-30'),('root_admission_sha256','0'*64)])
def test_one_session_qualification_refuses_other_predecessors(field,value):
    s,r=endpoint();s[field]=value
    with pytest.raises(ValueError,match='ONLY_EXACT_ADMITTED_ENDPOINT'):m.event_qualification_count(s,r)

def test_endpoint_guard_removal_falsifier():
    s,r=endpoint();s['completed']=2154
    with pytest.raises(ValueError):m.event_qualification_count(s,r)
    fn,=[n for n in ast.parse(Path(m.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='event_qualification_count']
    fn.body=[n for n in fn.body if not (isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=='need')]
    scope=dict(vars(m));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<endpoint-guard-removed>','exec'),scope)
    assert scope['event_qualification_count'](s,r)==1
