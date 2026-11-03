"""Pure metadata, packet and role seams; no canonical runtime execution."""
from copy import deepcopy
from dataclasses import dataclass,replace
import inspect
import json
from pathlib import Path
import sys
from types import SimpleNamespace,ModuleType

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import p01_factual_batch_contract as c
import p01_factual_batch_codec as codec
import p01_factual_batch_guard as guard
import p01_factual_batch_pause as pause


def state(episodes=None,pending=None,selected=None):
    return SimpleNamespace(wealth_core={'episodes':episodes or {}},pending=pending or [],
                           median5={'selected':selected or []})


def action(ticker):return next(a for a in c.facts()['records'] if a['source_ticker']==ticker)


def episode(a,current=20,initial=20,**changes):
    return dict(security_id=a['source_security_id'],current_shares=current,initial_shares=initial,
                exit_pending=False,**changes)


def test_exact_eighteen_source_bound_records_and_private_preimages_absent():
    v=c.document();assert len(v['actions'])==18 and c.specification()['measured_closes']==526
    assert sum(a['exchange_ratio'] is not None for a in v['actions'])==4
    assert v['source_boundary_reemitted'] is False and v['financial_source_516_unchanged'] is True
    for a in v['actions']:
        assert a['cash_in_lieu_price_per_delivered_share'] is None
        assert all(set(n)=={'session','sha256'} for n in a['native_events'])
        assert 'current_shares' not in a and 'raw_open' not in a


def test_static_input_exact_bytes_and_wrong_parent_mutations_refuse(tmp_path):
    raw=c.encoded(c.document());p=tmp_path/'input.json';p.write_bytes(raw)
    value=c.parse(p,resume_session='2020-02-04',predecessor_checkpoint_sha256=c.INNER)
    assert value.sha256==c.sha(raw)
    assert value.model_dump(by_alias=True)==c.document()
    with pytest.raises(ValueError):c.parse(p,resume_session='2020-02-03',predecessor_checkpoint_sha256=c.INNER)
    with pytest.raises(ValueError):c.parse(p,resume_session='2020-02-04',predecessor_checkpoint_sha256='0'*64)
    v=json.loads(raw);v['actions'][0]['cash_per_share']='999';p.write_bytes(c.encoded(v))
    with pytest.raises(ValueError):c.parse(p,resume_session='2020-02-04',predecessor_checkpoint_sha256=c.INNER)
    p.write_bytes(raw.rstrip(b'\n'))
    with pytest.raises(ValueError):c.parse(p,resume_session='2020-02-04',predecessor_checkpoint_sha256=c.INNER)


@pytest.mark.parametrize('ticker',['WLH','VSLR','BMCH','WPX'])
def test_known_clock_whole_stock_scope(ticker):
    a=action(ticker);q=__import__('fractions').Fraction(a['exchange_ratio']).denominator
    s=state({'0':episode(a,q,q)})
    assert guard.require_scope(s,a)['episodes']==s.wealth_core['episodes']


def test_holder_whole_exact_episode_fractions_supported_without_reference_rounding():
    a=action('VSLR');s=state({'0':episode(a,10,20),'1':episode(a,10,20)})
    assert guard.require_scope(s,a)['episodes']==s.wealth_core['episodes']
    s.wealth_core['episodes']['1']['initial_shares']=10
    with pytest.raises(ValueError,match='INITIAL_REFERENCE'):guard.require_scope(s,a)


def test_aggregate_fraction_and_inexact_allocation_refuse():
    a=action('VSLR')
    with pytest.raises(ValueError,match='HOLDER_ENTITLEMENT'):guard.require_scope(state({'0':episode(a,1,20)}),a)
    # Whole aggregate 11, but first binary64 allocation 0.55 is inexact.
    s=state({'0':episode(a,1,20),'1':episode(a,19,20)})
    with pytest.raises(ValueError,match='EPISODE_ALLOCATION'):guard.require_scope(s,a)


@pytest.mark.parametrize('operation',['OPEN_SLOT_POSITION','CLOSE_POSITION'])
def test_every_source_pending_intent_refuses(operation):
    a=action('WLH');s=state(pending=[dict(security_id=a['source_security_id'],operation=operation,
                                        intended_dollars='100',signal_session='2026-01-01')])
    with pytest.raises(ValueError,match='SOURCE_PENDING'):guard.require_scope(s,a)


def test_source_exit_flag_refuses_with_no_pending_order():
    a=action('WLH');e=episode(a,5,5);e['exit_pending']=True
    with pytest.raises(ValueError,match='EXIT_FLAG'):guard.require_scope(state({'0':e}),a)


def test_target_only_holding_pending_and_flag_are_not_source_scope():
    a=action('WLH');target={'security_id':a['delivered_security_id'],'exit_pending':True}
    s=state({'0':target},[{'security_id':a['delivered_security_id'],'operation':'CLOSE_POSITION'}])
    assert guard.require_scope(s,a)['pending']==s.pending


@pytest.mark.parametrize('ticker',['UFS','MSP','CTXS','KAMN','MDC','SHCO'])
def test_date_only_market_clock_cannot_settle_actual_source_holding(ticker):
    a=action(ticker)
    assert a['clock_scope']=='DAILY_MARKET_UNHELD_SOURCE'
    with pytest.raises(ValueError,match='DAILY_MARKET_CLOCK'):guard.require_scope(state({'0':episode(a)}),a)


@dataclass(frozen=True)
class Event:
    session:str
    security_id:str
    kind:str='CASH_MERGER'
    cash_per_share:float|None=None
    delivered_security_id:str|None=None
    delivered_ticker:str|None=None
    delivered_issuer_id:str|None=None
    exchange_ratio:str|None=None
    cash_in_lieu_price_per_delivered_share:None=None
    reference:str|None=None
    entitlement_aggregation:str='HOLDER'
    def completeness(self,q):return True,None


@dataclass(frozen=True)
class Packet:
    day:str
    terminal:tuple
    bars:object
    windows:object
    cash:object
    spins:object


@pytest.fixture
def seam(monkeypatch,tmp_path):
    a=deepcopy(action('WLH'));n=Event(a['native_events'][0]['session'],a['source_security_id'],reference='SYNTHETIC_NATIVE')
    a['native_events'][0]['sha256']=c.digest(codec.material(n))
    expected={'schema':c.SCHEMA,'actions':[a]}
    monkeypatch.setattr(codec,'document',lambda:deepcopy(expected))
    module=ModuleType('stock_strategy_shared.wealth_core.terminal');module.terminal_terms_from_dict=lambda v:Event(**v)
    monkeypatch.setitem(sys.modules,module.__name__,module)
    obj=SimpleNamespace(model_dump=lambda **kwargs:deepcopy(expected))
    monkeypatch.setattr(codec,'BatchInput',SimpleNamespace) # a registered object, never real Core
    seam=codec.InputCodec({n.session:(n,)})
    seam.objects.append(obj);seam.original_apply=lambda packet,loaded:packet
    packet=Packet(n.session,(n,),object(),object(),object(),object())
    return a,n,seam,obj,packet


def test_codec_moves_only_exact_native_terminal_and_reinserts_economic_term(seam):
    a,n,co,obj,p=seam;out=co.apply(p,obj)
    assert out.terminal==() and all(getattr(out,f) is getattr(p,f) for f in ('bars','windows','cash','spins'))
    economic=replace(p,day=a['economic_session'],terminal=())
    inserted=co.apply(economic,obj)
    assert [codec.material(v) for v in inserted.terminal]==[c.term(a)]
    assert all(getattr(inserted,f) is getattr(economic,f) for f in ('bars','windows','cash','spins'))


@pytest.mark.parametrize('mutation',['missing','changed','duplicate','collision','instance'])
def test_codec_preimage_and_registered_identity_falsifiers(seam,mutation):
    a,n,co,obj,p=seam
    if mutation=='missing':p=replace(p,terminal=())
    elif mutation=='changed':p=replace(p,terminal=(replace(n,reference='CHANGED'),))
    elif mutation=='duplicate':p=replace(p,terminal=(n,n))
    elif mutation=='collision':p=replace(p,day=a['economic_session'])
    else:obj=deepcopy(obj)
    with pytest.raises(ValueError):co.apply(p,obj)


def test_guard_writes_actual_pre_event_before_source_scope_refusal(tmp_path):
    a=action('WLH');g=guard.ActionGuard(tmp_path);calls=[]
    g.pre_event=lambda run,day:calls.append(('checkpoint',day))
    g.original_advance=lambda *args:calls.append(('advanced',))
    e=episode(a,5,5);e['exit_pending']=True
    published=SimpleNamespace(session=a['economic_session'],terminal_events=(Event(**c.term(a)),))
    with pytest.raises(ValueError,match='EXIT_FLAG'):g.advance(SimpleNamespace(state=state({'0':e})),published)
    assert calls==[('checkpoint',a['economic_session'])]


def test_guard_target_roles_require_actual_component_proof(tmp_path):
    a=action('WLH');g=guard.ActionGuard(tmp_path);g.pre_event=lambda *args:None
    g.original_advance=lambda *args:pytest.fail('advance before component proof')
    s=state({'0':{'security_id':a['delivered_security_id'],'exit_pending':True}})
    p=SimpleNamespace(session=a['economic_session'],terminal_events=(Event(**c.term(a)),))
    with pytest.raises(ValueError,match='TARGET_ROLE_INDEPENDENCE'):g.advance(SimpleNamespace(state=s),p)


def test_held_source_target_holding_is_separate_from_target_pending(tmp_path):
    from p01_factual_batch_review import action_scope
    a=action('VSLR');g=guard.ActionGuard(tmp_path,target_independence_qualified=True)
    g.pre_event=lambda *args:None;g.original_advance=lambda run,p:run
    s=state({'0':episode(a,20,20),'1':{'security_id':a['delivered_security_id'],'exit_pending':False}})
    run=SimpleNamespace(state=s)
    p=SimpleNamespace(session=a['economic_session'],terminal_events=(Event(**c.term(a)),))
    with pytest.raises(ValueError,match='HELD_SOURCE_TARGET_HOLDING_COMPONENT'):g.advance(run,p)
    g.held_target_holding_qualified=True
    assert g.advance(run,p) is run
    s.pending=[{'security_id':a['delivered_security_id'],'operation':'CLOSE_POSITION'}]
    with pytest.raises(ValueError,match='HELD_SOURCE_WITH_TARGET_PENDING'):g.advance(run,p)
    s.pending=[];s.wealth_core['episodes']['1']['exit_pending']=True
    with pytest.raises(ValueError,match='HELD_SOURCE_WITH_TARGET_EXIT_FLAG'):g.advance(run,p)
    wire=dict(wealth_core=s.wealth_core,pending=s.pending,median5=s.median5)
    with pytest.raises(ValueError,match='HELD_SOURCE_TARGET_EXIT_FLAG'):action_scope(wire,a,True,True)
    # Unheld source plus target-only flag remains the independent supported case.
    del s.wealth_core['episodes']['0']
    assert g.advance(run,p) is run
    assert action_scope(wire,a,True,True)['source_held'] is False


def test_verified_full_pre_event_checkpoint_is_current_before_guard(tmp_path,monkeypatch):
    base={'sources':{'SYNTHETIC.py':'0'*64},'policy':'SYNTHETIC'};repairs=[]
    expected={'checkpoint_sha256':'a'*64,'state_sha256':'b'*64,'input_sha256':c.digest(dict(base=base,repairs=repairs)),
              'state':{'last_processed_session':'2020-02-05'}}
    commitments={n:dict(bytes=0,prefix_sha256=c.sha(b''),last_record_sha256=None) for n in ('daily','formation','monthly','watch')}
    for n in commitments:(tmp_path/(n+'.jsonl')).write_bytes(b'')
    cp=dict(base=base,repairs=repairs,run=expected,source_cursor='2020-02-05',journals=commitments)
    cp['sha256']=c.digest(cp)
    folder=tmp_path/'pre-event';folder.mkdir();(folder/'2020-02-06-synthetic.json.gz').write_bytes(b'STUB')
    module=ModuleType('research.pooled_vacancy_funding');module.journal=SimpleNamespace(read_checkpoint=lambda path:deepcopy(cp))
    monkeypatch.setitem(sys.modules,module.__name__,module)
    g=guard.ActionGuard(tmp_path);writes=[];order=[]
    g.runtime=SimpleNamespace(checkpoint=lambda run:expected,restore=lambda *args,**kwargs:object())
    def write_current(path,value):
        path.write_bytes(b'SYNTHETIC_CURRENT');writes.append((path,value));order.append('current')
    g.backtest=SimpleNamespace(write_checkpoint=write_current,source_files=lambda:base['sources'])
    g.journal=module.journal
    def original_archive(path,value):order.append('archive');return folder/'2020-02-06-synthetic.json.gz'
    g.original_archive=original_archive
    run=SimpleNamespace(state=SimpleNamespace(last_processed_session='2020-02-05'),policy='SYNTHETIC',input_sha256=expected['input_sha256'])
    g.archive(folder/'2020-02-06.json.gz',cp)
    assert order==['archive','current']
    proof=g.pre_event(run,'2020-02-06')
    assert writes==[(tmp_path/'checkpoint.json.gz',cp)] and proof['current_saved_identical_before_guard'] is True
    assert proof['current_file']==dict(bytes=17,sha256=c.sha(b'SYNTHETIC_CURRENT'))
    bad=deepcopy(cp);bad['journals']['watch']['prefix_sha256']='0'*64
    bad['sha256']=c.digest({k:v for k,v in bad.items() if k!='sha256'})
    with pytest.raises(ValueError,match='EVERY_ACTUAL_JOURNAL_PREFIX'):g.archive(folder/'2020-02-06.json.gz',bad)
    assert len(writes)==1
    g.archive(tmp_path/'month-end/2020-02-28.json.gz',cp)
    assert len(writes)==1 # unrelated canonical archive delegates unchanged
    (tmp_path/'watch.jsonl').write_bytes(b'SYNTHETIC_ACTUAL_UNSENT_WATCH_TAIL\n')
    g.pre_event(run,'2020-02-06')
    assert (tmp_path/'watch.jsonl').read_bytes()==b'SYNTHETIC_ACTUAL_UNSENT_WATCH_TAIL\n'
    g.runtime.checkpoint=lambda run:{**expected,'state_sha256':'wrong-restore'}
    with pytest.raises(ValueError,match='FULL_RESTORE'):g.archive(folder/'2020-02-06.json.gz',cp)
    assert len(writes)==1
    g.runtime.checkpoint=lambda run:expected
    cp['run']['state_sha256']='c'*64
    with pytest.raises(ValueError):g.pre_event(run,'2020-02-06')
    assert len(writes)==1


def test_epoch_pause_refuses_state_change_before_write(tmp_path):
    parent={'run':{'state':{'cash':'1'}}};p=pause.EpochPause(parent,tmp_path/'cp.gz')
    calls=[];p.original_write=lambda *args:calls.append(args)
    changed=deepcopy(parent);changed['run']['state']['cash']='2'
    with pytest.raises(ValueError):p.write(tmp_path/'cp.gz',changed)
    assert not calls
    with pytest.raises(ValueError):p.advance(None,None)


def test_hosted_main_uses_two_canonical_sessions_and_fresh_own526():
    source=(c.HERE/'p01_factual_batch_run.py').read_text()
    assert 'backtest.main(args+binding.source_args)' in source
    assert "original_own526_resumed_fresh=True" in source
    assert "current['sha256']==qualified['input_zero_outer_sha256']" in source
    assert "source_epoch_boundary_reemitted=False" in source
    assert "raw==encoded(document())" in source
