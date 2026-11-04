"""Admission registry and same-day event qualification, DATA/synthetic only."""
from copy import deepcopy
from dataclasses import asdict, dataclass, field, make_dataclass, replace
import json
from pathlib import Path
import sys
from types import ModuleType,SimpleNamespace

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_partial as p
import system_campaign_financial_future as f


@pytest.fixture(autouse=True)
def local_registered_catalog_path(monkeypatch):
    import system_campaign_ordinary_registry as registry
    original=registry.registrations
    monkeypatch.setattr(registry,'registrations',lambda:original(p.HERE))


def test_both_generations_resolve_by_exact_own_admission_hash():
    for arm,old,new in [('P04',817,1090),('P07',439,503),('P10',692,1028)]:
        latest=p.root_spec(arm);prior=p.root_spec(arm,p.PRIOR_ADMISSIONS[arm])
        assert (prior['measured_closes'],latest['measured_closes'])==(old,new)
        assert latest['root_admission']['parent_root_admission_sha256']==prior['root_admission_sha256']
        assert p.root_spec(arm,p.ADMISSIONS[arm])==latest
        p.validate_root_spec(prior);p.validate_root_spec(latest)
        assert latest['root_admission']['financial_continuation_authorized'] is True
        assert latest['financial_authority'] is latest['financial_predecessor_admitted'] is False
        assert latest['root_admission']['performance_scoring_authorized'] is False


@pytest.mark.parametrize('arm,digest',[('P04','0'*64),('P07',p.PRIOR_ADMISSIONS['P04']),('P10',p.ADMISSIONS['P04'])])
def test_unknown_or_other_arm_historical_root_refuses(arm,digest):
    with pytest.raises(ValueError):p.root_spec(arm,digest)


def test_historical_root_never_silently_selects_current(monkeypatch):
    value=json.loads((p.HERE/p.ROOTS).read_bytes());key=p.PRIOR_ADMISSIONS['P04']
    value['historical_roots'][key]=deepcopy(value['arms']['P04'])
    class FakePath:
        def __truediv__(self,name):return self
        def read_bytes(self):return json.dumps(value).encode()
    monkeypatch.setattr(p,'HERE',FakePath())
    with pytest.raises(ValueError,match='EXACT_SELECTED_ROOT_HASH'):p.root_spec('P04',key)


def test_next_p04_selects_only_unconsumed_epay_no_duplicate_regi_plan():
    _,catalog,terms=f.selected('P04',cursor='2022-04-29')
    assert catalog=='system-campaign-december-cash-calendar-terminal-facts.json'
    t,=terms;assert t['ticker']=='EPAY' and t['added']['cash_per_share']==57.
    assert t['native_session']==t['added']['session']=='2022-05-13'
    assert len(f.suppressions(dict(source_cursor='2022-04-29'),terms))==1
    with pytest.raises(ValueError):f.suppressions(dict(source_cursor='2022-05-13'),terms)


def test_actual_same_day_qualification_exercises_wrong_native_falsifier(tmp_path,monkeypatch):
    _,_,terms=f.selected('P04',cursor='2022-04-29');t,=terms
    names=list(t['added']);Terminal=make_dataclass('Terminal',[(name,object) for name in names])
    Terminal.completeness=lambda self,n:(self.cash_per_share is not None,())
    native=Terminal(**dict(t['added'],cash_per_share=None,reference='synthetic incomplete native'))
    t['native_term_sha256']=f.digest(asdict(native))
    @dataclass(frozen=True)
    class Packet:
        session:object;bars:object;memberships:object;prices:object;spy:object;extra:object;terminal:object;spinoffs:object
    cp=dict(source_cursor='2022-04-29',base=dict(sources={'research/pooled_input_support/adapter.py':'a'*64}),run=dict(checkpoint_sha256='b'*64))
    document=dict(suppress=[dict(session=t['native_session'],security_id=t['security_id'],term_sha256=t['native_term_sha256'])],add=[t['added']])
    path=tmp_path/'overlay.json';path.write_text(json.dumps(document));calls=[]
    def load(path,*,resume_session,predecessor_checkpoint_sha256):
        if resume_session!=cp['source_cursor'] or predecessor_checkpoint_sha256!=cp['run']['checkpoint_sha256']:raise ValueError('wrong epoch')
        return json.loads(path.read_bytes())
    def apply(packet,loaded):
        original=packet.terminal[0]
        loaded=getattr(loaded,'document',loaded)
        if loaded['suppress'][0]['term_sha256']!=f.digest(asdict(original)):
            calls.append('wrong-native-refused');raise ValueError('suppressed original terminal differs: synthetic')
        calls.append('same-day-replaced');return replace(packet,terminal=(Terminal(**loaded['add'][0]),))
    def values(*,prior,published):
        if published.terminal_events[0].cash_per_share is None:raise ValueError('incomplete leadership cash terminal')
        return {t['security_id']:57.}
    modules={
      'research.pooled_input_support.adapter':dict(Packet=Packet),
      'research.pooled_vacancy_funding':dict(backtest=SimpleNamespace(apply_repair=apply)),
      'research.pooled_vacancy_funding.repair':dict(load_repair=load),
      'research.bounded_20y.run':dict(vendor=lambda x:x),
      'sentinel.controller':dict(terminal_returns=SimpleNamespace(values=values)),
      'system_campaign_sprint_facts':dict(qualify_packet_schema=lambda *a:None,
         published_packet=lambda p:SimpleNamespace(session=p.session,bars=p.bars,terminal_events=p.terminal)),
      'system_campaign_2021_completions_facts':dict(notional=lambda term,bar:term['cash_per_share'],require_witness=lambda *a:None),
    }
    for name,attrs in modules.items():
        module=ModuleType(name);vars(module).update(attrs);monkeypatch.setitem(sys.modules,name,module)
    f.qualify(cp,dict(terms=terms),{},SimpleNamespace(terminal={t['native_session']:(native,)}),
              SimpleNamespace(document=document,earliest_affected_session=t['native_session']),path,tmp_path)
    assert calls==['same-day-replaced','wrong-native-refused']
    proof=json.loads((tmp_path/'future-input-qualification.json').read_bytes())
    assert proof['packet_checks']==1 and proof['wrong_native_and_delivery_witness_refused'] is True


def test_next_p10_selects_only_unconsumed_vcra_before_original_v21_loop():
    _,catalog,terms=f.selected('P10',cursor='2022-01-31')
    assert catalog=='system-campaign-february-cash-calendar-terminal-facts.json'
    t,=terms;assert t['ticker']=='VCRA' and t['added']['cash_per_share']==79.25
    assert t['native_session']=='2022-02-22' and t['added']['session']=='2022-02-23'
    assert f.suppressions(dict(source_cursor='2022-01-31'),terms)==[dict(
        session='2022-02-22',security_id='576374012507208201',term_sha256=t['native_term_sha256'])]


def cash_order_fixture():
    sid='576374012507208201'
    record=dict(cash=[dict(actual_context_call=True,security_id=sid,
        postcondition=dict(actual_held=True,quantity=69,nominal_cash=5468.25))],
        engine_calls=1,order=['CASH:'+sid,'ENGINE'],risk=[(5,'other')])
    return record,SimpleNamespace(state=SimpleNamespace(pending=[])),sid


def test_exact_vcra_cash_settlement_precedes_unchanged_survivor_loop():
    record,result,sid=cash_order_fixture();before=deepcopy(record)
    f.cash_before_v(record,result,sid,69,5468.25);assert record==before


@pytest.mark.parametrize('change',['cash','quantity','order','engine','risk','pending','caller'])
def test_wrong_vcra_posting_order_or_surviving_source_refuses(change):
    record,result,sid=cash_order_fixture()
    if change=='cash':record['cash'][0]['postcondition']['nominal_cash']+=.01
    elif change=='quantity':record['cash'][0]['postcondition']['quantity']=68
    elif change=='order':record['order'].reverse()
    elif change=='engine':record['engine_calls']=0
    elif change=='risk':record['risk'].append((13,sid))
    elif change=='pending':result.state.pending.append(dict(security_id=sid))
    else:record['cash'][0]['actual_context_call']=False
    with pytest.raises(ValueError):f.cash_before_v(record,result,sid,69,5468.25)


def test_cash_before_v_guard_removal_falsifier():
    import ast
    record,result,sid=cash_order_fixture();record['cash'][0]['postcondition']['quantity']=68
    with pytest.raises(ValueError):f.cash_before_v(record,result,sid,69,5468.25)
    fn=next(n for n in ast.parse(Path(f.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='cash_before_v')
    fn.body.pop();ns=dict(vars(f));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-cash-before-v-guard>','exec'),ns)
    ns['cash_before_v'](record,result,sid,69,5468.25)


def test_original_risk_exception_identity_propagates_with_failed_sid_observation():
    error=ValueError('REFUSED_VOLATILITY_CAUSAL_AXIS')
    def failed(*a,**k):raise error
    observer=SimpleNamespace(risk_original=failed,current={})
    ep=SimpleNamespace(slot_id=13,security_id='576374012507208201')
    with pytest.raises(ValueError) as caught:f.ActualEvents.risk(observer,ep,bars=(),session='2022-02-23',cfg=None)
    assert caught.value is error
    assert observer.current['failed_risk_call']==dict(slot_id=13,security_id=ep.security_id,session='2022-02-23',error=str(error))
