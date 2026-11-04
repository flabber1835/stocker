"""Retained proof seed/source/AST and synthetic suffix checks; no financial replay."""
import ast
from copy import deepcopy
import gzip,json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_uncertainty as u
import system_campaign_financial_branches as b
import system_campaign_financial_partial as p
import system_campaign_financial_future as f
from system_campaign_uncertainty_math import Interval,RollingWitnessBounds,growth


def parent_spec():
    spec=p.root_spec('P07','c3b3695de955721404aa8b1eb04f2f272efa4f3bd01c8bdd5fac10b92995811c')
    return dict(sha256=spec['outer_sha256'],completed=503,source_cursor='2019-12-31',base=deepcopy(spec['base'])),spec


def test_exact_qualified_503_root_and_original_branch_source_are_accepted():
    cp,spec=parent_spec();before=deepcopy((cp,spec))
    assert len(u.retained_contract(cp,spec))==6 and (cp,spec)==before


def test_own756_root_registers_all302_certificates_and_preserves628_history():
    spec=p.root_spec('P07','f7f86bf917f7d2718c8e360a4e1d1de2c2d90d6dd94406e581c6712201a8b776')
    cp=dict(sha256=spec['outer_sha256'],completed=spec['measured_closes'],source_cursor=spec['selected_session'],base=deepcopy(spec['base']))
    assert cp['completed']==756 and len(u.retained_contract(cp,spec))==6
    assert u.RETAINED_PROOF_SEEDS[spec['root_admission_sha256']]==dict(completed=756,source_cursor='2020-12-31',rows=302,new_rows=128,retained_rows=174)
    assert p.root_spec('P07',spec['root_admission']['parent_root_admission_sha256'])['measured_closes']==628


def test_new_543_admission_has_its_separately_registered_89_row_seed():
    spec=p.root_spec('P07','46fd68cb0d747c8c5ca004e979f49f89c02d505ef69069af7e086bd18b18268d')
    cp=dict(sha256=spec['outer_sha256'],completed=spec['measured_closes'],
            source_cursor=spec['selected_session'],base=deepcopy(spec['base']))
    assert cp['completed']==543
    assert len(u.retained_contract(cp,spec))==6
    phase=u.RETAINED_PROOF_SEEDS[spec['root_admission_sha256']]
    assert phase==dict(completed=543,source_cursor='2020-02-28',rows=89,new_rows=40,retained_rows=49)
    with pytest.raises(ValueError):u.retained_contract(dict(cp,completed=544),spec)


@pytest.mark.parametrize('key,value',[('completed',504),('source_cursor','2020-01-02'),('sha256','0'*64)])
def test_other_parent_or_tail_cannot_seed_retained_proof(key,value):
    cp,spec=parent_spec();cp[key]=value
    with pytest.raises(ValueError):u.retained_contract(cp,spec)


def test_parent_guard_removal_falsifier():
    cp,spec=parent_spec();cp['completed']=504
    with pytest.raises(ValueError):u.retained_contract(cp,spec)
    fn=next(n for n in ast.parse(Path(u.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='retained_contract')
    guard=next(n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and n.value.func.id=='need')
    fn.body.remove(guard);ns=dict(vars(u));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-admitted-proof-parent-guard>','exec'),ns)
    assert len(ns['retained_contract'](cp,spec))==6


def test_actual_admitted_seed_identity_can_resume_without_reexecuting_old_proofs():
    old=Path('C:/Users/mbron/.codex/visualizations/2026/11/03/01a1a1b6-c8b7-7800-b947-f49191928329/financial-runs-20261103-013/capture-P07-13293585860-001/verified-output')
    if not old.exists():pytest.skip('private authenticated DATA fixture is local-only')
    old=Path('\\\\?\\'+str(old.resolve()));cp=json.loads(gzip.decompress((old/'book/checkpoint.json.gz').read_bytes()))
    hashes,rows,raw=u.retained_seed(old,cp,p.root_spec('P07','c3b3695de955721404aa8b1eb04f2f272efa4f3bd01c8bdd5fac10b92995811c'))
    assert len(hashes)==6 and len(rows)==49 and rows[-1]['session']=='2019-12-31'
    assert json.loads(raw)['actual_divergent_decisions_refused'] is True


def test_actual_new_admitted_seed_keeps_all89_rows_and_closed_original_qualification():
    old=Path('C:/Users/mbron/.codex/visualizations/2026/11/03/01a1a1b6-c8b7-7800-b947-f49191928329/financial-runs-20261104-019/capture-P07-13299422018-001/verified-output')
    if not old.exists():pytest.skip('private authenticated DATA fixture is local-only')
    old=Path('\\\\?\\'+str(old.resolve()));cp=json.loads(gzip.decompress((old/'book/checkpoint.json.gz').read_bytes()))
    hashes,rows,raw=u.retained_seed(old,cp,p.root_spec('P07','46fd68cb0d747c8c5ca004e979f49f89c02d505ef69069af7e086bd18b18268d'))
    assert len(hashes)==6 and len(rows)==89 and rows[-1]['session']=='2020-02-28'
    assert json.loads(raw)['historical_financial_sessions_advanced']==0


def test_actual_current565_admission_retains111_committed_rows_without_replaying_old_transitions():
    old=Path('C:/Users/mbron/.codex/visualizations/2026/11/03/01a1a1b6-c8b7-7800-b947-f49191928329/financial-runs-20261104-035/capture-P07-13315213171-001/verified-output')
    if not old.exists():pytest.skip('private authenticated DATA fixture is local-only')
    old=Path('\\\\?\\'+str(old.resolve()));cp=json.loads(gzip.decompress((old/'book/checkpoint.json.gz').read_bytes()))
    hashes,rows,raw=u.retained_seed(old,cp,p.root_spec('P07','30552e338938b213e0dcfe5ef06ca6defcca8d0627126cf39cfd63b2982c9e03'))
    assert len(hashes)==6 and len(rows)==111 and rows[-1]['session']=='2020-03-31'
    assert json.loads(raw)['historical_financial_sessions_advanced']==0


def test_actual_historical628_admission_retains174_committed_rows_without_old_replay():
    old=Path('C:/Users/mbron/.codex/visualizations/2026/11/03/01a1a1b6-c8b7-7800-b947-f49191928329/financial-runs-20261104-042/capture-P07-13318715488-001/verified-output')
    if not old.exists():pytest.skip('private authenticated DATA fixture is local-only')
    old=Path('\\\\?\\'+str(old.resolve()));cp=json.loads(gzip.decompress((old/'book/checkpoint.json.gz').read_bytes()))
    hashes,rows,raw=u.retained_seed(old,cp,p.root_spec('P07','2293655ea9e4c520c66e016a33c9d33b78f12ceb09c50a371bc84b76c0eef543'))
    assert len(hashes)==6 and len(rows)==174 and rows[-1]['session']=='2020-06-30'
    assert json.loads(raw)['historical_financial_sessions_advanced']==0


def test_actual_current756_admission_retains_only302_committed_certificates():
    old=Path('C:/Users/mbron/.codex/visualizations/2026/11/03/01a1a1b6-c8b7-7800-b947-f49191928329/financial-runs-20261104-098/capture-P07-13335581618-001/verified-output')
    if not old.exists():pytest.skip('private authenticated DATA fixture is local-only')
    old=Path('\\\\?\\'+str(old.resolve()));cp=json.loads(gzip.decompress((old/'book/checkpoint.json.gz').read_bytes()))
    hashes,rows,raw=u.retained_seed(old,cp,p.root_spec('P07','f7f86bf917f7d2718c8e360a4e1d1de2c2d90d6dd94406e581c6712201a8b776'))
    assert len(hashes)==6 and len(rows)==302 and rows[-1]['session']=='2020-12-31'
    assert json.loads(raw)['historical_financial_sessions_advanced']==0


def test_frozen_review_loop_undo_recovers_every_original_predicate():
    review=next(n for n in ast.parse(Path(b.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='review')
    original=next(n for n in review.body if isinstance(n,ast.For) and ast.unparse(n.target)=='(index, row)')
    tree=u.suffix_review_tree();adapted=tree.body[0]
    assert ast.unparse(adapted.iter)=='enumerate(rows, start=retained_count)'
    adapted.iter=ast.parse('enumerate(rows)',mode='eval').body
    assert ast.dump(adapted,include_attributes=False)==ast.dump(original,include_attributes=False)
    assert 'BRANCH_EXACT_CURRENT_REPRESENTATIVE_STATE' in ast.unparse(tree.body[1])


def fixture():
    prior=dict(version=2,episode=False,latched=False,full_streak=1,recent_positive_streak=0,
        previous_native=1.,previous_desired=1.,effective_native=1.,champion_audit=dict(episodes=0,concordance_releases=0),
        witness_nav=[1.]*41,last_session='2019-12-31')
    parent=dict(completed=503,source_cursor='2019-12-31',run=dict(state=dict(median5=deepcopy(prior))))
    math=RollingWitnessBounds(prior['witness_nav']);seed=[dict(math=math.snapshot(),possible_after=[b.discrete(prior)])]
    factor=growth([Interval.point(0.)]);math.advance(factor,1.)
    bounds={f'recent_r{n}':math.period(n) for n in (20,40)}
    def recover(**kwargs):
        state=deepcopy(kwargs['state']);state['full_streak']+=1
        return state,dict(desired_allocation=1.,reason='SYNTHETIC')
    actual=deepcopy(prior);actual['last_session']='2020-01-02'
    scalars=dict(native=1.,wc_drawdown=0.,spy_r20=0.,wc_r20=0.,recent_r20=0.,recent_r40=0.)
    (after,decision),following,leaves=b.cloud(recover,dict(scalars,state=actual),bounds,seed[-1]['possible_after'])
    row=dict(session='2020-01-02',before=b.discrete(prior),after=b.discrete(after),possible_before=seed[-1]['possible_after'],
        possible_after=following,every_reachable_canonical_decision_identical=True,representative_is_not_a_valuation=True,
        owned_position=False,pending_order=False,scalar_inputs=scalars,decision=decision,branches=leaves,
        intervals={k:v.pair() for k,v in bounds.items()},math=math.snapshot(),material=dict(
         rows=[dict(security_id='synthetic',prior=1.,current=[1.,1.])],factor=factor.pair(),representative_nav=1.,
         observed=dict(recent_r20=0.,recent_r40=0.)))
    current=dict(completed=504,source_cursor=row['session'],run=dict(state=dict(median5=after)))
    financial={row['session']:dict(decision=dict(ldrc=decision,native_target_core_exposure=1.))}
    kwargs=dict(median5=SimpleNamespace(fresh=lambda **kwargs:deepcopy(prior)),champion_config=SimpleNamespace(recover=recover))
    return parent,current,seed,[row],financial,kwargs


def test_only_new_synthetic_rows_are_checked_with_entire_frozen_loop():
    parent,current,seed,rows,financial,kwargs=fixture();before=deepcopy((parent,current,seed,rows,financial))
    result=u.review_new_rows(parent,current,seed,rows,financial,**kwargs)
    assert result==dict(rows=1,exhaustive_leaves=1,maximum_possible_states=1,prior_proof_rows_reexecuted=0,every_reachable_decision_identical=True)
    assert (parent,current,seed,rows,financial)==before


@pytest.mark.parametrize('change',['factor','interval','before','possible','branch','decision','math','scope','final'])
def test_new_math_branches_or_financial_identity_mismatch_refuses(change):
    parent,current,seed,rows,financial,kwargs=fixture();row=rows[0]
    if change=='factor':row['material']['factor'][0]=.9
    elif change=='interval':row['intervals']['recent_r20'][0]=-.1
    elif change=='before':row['before']['full_streak']=99
    elif change=='possible':row['possible_before']=[]
    elif change=='branch':row['branches']=[]
    elif change=='decision':row['decision']=dict(desired_allocation=0.,reason='OTHER')
    elif change=='math':row['math']['steps']=9
    elif change=='scope':current['completed']+=1
    else:current['run']['state']['median5']['full_streak']=9
    with pytest.raises(ValueError):u.review_new_rows(parent,current,seed,rows,financial,**kwargs)


def typed_book(tmp_path):
    (tmp_path/'book/repairs').mkdir(parents=True)
    (tmp_path/'hydrated-uncertainty-event.json').write_bytes(b'{"synthetic":true}\n')
    path=b.overlay(dict(source_cursor='2019-09-30',run=dict(checkpoint_sha256='a'*64)),tmp_path)
    raw=path.read_bytes();h=b.digest(json.loads(raw))
    import hashlib
    h=hashlib.sha256(raw).hexdigest();(tmp_path/'book/repairs'/(h+'.json')).write_bytes(raw)
    descriptor=dict(filename=h+'.json',sha256=h,resume_session='2019-09-30',predecessor_checkpoint_sha256='a'*64)
    codec=b.Codec(b.evidence(tmp_path));backtest=SimpleNamespace(load_repair=codec.load)
    return dict(repairs=[descriptor]),codec,backtest


def test_exact_same_active_model_codec_is_used_for_the_certificate(tmp_path):
    cp,codec,backtest=typed_book(tmp_path)
    assert u.active_codec(backtest,tmp_path,cp) is codec and len(codec.objects)==1


@pytest.mark.parametrize('change',['unbound','evidence','duplicate','digest'])
def test_different_codec_or_retained_model_identity_refuses(tmp_path,change):
    cp,codec,backtest=typed_book(tmp_path)
    if change=='unbound':backtest.load_repair=lambda *args:None
    elif change=='evidence':codec.evidence=[]
    elif change=='duplicate':cp['repairs'].append(deepcopy(cp['repairs'][0]))
    else:cp['repairs'][0]['sha256']='0'*64
    with pytest.raises(ValueError):u.active_codec(backtest,tmp_path,cp)


def test_mdco_shared_selector_preserves_complete_original_term():
    _,_,terms=f.selected('P07',cursor='2019-12-31');t=next(v for v in terms if v['ticker']=='MDCO')
    catalog=json.loads((f.HERE/'system-campaign-medicines-terminal-facts.json').read_bytes())
    assert t['added']==catalog['terms'][0]['added'] and t['identity_witness']==catalog['identity_witness']
    assert t['last_trading_session']=='2020-01-03' and t['added']['session']=='2020-01-06'
    assert f.suppressions(dict(source_cursor='2019-12-31'),terms)[0]==dict(
        session='2020-01-03',security_id=t['security_id'],term_sha256=t['native_term_sha256'])
    assert [v['ticker'] for v in terms]==['MDCO','ARQL']
    with pytest.raises(ValueError):f.selected('P07',cursor='2020-01-03')


def test_new_scope_guard_removal_falsifier():
    parent,current,seed,rows,financial,kwargs=fixture();current['completed']+=1
    with pytest.raises(ValueError):u.review_new_rows(parent,current,seed,rows,financial,**kwargs)
    fn=next(n for n in ast.parse(Path(u.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='review_new_rows')
    guard=next(n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and n.value.func.id=='need')
    fn.body.remove(guard);ns=dict(vars(u));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-new-proof-scope-guard>','exec'),ns)
    assert ns['review_new_rows'](parent,current,seed,rows,financial,**kwargs)['rows']==1


def test_frozen_review_source_guard_removal_falsifier(tmp_path,monkeypatch):
    name='system_campaign_financial_branches.py';(tmp_path/name).write_bytes(Path(b.__file__).read_bytes()+b'\n')
    monkeypatch.setattr(u,'HERE',tmp_path)
    with pytest.raises(ValueError):u.suffix_review_tree()
    fn=next(n for n in ast.parse(Path(u.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='suffix_review_tree')
    guard=next(n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and n.value.func.id=='need')
    fn.body.remove(guard);ns=dict(vars(u));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-frozen-proof-source-guard>','exec'),ns)
    assert len(ns['suffix_review_tree']().body)==2


def test_mdco_phase_guard_removal_falsifier():
    with pytest.raises(ValueError):f.selected('P07',cursor='2020-01-03')
    fn=next(n for n in ast.parse(Path(f.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='selected')
    branch=next(n for n in fn.body if isinstance(n,ast.If) and ast.unparse(n.test)=="arm == 'P07'")
    branch.body[0]=ast.Pass();ns=dict(vars(f));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-mdco-phase-guard>','exec'),ns)
    assert ns['selected']('P07',cursor='2020-01-03')[2][0]['ticker']=='MDCO'


@pytest.mark.parametrize('unchanged',[False,True])
def test_retained_run_wires_one_future_adoption_and_the_entire_seed(tmp_path,monkeypatch,unchanged):
    from contextlib import nullcontext
    from types import ModuleType
    import system_campaign_alder_date_v2 as alder_module
    import system_campaign_p02_retained_run as dispatch
    import system_campaign_uncertainty_archive as archive
    import system_campaign_financial_resume as launcher
    old,out=tmp_path/'old',tmp_path/'out';old.mkdir();out.mkdir()
    native=object();codec=object();hashes={'synthetic':'a'*64};seed=[dict(chain_sha256='b'*64,possible_after=[{}]) for _ in range(49)]
    qualification=b'{"closed_qualification":true}\n'
    (old/'hydrated-alder-unresolved-date.json').write_bytes(b'{"unchanged_native":true}\n')
    (old/'hydrated-uncertainty-event.json').write_bytes(b'{"unchanged_event":true}\n')
    cp=dict(sha256='c'*64,completed=756,source_cursor='2020-12-31',repairs=[],run=dict(input_sha256='e'*64))
    spec=dict(root_admission_sha256=next(iter(u.UNCHANGED_INPUT_SEEDS))) if unchanged else object()
    calls=[];active=[]
    class Context:
        def __init__(self,name):self.name=name
        def __enter__(self):active.append(self.name);calls.append('enter:'+self.name);return self
        def __exit__(self,*args):assert active.pop()==self.name;calls.append('exit:'+self.name)
    class Alder(Context):
        def __init__(self,path):super().__init__('alder');self.native=native
        def hydrate(self,path):path.write_bytes((old/'hydrated-alder-unresolved-date.json').read_bytes())
    class Certificate(Context):
        def __init__(self,destination,selected_codec,selected_native,selected_hashes,*,seed:object,event_source):
            assert destination==out and selected_codec is codec and selected_native is native and selected_hashes is hashes
            assert len(seed)==49 and event_source==dict(unchanged_event=True)
            calls.append('entire-49-row-seed');super().__init__('certificate')
    class Gate(Context):
        def __init__(self,parent,book,destination,sha,earliest):
            assert not unchanged
            assert parent is cp and book==out/'book' and destination==out/'input-adoption'
            assert sha=='d'*64 and earliest=='2020-01-03';calls.append('one-future-adoption');super().__init__('gate')
    path=out/'future-financial-overlay.json'
    if not unchanged:path.write_bytes(b'{}')
    def main(args):
        assert args==(['synthetic-original'] if unchanged else ['synthetic-original','--repair-overlay',str(path)])
        assert active==(['proof','alder','dispatch','certificate','observer','execution'] if unchanged else ['alder','dispatch','gate','certificate','observer','execution','events'])
        calls.append('delegated-original-main');return 0
    module=ModuleType('research.pooled_vacancy_funding');module.backtest=SimpleNamespace(main=main)
    monkeypatch.setitem(sys.modules,module.__name__,module)
    monkeypatch.setattr(u,'hosted',lambda:None)
    monkeypatch.setattr(u,'retained_seed',lambda *args:(hashes,seed,qualification))
    monkeypatch.setattr(u,'active_codec',lambda *args:codec)
    monkeypatch.setattr(u,'proof_scope',lambda *args:Context('proof') if unchanged else nullcontext())
    monkeypatch.setattr(alder_module,'AlderDateV2',Alder)
    monkeypatch.setattr(dispatch,'idempotent_dispatch',lambda alder:Context('dispatch'))
    monkeypatch.setattr(archive,'preserve',lambda *args:calls.append('preserved-original-event-gzip'))
    monkeypatch.setattr(b,'Certificate',Certificate)
    def prepare(*args):
        assert not unchanged
        return path,SimpleNamespace(sha256='d'*64,earliest_affected_session='2020-01-03')
    monkeypatch.setattr(f,'prepare',prepare)
    def events(destination,arm,*,cp:object):
        assert not unchanged
        assert destination==out and arm=='P07' and cp is parent_for_events
        return Context('events')
    parent_for_events=cp
    monkeypatch.setattr(f,'ActualEvents',events)
    monkeypatch.setattr(launcher,'AdoptionGate',Gate)
    monkeypatch.setattr(u,'boundary',lambda *args:calls.append('verified-exact-new-neutral-boundary'))
    assert u.run_retained(cp,out,['synthetic-original'],Context('observer'),Context('execution'),spec,old)==0
    assert calls.count('one-future-adoption')==(0 if unchanged else 1)
    assert calls.count('entire-49-row-seed')==1 and active==[]
    if unchanged:
        assert calls[-1]=='exit:proof'
        assert json.loads((out/u.UNCHANGED_INPUT).read_bytes())['new_factual_overlay'] is False
        assert not path.exists() and not (out/u.MODEL_ADOPTION).exists()
    else:assert calls[-1]=='verified-exact-new-neutral-boundary'
    assert (out/'branch-controller-qualification.json').read_bytes()==qualification
    proof=json.loads((out/'retained-proof-admission/seed.json').read_bytes())
    assert proof['rows']==49 and proof['prior_qualification_reexecuted'] is False
    assert proof['prior_proof_rows_reexecuted']==0 and proof['new_date_or_model_adoption'] is False
