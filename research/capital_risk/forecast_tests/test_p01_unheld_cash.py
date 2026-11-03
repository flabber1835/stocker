from dataclasses import make_dataclass
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

CAP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(CAP))
spec=importlib.util.spec_from_file_location('mdp_cash',CAP/'p01_iac_namespace_continue.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def state():
    return {'wealth_core':{'episodes':{},'slots':{}},'pending':[],'ledger':{'events':[],'receivables':[]}}


def test_actual_scope_is_zero_ownership_only():m.mdp_unheld_scope(state())


@pytest.mark.parametrize('role',['held','pending','reserved','claim','historical','historical_child','prior_terminal'])
def test_all_material_mdp_roles_refuse(role):
    value=state()
    if role=='held':value['wealth_core']['episodes']['0']={'security_id':m.MDP,'current_shares':1}
    elif role=='pending':value['pending']=[{'security_id':m.MDP}]
    elif role=='reserved':value['wealth_core']['slots']['0']={'reserved_for':m.MDP}
    elif role=='claim':value['ledger']['receivables']=[{'security_id':m.MDP}]
    elif role=='historical':value['ledger']['events']=[{'security_id':m.MDP}]
    elif role=='historical_child':value['ledger']['events']=[{'security_id':'other','detail':{'delivered_security_id':m.MDP}}]
    else:value['wealth_core']['terminal_pending_terms']={m.MDP:{}}
    with pytest.raises(ValueError,match='MDP_'):m.mdp_unheld_scope(value)


def setup_codec():
    value=json.loads((CAP/m.SUPPLEMENT).read_bytes())
    parent={'sha256':value['parent_outer_sha256'],'source_cursor':'2021-11-30','run':{'checkpoint_sha256':value['predecessor_checkpoint_sha256']}}
    codec=m.UnheldCashCodec(Path('unused'),parent)
    loaded=codec.load(CAP/m.SUPPLEMENT,resume_session=parent['source_cursor'],predecessor_checkpoint_sha256=parent['run']['checkpoint_sha256'])
    native=dict(session='2021-12-01',security_id=m.MDP,kind='CASH_MERGER',cash_per_share=None,
                delivered_security_id=None,delivered_ticker=None,delivered_issuer_id=None,exchange_ratio=None,
                cash_in_lieu_price_per_delivered_share=None,reference='actions/acquisitionby deal_value_musd=2705.5',entitlement_aggregation='HOLDER')
    Term=make_dataclass('Term',[(key,object) for key in native],frozen=True)
    Packet=make_dataclass('Packet',[('day',str),('terminal',tuple),('bars',tuple),('meta',object)],frozen=True)
    packet=Packet('2021-12-01',(Term(**native),),('unchanged-bars',),object())
    return codec,loaded,packet,value


def test_complete_ordered_terms_and_only_terminal_fields_change():
    codec,loaded,packet,value=setup_codec()
    assert value['ordered_legs']==['DISTRIBUTE_NEW_MEREDITH_ONE_FOR_ONE','GRAY_CASH_16_99','DOTDASH_CASH_42_18']
    result=codec.apply(packet,loaded)
    assert result.terminal[0].cash_per_share==59.17
    assert result.bars is packet.bars and result.meta is packet.meta
    assert result.terminal[0].delivered_security_id is None and loaded.held_multileg_supported is False
    value=state();obj=SimpleNamespace(**value)
    start=codec.before(obj,'2021-12-01');codec.after(obj,'2021-12-01',start)
    assert codec.zero_value_checks==[{'session':'2021-12-01','no_source_financial_value_added':True}]


def test_wrong_native_preimage_refuses():
    from dataclasses import replace
    codec,loaded,packet,value=setup_codec()
    packet=replace(packet,terminal=(replace(packet.terminal[0],reference='changed'),))
    with pytest.raises(ValueError,match='EXACT_NATIVE_TERMINAL_PREIMAGE'):codec.apply(packet,loaded)


def test_unregistered_input_refuses():
    codec,loaded,packet,value=setup_codec();codec.objects=[]
    with pytest.raises(ValueError,match='REGISTERED_TYPED_INPUT'):codec.apply(packet,loaded)


def test_identical_preparation_does_not_duplicate_the_term():
    codec,loaded,packet,value=setup_codec()
    first=codec.apply(packet,loaded);second=codec.apply(packet,loaded)
    assert first.terminal==second.terminal and len(codec.applied)==1
    with pytest.raises(ValueError,match='NATIVE_TERMINAL_PREIMAGE'):codec.apply(first,loaded)


def test_marker_cannot_add_cash_or_shares():
    codec,loaded,packet,value=setup_codec();codec.apply(packet,loaded)
    value=state();obj=SimpleNamespace(**value);start=codec.before(obj,'2021-12-01')
    obj.ledger['events'].append({'security_id':m.MDP,'cash_delta':1,'shares_delta':0})
    with pytest.raises(ValueError,match='CANNOT_ADD_FINANCIAL_VALUE'):codec.after(obj,'2021-12-01',start)


def test_facts_cannot_be_changed_or_claim_held_capability():
    value=json.loads((CAP/m.SUPPLEMENT).read_bytes())
    for field,bad in [('aggregate_cash_per_old_share','42.18'),('held_multileg_supported',True),('source_security_id','other')]:
        with pytest.raises(ValueError):m.UnheldCashInput.model_validate({**value,field:bad})


def zero_pair():
    from copy import deepcopy
    before={'base':{},'source_cursor':'2021-11-30','completed':986,'economics':{},'stats':{},'spy_base':{},'retries':{},
            'repairs':[{'sha256':str(i)} for i in range(13)],'journals':{'watch':{'bytes':0},'daily':{'bytes':0}},'chain':'a'*64}
    run={'state':{'cash':'50000'},'state_sha256':m.digest({'cash':'50000'}),'input_sha256':m.digest({'base':{},'repairs':before['repairs']})}
    run['checkpoint_sha256']=m.digest(run);before['run']=run;before['sha256']=m.digest(before)
    after=deepcopy(before);overlay='b'*64
    desc={'filename':overlay+'.json','sha256':overlay,'resume_session':before['source_cursor'],'predecessor_checkpoint_sha256':run['checkpoint_sha256']}
    after['repairs'].append(desc);after['run']['input_sha256']=m.digest({'base':{},'repairs':after['repairs']})
    after['run']['checkpoint_sha256']=m.digest({k:v for k,v in after['run'].items() if k!='checkpoint_sha256'})
    event={'schema':'research.pooled-action-successor/1','predecessor_checkpoint_sha256':run['checkpoint_sha256'],
           'unchanged_through':before['source_cursor'],'earliest_affected_session':'2021-12-01',
           'state_sha256':run['state_sha256'],'overlay':desc,'predecessor_input_sha256':run['input_sha256'],
           'successor_input_sha256':after['run']['input_sha256']}
    after['chain']=m.digest({'previous':before['chain'],'event':event});after['journals']['watch']['bytes']=1
    after['sha256']=m.digest({k:v for k,v in after.items() if k!='sha256'})
    return before,after,overlay,event


def test_actual_zero_adoption_accepts986_plus_one_input_only():
    before,after,overlay,event=zero_pair();gate=m.SourceGate(before,Path('old'),Path('out'))
    assert gate.allow(after,overlay,'2021-12-01')==event


@pytest.mark.parametrize('changed',['state','completed'])
def test_zero_adoption_cannot_advance_financial_state(changed):
    before,after,overlay,event=zero_pair();gate=m.SourceGate(before,Path('old'),Path('out'))
    if changed=='state':after['run']['state']['cash']='50001'
    else:after['completed']+=1
    with pytest.raises(ValueError):gate.allow(after,overlay,'2021-12-01')
