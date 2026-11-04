"""New literal cash facts, own source scope, actual cash/V order; DATA only."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import ModuleType,SimpleNamespace

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_future as f
import system_campaign_financial_resume as m


@pytest.mark.parametrize('arm,cursor,ticker,price,day,native',[
    ('P04','2022-06-30','SAFM',203.,'2022-07-22','2022-07-21'),
    ('P10','2022-07-29','ACC',65.47,'2022-08-10','2022-08-09'),
    ('P10','2024-04-30','SWAV',335.,'2024-05-31','2024-05-30')])
def test_actual_new_cash_terms_keep_exact_independent_witness_and_own_phase(arm,cursor,ticker,price,day,native):
    codec,name,terms=f.selected(arm,cursor=cursor);t,=terms
    assert name==f.OWN_CASH_CATALOG and t['ticker']==ticker and t['added']['cash_per_share']==price
    assert t['added']['session']==day and t['native_session']==native
    assert t['identity_witness']['security_type_eligible']=='1'
    assert t['source_capture']['run_id']==f.OWN_CASH_SOURCE_CLOCKS[arm,cursor][0]
    assert t['parent_outer_sha256']==m.root_spec(arm,t['parent_root_admission_sha256'])['outer_sha256']
    assert t['parent_positions']==f.registered_scope(t['source_capture']['scope_sha256'])['terms'][0]['parent_positions']
    cp=dict(source_cursor=cursor,run=dict(checkpoint_sha256='a'*64))
    material=dict(terms=terms,catalog_sha256=codec.catalog_sha,original_validator_sha256=codec.compiler_sha,
        selector_sha256='b'*64,original_validator_description=codec.validator_description)
    doc=f.document(cp,material,'c'*64)
    assert doc['suppress']==[dict(session=native,security_id=t['security_id'],term_sha256=t['native_term_sha256'])]
    assert doc['add']==[t['added']] and t['added']['entitlement_aggregation']=='HOLDER'
    hashes={v['sha256'] for v in doc['source_evidence']}
    assert t['source_capture']['payload_sha256'] in hashes and t['source_capture']['independent_data_review_sha256'] in hashes
    if arm=='P04':
        assert t['preopen_completion_confirmed'] is True and t['actual_completion_date']==day
        assert t['parent_positions'][0]['quantity']==29
    elif ticker=='ACC':
        assert t['preopen_completion_confirmed'] is False and t['actual_completion_date']==native
        assert t['recognition_rule']=='RETAINED_NEXT_SESSION_AFTER_CONFIRMED_LAST_TRADING_DAY'
        assert t['parent_positions']==[]  # The later78-share holding is produced by the resumed path.
    else:
        assert t['preopen_completion_confirmed'] is True and t['actual_completion_date']==day
        assert t['recognition_rule']=='CONFIRMED_PREOPEN_COMPLETION' and t['parent_positions']==[]
        assert t['retained_primary_catalog']['filename']=='system-campaign-unconsumed2024-cash-calendar-terminal-facts.json'


def changed_catalog(tmp_path,monkeypatch):
    value=json.loads((f.HERE/f.OWN_CASH_CATALOG).read_bytes())
    value['terms'][0]['added']['cash_per_share']=204.
    (tmp_path/f.OWN_CASH_CATALOG).write_bytes((json.dumps(value,sort_keys=True,indent=2)+'\n').encode())
    monkeypatch.setattr(f,'HERE',tmp_path)


def test_any_changed_literal_cash_catalog_refuses_before_use(tmp_path,monkeypatch):
    changed_catalog(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='EXACT_REVIEWED_LITERAL_CATALOG'):f.own_cash_selection('P04','2022-06-30')


def test_literal_fact_digest_guard_removal_falsifier(tmp_path,monkeypatch):
    original=f.HERE;value=json.loads((original/f.OWN_CASH_CATALOG).read_bytes())
    value['terms'][-1]['source_capture']['payload_sha256']='0'*64
    (tmp_path/f.OWN_CASH_CATALOG).write_bytes((json.dumps(value,sort_keys=True,indent=2)+'\n').encode())
    primary=value['terms'][-1]['retained_primary_catalog']['filename']
    (tmp_path/primary).write_bytes((original/primary).read_bytes());monkeypatch.setattr(f,'HERE',tmp_path)
    with pytest.raises(ValueError):f.own_cash_selection('P10','2024-04-30')
    fn=next(n for n in ast.parse(Path(f.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='own_cash_selection')
    guard=next(n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and
               any(isinstance(a,ast.Constant) and a.value=='OWN_CASH_EXACT_REVIEWED_LITERAL_CATALOG' for a in n.value.args))
    fn.body.remove(guard);ns=dict(vars(f));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<removed-literal-cash-fact-guard>','exec'),ns)
    assert ns['own_cash_selection']('P10','2024-04-30')[2][0]['source_capture']['payload_sha256']=='0'*64


def test_historical_cash_phases_keep_original_full_catalog_generation():
    old='7b58c64413b5f513ce76b9c7382f34cf8df612969e0865604ba283eb8a464be9'
    for phase in [('P04','2022-06-30'),('P10','2022-07-29')]:
        codec,_,_=f.own_cash_selection(*phase)
        assert codec.catalog_sha==old and len(codec.catalog['terms'])==2
        assert f.sha((json.dumps(codec.catalog,sort_keys=True,indent=2)+'\n').encode())==old
    codec,_,terms=f.own_cash_selection('P10','2024-04-30')
    assert len(codec.catalog['terms'])==3 and codec.catalog_sha==f.OWN_CASH_SHA
    assert terms[0]['source_capture']['run_id']==41799737694


def test_reviewed_append_cannot_silently_edit_a_closed_generation(tmp_path,monkeypatch):
    original=f.HERE;changed_catalog(tmp_path,monkeypatch)
    primary='system-campaign-unconsumed2024-cash-calendar-terminal-facts.json'
    (tmp_path/primary).write_bytes((original/primary).read_bytes())
    monkeypatch.setattr(f,'OWN_CASH_SHA',f.sha((tmp_path/f.OWN_CASH_CATALOG).read_bytes()))
    with pytest.raises(ValueError,match='CLOSED_CATALOG_GENERATION_BYTES'):
        f.own_cash_selection('P10','2024-04-30')
    fn=next(n for n in ast.parse(Path(f.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='own_cash_selection')
    loop=next(n for n in fn.body if isinstance(n,ast.For) and ast.unparse(n.iter)=='CLOSED_CASH_GENERATIONS.items()')
    fn.body.remove(loop);ns=dict(vars(f))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<removed-closed-cash-generation-guard>','exec'),ns)
    assert ns['own_cash_selection']('P04','2022-06-30')[2][0]['added']['cash_per_share']==204.


@pytest.mark.parametrize('change',['cash','clock','metadata','native'])
def test_retained_swav_primary_terms_and_metadata_cannot_change(change):
    _,_,terms=f.own_cash_selection('P10','2024-04-30');term=deepcopy(terms[0])
    if change=='cash':term['added']['cash_per_share']=334.
    elif change=='clock':term['preopen_completion_confirmed']=False
    elif change=='metadata':term['identity_witness']['issuer_id']='SEC_UNKNOWN'
    else:term['native_term_sha256']='0'*64
    with pytest.raises(ValueError,match='UNCHANGED_RETAINED_PRIMARY_TERM'):f.retained_primary(term)


def test_retained_primary_guard_removal_falsifier():
    _,_,terms=f.own_cash_selection('P10','2024-04-30');term=deepcopy(terms[0]);term['added']['cash_per_share']=334.
    with pytest.raises(ValueError):f.retained_primary(term)
    fn=next(n for n in ast.parse(Path(f.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='retained_primary')
    fn.body.pop();ns=dict(vars(f))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<removed-retained-primary-guard>','exec'),ns)
    assert ns['retained_primary'](term) is None


@pytest.mark.parametrize('change',['outer','position'])
def test_wrong_parent_refuses_before_frozen_source_access(monkeypatch,tmp_path,change):
    monkeypatch.setattr(f,'hosted',lambda:None)
    fake=ModuleType('research.pooled_input_support')
    fake.inputs=SimpleNamespace(load_actions=lambda *a:(_ for _ in ()).throw(AssertionError('unsafe source access')))
    monkeypatch.setitem(sys.modules,'research.pooled_input_support',fake)
    cp=dict(source_cursor='2022-06-30',sha256=m.root_spec('P04')['outer_sha256'],
            run=dict(state=dict(wealth_core=dict(episodes={}))))
    if change=='outer':cp['sha256']='0'*64
    with pytest.raises(ValueError,match='OWN_CASH_'):f.hydrate(cp,'P04')


def cash_phase():
    sid='209530306982231273';quantity=78;amount=quantity*65.47
    record=dict(session='2022-08-10',cash=[dict(security_id=sid,actual_context_call=True,
        postcondition=dict(actual_held=True,quantity=quantity,nominal_cash=amount))],
        engine_calls=1,order=['CASH:'+sid,'ENGINE'],risk=[(6,'other')])
    result=SimpleNamespace(state=SimpleNamespace(pending=[]))
    terms=[dict(session='2022-08-10',security_id=sid,kind='CASH_MERGER')]
    return record,result,terms


def test_actual_resumed_quantity_is_used_for_cash_before_original_v_loop():
    record,result,terms=cash_phase();before=deepcopy(record)
    f.actual_cash_phase(record,result,'P10',terms)
    assert record==before
    record['cash'][0]['postcondition'].update(quantity=77,nominal_cash=77*65.47)
    f.actual_cash_phase(record,result,'P10',terms)  # Observes canonical output; never imports78 from a tail.


@pytest.mark.parametrize('change',['auxiliary','duplicate','other_sid','order','surviving_risk','pending','engine'])
def test_wrong_actual_cash_context_or_v_order_refuses(change):
    record,result,terms=cash_phase();sid=terms[0]['security_id']
    if change=='auxiliary':record['cash'][0]['actual_context_call']=False
    elif change=='duplicate':record['cash'].append(deepcopy(record['cash'][0]))
    elif change=='other_sid':record['cash'][0]['security_id']='other'
    elif change=='order':record['order'].reverse()
    elif change=='surviving_risk':record['risk'].append((9,sid))
    elif change=='pending':result.state.pending.append(dict(security_id=sid))
    else:record['engine_calls']=0
    with pytest.raises(ValueError):f.actual_cash_phase(record,result,'P10',terms)


def test_one_actual_cash_context_guard_removal_falsifier():
    record,result,terms=cash_phase();record['cash'].append(deepcopy(record['cash'][0]))
    with pytest.raises(ValueError):f.actual_cash_phase(record,result,'P04',terms)
    fn=next(n for n in ast.parse(Path(f.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='actual_cash_phase')
    loop=next(n for n in fn.body if isinstance(n,ast.For))
    guard=next(n for n in loop.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call))
    loop.body.remove(guard);ns=dict(vars(f));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<removed-actual-cash-context-count>','exec'),ns)
    ns['actual_cash_phase'](record,result,'P04',terms)


@pytest.mark.parametrize('mode,flags',[
    ('OWN_ADMITTED_FINANCIAL_CONTINUATION',(True,False,False)),
    ('READONLY_NEW_FINANCIAL_PREFIX_AND_REPORTING_ADMISSION',(False,True,False)),
    ('READONLY_FROZEN_SOURCE_WITNESSES',(False,False,True))])
def test_explicit_mode_derives_all_authority_flags_and_worker_limits(monkeypatch,mode,flags):
    monkeypatch.setattr(m,'EXECUTION_MODE',mode)
    arms=('P00',) if flags[1] else (('P10',) if flags[2] else ('P04','P10'))
    monkeypatch.setattr(m,'SELECTED_ARMS',arms);r=m.expected_request()
    assert tuple(r[k] for k in ('financial_resume_authorized','readonly_partial_review','readonly_source_witnesses'))==flags
    assert r['maximum_parallel_financial_workers']==(len(arms) if flags[0] else 0)
    assert r['maximum_parallel_readonly_workers']==(0 if flags[0] else len(arms))
    assert set(r['source_witness_scopes'])==({'P10'} if flags[2] else set())
    assert m.request_authority(r)


def test_unknown_execution_mode_refuses_before_request_generation(monkeypatch):
    monkeypatch.setattr(m,'EXECUTION_MODE','UNKNOWN')
    with pytest.raises(ValueError,match='ONE_EXPLICIT_REQUEST_EXECUTION_MODE'):m.expected_request()
