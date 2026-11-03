"""Detached packets and existing codec lifecycle; no canonical replay."""
import ast
from copy import deepcopy
from dataclasses import make_dataclass,replace
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
CAP=Path(__file__).resolve().parents[1];sys.path.insert(0,str(CAP))
import p01_iac_namespace_continue as m

def state():return dict(wealth_core=dict(episodes={},slots={}),pending=[],ledger=dict(events=[],receivables=[]))
def packet_codec():
    raw=(CAP/m.STOCK_INPUT).read_bytes();doc=m.UnheldStockInput.model_validate(json.loads(raw))
    c=m.UnheldStockCodec.__new__(m.UnheldStockCodec);c.expected_raw=raw;c.document=doc
    c.origin=dict(source_cursor='2026-05-27');c.objects=[];c.applied=[];c.zero_value_checks=[]
    d=c.load(CAP/m.STOCK_INPUT,resume_session='2026-05-27',predecessor_checkpoint_sha256=doc.predecessor_checkpoint_sha256)
    native=dict(session='2026-05-28',security_id=m.AMWD,kind='CASH_MERGER',cash_per_share=None,
        delivered_security_id=None,delivered_ticker=None,delivered_issuer_id=None,exchange_ratio=None,
        cash_in_lieu_price_per_delivered_share=None,reference='actions/acquisitionby deal_value_musd=700.7',entitlement_aggregation='HOLDER')
    assert m.digest(native)==doc.native_term_sha256
    T=make_dataclass('Terminal',[(k,object) for k in native],frozen=True)
    P=make_dataclass('Packet',[('day',str),('terminal',tuple),('spins',tuple),('bars',tuple)],frozen=True)
    return c,d,P('2026-05-28',(T(**native),),(),(object(),))

def test_exact_stock_terms_and_unrelated_packet_fields():
    c,d,p=packet_codec();other=replace(p.terminal[0],security_id='other');p=replace(p,terminal=(*p.terminal,other))
    new=c.apply(p,d);term=new.terminal[0]
    assert (term.kind,term.delivered_security_id,term.delivered_ticker,term.delivered_issuer_id,term.exchange_ratio)==('CONVERSION',m.MBC,'MBC','SID:'+m.MBC,'5.150')
    assert term.cash_per_share is term.cash_in_lieu_price_per_delivered_share is None
    assert term.entitlement_aggregation=='HOLDER' and new.terminal[1] is other and new.bars is p.bars and new.spins is p.spins
    assert c.apply(p,d)==new and len(c.applied)==1
    with pytest.raises(ValueError,match='NATIVE_TERMINAL_PREIMAGE'):c.apply(new,d)

@pytest.mark.parametrize('wrong',['native','delivery','spin','unregistered'])
def test_wrong_native_and_conflicting_action_refuse(wrong):
    c,d,p=packet_codec()
    if wrong=='native':p=replace(p,terminal=(replace(p.terminal[0],reference='changed'),))
    elif wrong=='delivery':p=replace(p,terminal=(*p.terminal,replace(p.terminal[0],security_id='other',delivered_security_id=m.AMWD)))
    elif wrong=='spin':p=replace(p,spins=({'child_security_id':m.AMWD},))
    else:c.objects=[]
    with pytest.raises(ValueError,match='AMWD_'):c.apply(p,d)

@pytest.mark.parametrize('role',['held','pending','slot','receivable','history','claim'])
def test_every_unsupported_ownership_role_refuses(role):
    s=state();record={'security_id':m.AMWD}
    if role=='held':s['wealth_core']['episodes']['1']=record
    elif role=='pending':s['pending'].append(record)
    elif role=='slot':s['wealth_core']['slots']['1']={'reserved_for':m.AMWD}
    elif role=='receivable':s['ledger']['receivables'].append(record)
    elif role=='history':s['ledger']['events'].append({'detail':{'delivered_security_id':m.AMWD}})
    else:s['wealth_core']['terminal_pending_terms']={m.AMWD:{}}
    with pytest.raises(ValueError,match='AMWD_'):m.unheld_stock_scope(s)

def test_removed_history_guard_accepts_the_same_hostile_state():
    s=state();s['ledger']['events'].append({'security_id':m.AMWD})
    with pytest.raises(ValueError,match='HISTORICAL'):m.unheld_stock_scope(s)
    fn,=[n for n in ast.parse(Path(m.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='unheld_stock_scope']
    fn.body=[n for n in fn.body if not (isinstance(n,ast.If) and ast.unparse(n.test)=='history')]
    scope=dict(vars(m));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<AMWD-history-guard-removed>','exec'),scope)
    assert scope['unheld_stock_scope'](s) is None

@pytest.mark.parametrize('field',['cash_delta','shares_delta'])
def test_no_source_value_can_be_created(field):
    c,d,p=packet_codec();s=SimpleNamespace(**state());c.apply(p,d);n=c.before(s,p.day)
    event=dict(security_id=m.AMWD,cash_delta=0,shares_delta=0);event[field]=1;s.ledger['events'].append(event)
    with pytest.raises(ValueError,match='CANNOT_ADD_PORTFOLIO'):c.after(s,p.day,n)

def test_synthetic_load_apply_and_zero_value_lifecycle():
    c,d,p=packet_codec();s=SimpleNamespace(**state());c.apply(p,d);before=deepcopy(s.__dict__)
    n=c.before(s,p.day);c.after(s,p.day,n)
    assert s.__dict__==before and c.zero_value_checks==[dict(session=p.day,no_source_financial_value_added=True)]
    assert c.apply(replace(p,day='2026-05-29'),d).day=='2026-05-29'
    with pytest.raises(ValueError,match='FUTURE_INPUT'):c.load(CAP/m.STOCK_INPUT,resume_session='2026-05-26',predecessor_checkpoint_sha256=d.predecessor_checkpoint_sha256)

@pytest.mark.parametrize('field,value',[('exchange_ratio','5.15'),('delivered_security_id','wrong'),('fractional_cash_price_known',True),('held_settlement_supported',True),('native_term_sha256','a'*64)])
def test_changed_economics_or_claimed_capabilities_refuse(field,value):
    raw=json.loads((CAP/m.STOCK_INPUT).read_bytes())
    with pytest.raises(ValueError):m.UnheldStockInput.model_validate({**raw,field:value})

def test_explicit_current_request_and_new_event_gate():
    r=m.expected_request();spec=m.read(CAP/m.SPEC)
    assert (r['original_sessions'],r['remaining_sessions'],r['original_inputs'],r['successor_inputs'])==(2111,45,15,16)
    assert r['new_input_file']==m.STOCK_INPUT and r['new_event_qualification_required']
    proof=dict(passed=True,parent_sha256=spec['outer_sha256'],old_qualification_reexecuted=False,qualification_state_adopted=False,
        components=[{},{}],unheld_stock_input_sha256=r['new_input_sha256'],unheld_stock_applications=[{}],
        unheld_stock_zero_value_checks=[dict(session='2026-05-28',no_source_financial_value_added=True)])
    m.validate_event_qualification(proof,spec,r)
    for k,v in [('parent_sha256','wrong'),('unheld_stock_input_sha256','wrong'),('unheld_stock_zero_value_checks',[])]:
        with pytest.raises(ValueError):m.validate_event_qualification({**proof,k:v},spec,r)

def test_missing_origin_refuses_before_restore(tmp_path):
    with pytest.raises(ValueError,match='ADMITTED_ORIGIN'):m.UnheldStockCodec(tmp_path,{'sha256':'wrong'})
