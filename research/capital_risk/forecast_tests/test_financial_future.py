"""Root/future-only/actual-cash falsifiers using DATA and synthetic calls only."""
import ast
from copy import deepcopy
import gzip
import inspect
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_partial as p
import system_campaign_financial_future as f
import system_campaign_financial_uncertainty as u


def entry(arm='P10'):
    return json.loads((p.HERE / p.ROOTS).read_bytes())['arms'][arm]


def test_actual_root_admissions_preserve_historical_transport_flags():
    for arm, count in [('P04', 817), ('P07', 439), ('P10', 692)]:
        value = entry(arm); before = deepcopy(value)
        spec = p.authorized_spec(value, arm)
        p.validate_root_spec(spec)
        assert value == before and spec['measured_closes'] == count
        assert spec['financial_authority'] is spec['financial_predecessor_admitted'] is False
        assert spec['root_admission']['financial_continuation_authorized'] is True
        assert spec['root_admission']['full_financial_validation_completed'] is False


@pytest.mark.parametrize('change', ['digest','score','arm','cipher','journal','source','checkpoint','count'])
def test_root_authority_and_every_transport_identity_refuse(change):
    value = entry()
    if change == 'digest':value['admission_sha256'] = '0' * 64
    elif change == 'score':value['admission']['performance_scoring_authorized'] = True
    elif change == 'arm':value['transport']['arm'] = 'P04'
    elif change == 'cipher':value['transport']['encrypted_output']['sha256'] = '0' * 64
    elif change == 'journal':value['transport']['journals']['daily']['bytes'] += 1
    elif change == 'source':value['transport']['base']['sources'][next(iter(value['transport']['base']['sources']))] = '0'*64
    elif change == 'checkpoint':value['transport']['outer_sha256'] = '0'*64
    else:value['transport']['measured_closes'] += 1
    with pytest.raises(ValueError):p.authorized_spec(value, 'P10')


def pending_fixture():
    _, _, terms = f.selected('P10'); t = terms[0]; sid = t['security_id']
    native = dict(cash_in_lieu_price_per_delivered_share=None, cash_per_share=None, delivered_issuer_id=None,
        delivered_security_id=None, delivered_ticker=None, entitlement_aggregation='HOLDER', exchange_ratio=None,
        kind='CASH_MERGER', reference='actions/acquisitionby deal_value_musd=6237.1', security_id=sid, session='2020-09-30')
    assert f.digest(native) == t['native_term_sha256']
    w = dict(episodes={'5':dict(security_id=sid,slot_id=5,current_shares=101,exit_pending=False)},
        slots={'5':dict(occupied_by=sid)}, terminal_pending_sessions={sid:0},
        terminal_pending_terms={sid:dict(stale_at_event=0,terms=native)},unresolved_terminals={},
        terminal_carry_audit={sid:dict(carry_price=52.49,carry_session='2020-09-30',
            grace_prints=[dict(price=52.48,session='2020-09-30')],grace_split_multiplier=1.,grace_splits=[],
            last_trustworthy_print_session='2020-09-29',shares_at_carry=101)})
    return dict(source_cursor='2020-09-30',run=dict(state=dict(wealth_core=w))), terms, sid


def test_consumed_mnta_native_is_preserved_complete_future_cash_only_is_added():
    cp, terms, sid = pending_fixture(); before = deepcopy(cp)
    suppress = f.suppressions(cp, terms)
    assert len(suppress) == 4 and sid not in {s['security_id'] for s in suppress}
    assert all(s['session'] > cp['source_cursor'] for s in suppress)
    assert cp == before
    _,_,following=f.selected('P04')
    assert tuple(t['ticker'] for t in following)==('APHA','CATM','REGI','PLAN')
    assert len(f.suppressions(dict(source_cursor='2021-03-31'),following))==4


@pytest.mark.parametrize('change',['age','native','shares','held','slot','carry','past','other_consumed','cash'])
def test_pending_completion_cannot_be_generalized_or_rewrite_consumed_input(change):
    cp,terms,sid=pending_fixture();w=cp['run']['state']['wealth_core']
    if change=='age':w['terminal_pending_sessions'][sid]=1
    elif change=='native':w['terminal_pending_terms'][sid]['terms']['cash_per_share']=52.5
    elif change=='shares':w['episodes']['5']['current_shares']=102
    elif change=='held':w['episodes'].clear()
    elif change=='slot':w['slots']['5']['occupied_by']=None
    elif change=='carry':w['terminal_carry_audit'][sid]['shares_at_carry']=100
    elif change=='past':terms[0]['added']['session']='2020-09-30'
    elif change=='cash':terms[0]['added']['cash_per_share']=52.49
    else:terms[1]['native_session']='2020-09-30'
    with pytest.raises(ValueError):f.suppressions(cp,terms)


def test_pending_guard_removal_falsifier():
    cp,terms,sid=pending_fixture();cp['run']['state']['wealth_core']['terminal_pending_sessions'][sid]=1
    with pytest.raises(ValueError):f.suppressions(cp,terms)
    fn=next(n for n in ast.parse(Path(f.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='pending_completion')
    fn.body[-1]=ast.Pass();ns=dict(vars(f))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-actual-pending-guard>','exec'),ns)
    old=f.pending_completion
    try:
        f.pending_completion=ns['pending_completion']
        with pytest.raises(AssertionError):
            try:f.suppressions(cp,terms)
            except ValueError:refused=True
            else:refused=False
            assert refused
    finally:f.pending_completion=old


def cash_fixture():
    t=dict(security_id='s',cash_per_share=52.5,reference='primary')
    before=dict(cash=100.,episodes={'5':dict(security_id='s',current_shares=101)},slots={'5':dict(occupied_by='s')})
    after=dict(cash=5402.5,episodes={},slots={'5':dict(occupied_by=None)},terminal_pending_terms={},terminal_pending_sessions={})
    ledger=dict(events=[],receivables=[dict(inert='unchanged')])
    event=dict(event_type='CASH_MERGER',security_id='s',price=52.5,shares_delta=-101,cash_delta=5302.5,
        detail=dict(shares=101,reference='primary'),fees=0.,cash_before=100.,cash_after=5402.5)
    posted=dict(events=[event],receivables=deepcopy(ledger['receivables']))
    return before,after,ledger,posted,t,dict(applied=True)


def test_actual_cash_checker_has_no_financial_state_mutation():
    args=cash_fixture();before=deepcopy(args)
    assert f.cash_postcondition(*args)==dict(actual_held=True,quantity=101,nominal_cash=5302.5)
    assert args==before


@pytest.mark.parametrize('change',['fees','cash','shares','event','pending','receivables','slot'])
def test_actual_cash_mispost_refuses_before_commit(change):
    before,after,ledger,posted,t,result=cash_fixture()
    if change=='fees':posted['events'][0]['fees']=.01
    elif change=='cash':after['cash']+=.01
    elif change=='shares':posted['events'][0]['shares_delta']=-100
    elif change=='event':posted['events'].clear()
    elif change=='pending':after['terminal_pending_terms']['s']={}
    elif change=='receivables':posted['receivables'].clear()
    else:after['slots']['5']['occupied_by']='s'
    with pytest.raises(ValueError):f.cash_postcondition(before,after,ledger,posted,t,result)


def test_cash_post_guard_removal_falsifier():
    args=cash_fixture();args[3]['events'][0]['fees']=.01
    with pytest.raises(ValueError):f.cash_postcondition(*args)
    fn=next(n for n in ast.parse(Path(f.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='cash_postcondition')
    loop=next(n for n in fn.body if isinstance(n,ast.For))
    guard=next(n for n in loop.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and n.value.func.id=='need')
    loop.body.remove(guard);ns=dict(vars(f))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-cash-post-guard>','exec'),ns)
    with pytest.raises(AssertionError):
        try:ns['cash_postcondition'](*args)
        except ValueError:refused=True
        else:refused=False
        assert refused


def test_core_observer_uses_only_modules_present_in_actual_non_v_source(tmp_path,monkeypatch):
    runtime=SimpleNamespace(advance=lambda *a:None)
    terminal=SimpleNamespace(apply_terminal=lambda *a:None)
    research=ModuleType('research.pooled_vacancy_funding');research.runtime=runtime
    core=ModuleType('stock_strategy_shared.wealth_core');core.terminal=terminal
    core.adapter=SimpleNamespace(step_session=lambda *a:None)
    # No capital_risk is supplied: the actual P04 source lacks that V-only module.
    monkeypatch.setitem(sys.modules,'research.pooled_vacancy_funding',research)
    monkeypatch.setitem(sys.modules,'stock_strategy_shared.wealth_core',core)
    monkeypatch.setattr(f,'hosted',lambda:None)
    (tmp_path/f.OVERLAY).write_text(json.dumps(dict(add=[])))
    original_advance,original_terminal=runtime.advance,terminal.apply_terminal
    with f.ActualEvents(tmp_path,'P04'):
        assert runtime.advance!=original_advance and terminal.apply_terminal!=original_terminal
    assert runtime.advance is original_advance and terminal.apply_terminal is original_terminal


def test_actual_callsite_requires_code_state_ledger_and_session_identity():
    def step_session(state,ledger,session):return inspect.currentframe()
    state,ledger=object(),object();frame=step_session(state,ledger,'2020-10-01')
    assert f.actual_terminal_call(frame,step_session.__code__,state,ledger,'2020-10-01')
    def same_name(state,ledger,session):return inspect.currentframe()
    same_name.__name__='step_session'
    for code,s,l,d in [(same_name.__code__,state,ledger,'2020-10-01'),
                        (step_session.__code__,object(),ledger,'2020-10-01'),
                        (step_session.__code__,state,object(),'2020-10-01'),
                        (step_session.__code__,state,ledger,'2020-10-02')]:
        assert not f.actual_terminal_call(frame,code,s,l,d)


def test_actual_code_identity_guard_removal_falsifier():
    def step_session(state,ledger,session):return inspect.currentframe()
    state,ledger=object(),object();frame=step_session(state,ledger,'d');wrong=(lambda:None).__code__
    assert not f.actual_terminal_call(frame,wrong,state,ledger,'d')
    fn=next(n for n in ast.parse(Path(f.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='actual_terminal_call')
    fn.body[0].value.values.pop(0);ns=dict(vars(f))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-code-identity-guard>','exec'),ns)
    with pytest.raises(AssertionError):assert not ns['actual_terminal_call'](frame,wrong,state,ledger,'d')


def test_uncertainty_proof_uses_only_exact_qualified_sources_and_own_root():
    s=p.root_spec('P07')
    cp=dict(base=deepcopy(s['base']),sha256=s['outer_sha256'],source_cursor=s['selected_session'],completed=s['measured_closes'])
    saved=deepcopy(cp);assert len(u.source_contract(cp))==6 and cp==saved
    for change in ['source','count','parent']:
        bad=deepcopy(cp)
        if change=='source':bad['base']['sources']['sentinel/controller/median5.py']='0'*64
        elif change=='count':bad['completed']+=1
        else:bad['sha256']=p.root_spec('P04')['outer_sha256']
        with pytest.raises(ValueError):u.source_contract(bad)


def test_uncertainty_controller_guard_removal_falsifier():
    s=p.root_spec('P07');cp=dict(base=deepcopy(s['base']),sha256=s['outer_sha256'],source_cursor=s['selected_session'],completed=s['measured_closes'])
    cp['base']['sources']['sentinel/controller/median5.py']='0'*64
    with pytest.raises(ValueError):u.source_contract(cp)
    fn=next(n for n in ast.parse(Path(u.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='source_contract')
    guard=next(n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and n.value.func.id=='need')
    fn.body.remove(guard);ns=dict(vars(u));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-source-guard>','exec'),ns)
    with pytest.raises(AssertionError):
        try:ns['source_contract'](cp)
        except ValueError:refused=True
        else:refused=False
        assert refused


def test_uncertainty_boundary_requires_exact_actual_written_gzip_and_proof(tmp_path):
    from research.capital_risk.forecast_tests.test_pxd_pause import pair,OVERLAY
    import system_campaign_financial_resume as launcher
    before,after,_=pair();overlay=tmp_path/'input.json';overlay.write_bytes(b'inert input bytes')
    # Rebind only synthetic metadata, preserving the complete neutral contract.
    from research.capital_risk.forecast_tests.test_pxd_pause import outer
    descriptor=after['repairs'][0];descriptor['filename']=f.sha(overlay.read_bytes())+'.json';descriptor['sha256']=f.sha(overlay.read_bytes())
    after['run']['input_sha256']=f.digest(dict(base=after['base'],repairs=after['repairs']))
    # Recreate the source-bound neutral event/outer hashes after the inert digest change.
    previous=before['chain']
    e=dict(schema='research.pooled-action-successor/1',predecessor_checkpoint_sha256=before['run']['checkpoint_sha256'],
        unchanged_through=before['source_cursor'],earliest_affected_session='2024-05-02',state_sha256=before['run']['state_sha256'],
        overlay=descriptor,predecessor_input_sha256=before['run']['input_sha256'],successor_input_sha256=after['run']['input_sha256'])
    after['chain']=f.digest(dict(previous=previous,event=e));outer(after)
    root=tmp_path/'book';root.mkdir()
    gate=launcher.AdoptionGate(before,root,tmp_path/u.MODEL_ADOPTION,f.sha(overlay.read_bytes()),'2024-05-02')
    gate.original_write=lambda path,value:Path(path).write_bytes(gzip.compress(json.dumps(value).encode()))
    gate.write(root/'checkpoint.json.gz',after)
    assert u.boundary(tmp_path,u.MODEL_ADOPTION,before,overlay.name,'2024-05-02')==after
    proof=tmp_path/u.MODEL_ADOPTION/'proof.json';v=json.loads(proof.read_bytes());v['financial_sessions_advanced']=1;proof.write_text(json.dumps(v))
    with pytest.raises(ValueError):u.boundary(tmp_path,u.MODEL_ADOPTION,before,overlay.name,'2024-05-02')
