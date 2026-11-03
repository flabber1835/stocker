"""Source-exit input, detached packet and metadata tests; no financial runtime."""
import ast
from copy import deepcopy
from dataclasses import make_dataclass, replace
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

CAP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(CAP))
import p01_iac_namespace_continue as m


def state():
    return dict(wealth_core=dict(episodes={},slots={}),pending=[],ledger=dict(events=[],receivables=[]))


def codec_packet():
    raw=(CAP/m.EXIT_INPUT).read_bytes();doc=m.SourceExitInput.model_validate(json.loads(raw))
    obj=m.SourceExitCodec.__new__(m.SourceExitCodec)
    obj.expected_raw=raw;obj.document=doc;obj.origin=dict(source_cursor=doc.retained_source_session)
    obj.price=12.5;obj.objects=[];obj.applied=[];obj.zero_value_checks=[]
    loaded=obj.load(CAP/m.EXIT_INPUT,resume_session=doc.retained_source_session,
        predecessor_checkpoint_sha256=doc.predecessor_checkpoint_sha256)
    native=dict(session='2025-11-14',security_id=m.EXIT_SID,kind='CASH_MERGER',cash_per_share=None,
        delivered_security_id=None,delivered_ticker=None,delivered_issuer_id=None,exchange_ratio=None,
        cash_in_lieu_price_per_delivered_share=None,reference='actions/voluntarydelisting deal_value_musd=7173.3',entitlement_aggregation='HOLDER')
    assert m.digest(native)==doc.native_term_sha256
    Term=make_dataclass('Term',[(k,object) for k in native],frozen=True)
    Packet=make_dataclass('Packet',[('day',str),('terminal',tuple),('spins',tuple),('bars',tuple)],frozen=True)
    return obj,loaded,Packet('2025-11-14',(Term(**native),),(),(object(),))


def test_packet_changes_only_declared_terminal_fields_and_preserves_unrelated_term():
    c,d,p=codec_packet();other=replace(p.terminal[0],security_id='unrelated')
    p=replace(p,terminal=(*p.terminal,other));new=c.apply(p,d)
    assert new.terminal[0].cash_per_share==12.5 and new.terminal[1] is other
    assert new.bars is p.bars and new.spins is p.spins
    assert c.apply(p,d)==new and len(c.applied)==1
    with pytest.raises(ValueError,match='NATIVE_TERMINAL_PREIMAGE'):c.apply(new,d)


@pytest.mark.parametrize('kind',['native','delivery','spin','unregistered'])
def test_wrong_native_or_other_delivery_or_unregistered_input_refuses(kind):
    c,d,p=codec_packet()
    if kind=='native':p=replace(p,terminal=(replace(p.terminal[0],reference='wrong'),))
    elif kind=='delivery':p=replace(p,terminal=(*p.terminal,replace(p.terminal[0],security_id='other',delivered_security_id=m.EXIT_SID)))
    elif kind=='spin':p=replace(p,spins=({'child_security_id':m.EXIT_SID},))
    else:c.objects=[]
    with pytest.raises(ValueError,match='SOURCE_EXIT_'):c.apply(p,d)


@pytest.mark.parametrize('role',['held','pending','reservation','claim','history','nested_history','prior_term'])
def test_every_material_financial_role_refuses(role):
    s=state();sid=m.EXIT_SID
    if role=='held':s['wealth_core']['episodes']['e']={'security_id':sid}
    elif role=='pending':s['pending']=[{'security_id':sid}]
    elif role=='reservation':s['wealth_core']['slots']['s']={'reserved_ticker':'LNWO'}
    elif role=='claim':s['ledger']['receivables']=[{'security_id':sid}]
    elif role=='history':s['ledger']['events']=[{'security_id':sid}]
    elif role=='nested_history':s['ledger']['events']=[{'detail':{'anything':{'child_security_id':sid}}}]
    else:s['wealth_core']['terminal_pending_terms']={sid:{}}
    with pytest.raises(ValueError,match='SOURCE_EXIT_'):m.source_exit_scope(s)


def test_zero_value_before_and_after_require_actual_use():
    c,d,p=codec_packet();s=SimpleNamespace(**state())
    with pytest.raises(ValueError,match='APPLIED_ONCE'):c.before(s,p.day)
    c.apply(p,d);n=c.before(s,p.day)
    s.ledger['events'].append(dict(security_id=m.EXIT_SID,cash_delta=0,shares_delta=0))
    c.after(s,p.day,n)
    assert c.zero_value_checks==[dict(session=p.day,no_source_financial_value_added=True)]


@pytest.mark.parametrize('field',['cash_delta','shares_delta'])
def test_source_exit_cannot_add_cash_or_shares(field):
    c,d,p=codec_packet();s=SimpleNamespace(**state());c.apply(p,d);n=c.before(s,p.day)
    event=dict(security_id='other',detail={'child_security_id':m.EXIT_SID},cash_delta=0,shares_delta=0);event[field]=1
    s.ledger['events'].append(event)
    with pytest.raises(ValueError,match='CANNOT_ADD_PORTFOLIO'):c.after(s,p.day,n)


def test_quote_uses_exact_raw_close_and_date_without_signal_or_execution_price_inference():
    quote=dict(security_id=m.EXIT_SID,ticker='LNWO',session='2025-11-13',raw_close=12.5)
    doc=SimpleNamespace(source_ticker='LNWO',retained_source_session=quote['session'],retained_raw_quote_sha256=m.digest(quote))
    series=dict(security_id=m.EXIT_SID,ticker='LNWO',sessions=[quote['session']],raw_closes=[12.5],signal_closes=[25.0])
    origin={'run':{'state':{'feed':{'series':{m.EXIT_SID:series}}}}}
    assert m.retained_exit_quote(origin,doc)==12.5
    series['raw_closes']=[13.0]
    with pytest.raises(ValueError,match='RAW_QUOTE_PREIMAGE'):m.retained_exit_quote(origin,doc)
    # The same hostile quote passes if its hash predicate is removed.
    fn,=[n for n in ast.parse(Path(m.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='retained_exit_quote']
    comparison,=[n for n in ast.walk(fn) if isinstance(n,ast.BoolOp)
        and any(isinstance(v,ast.Compare) and ast.unparse(v)=='digest(quote) == document.retained_raw_quote_sha256' for v in n.values)]
    comparison.values=[v for v in comparison.values if ast.unparse(v)!='digest(quote) == document.retained_raw_quote_sha256']
    scope=dict(vars(m));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<quote-guard-removal>','exec'),scope)
    assert scope['retained_exit_quote'](origin,doc)==13.0
    series['sessions']=['2025-11-12']
    with pytest.raises(ValueError,match='SOURCE_DATE_AND_ID'):m.retained_exit_quote(origin,doc)


def test_history_falsifier_fails_if_guard_removed():
    value=state();value['ledger']['events']=[{'security_id':m.EXIT_SID}]
    with pytest.raises(ValueError):m.source_exit_scope(value)
    fn,=[n for n in ast.parse(Path(m.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='source_exit_scope']
    fn.body=[n for n in fn.body if not (isinstance(n,ast.If) and ast.unparse(n.test)=='history')]
    scope=dict(vars(m));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<history-guard-removal>','exec'),scope)
    assert scope['source_exit_scope'](value) is None


def test_explicit_future_request_and_qualification_gate():
    r=m.expected_request();spec=m.read(CAP/m.SPEC)
    assert (r['original_sessions'],r['remaining_sessions'],r['original_inputs'],r['successor_inputs'])==(1979,177,14,15)
    assert r['new_input_file']==m.EXIT_INPUT and r['new_event_qualification_required']
    assert r['qualification_wait_seconds']==2400
    proof=dict(passed=True,parent_sha256=spec['outer_sha256'],old_qualification_reexecuted=False,
        qualification_state_adopted=False,components=[{},{}],source_exit_input_sha256=r['new_input_sha256'],
        source_exit_applications=[{}],source_exit_zero_value_checks=[dict(session='2025-11-14',no_source_financial_value_added=True)])
    m.validate_event_qualification(proof,spec,r)
    for k,v in [('parent_sha256','wrong'),('source_exit_input_sha256','wrong'),('source_exit_zero_value_checks',[])]:
        with pytest.raises(ValueError):m.validate_event_qualification({**proof,k:v},spec,r)


def test_public_plan_contains_no_price_and_cannot_claim_held_or_execution_capability():
    value=json.loads((CAP/m.EXIT_INPUT).read_bytes());assert not any(k in value for k in ('raw_close','cash_per_share','price'))
    for k,v in [('legal_identity_admitted',True),('execution_price_claimed',True),('held_settlement_supported',True),('native_term_sha256','a'*64)]:
        with pytest.raises(ValueError):m.SourceExitInput.model_validate({**value,k:v})


def test_actual_successor_transport_requires_extraction_descriptor_before_download(tmp_path,monkeypatch):
    import subprocess
    spec=m.read(CAP/m.SPEC)
    assert m.successor_manifest_descriptor(spec['transport'])['member_count']==221
    old=deepcopy(spec);old['transport']['manifest']={'schema':'research.full-system-output/1','members':{}}
    def forbidden(*a,**k):raise AssertionError('NO_TRANSPORT_OR_CRYPTO_PERMITTED')
    monkeypatch.setattr(subprocess,'run',forbidden)
    with pytest.raises(ValueError,match='TRANSPORT_MANIFEST_DESCRIPTOR'):
        m.authenticate_successor(tmp_path/'unused',b'X'*32,old)
    assert not (tmp_path/'unused').exists()
