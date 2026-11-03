"""Targeted continuation, identity and first-transition postcondition checks."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system_campaign_p01_discovery_suffix_parent as parent
import system_campaign_p01_discovery_suffix_replay as replay
import system_campaign_p01_discovery_suffix_job as job
import system_campaign_p01_discovery_anchors as anchors_module
from system_campaign_discovery_context import CHECKPOINT,TAINT,digest,encoded


def saved_pair():
    state=dict(last_processed_session='2021-01-29',wealth_core=dict(cash=50.0))
    run=dict(schema='STUB_ONLY',state=state,state_sha256=digest(state),input_sha256='1'*64)
    run['checkpoint_sha256']=digest(run)
    empty=dict(bytes=0,prefix_sha256=hashlib.sha256(b'').hexdigest(),last_record_sha256=None)
    events=dict(bytes=0,prefix_sha256=hashlib.sha256(b'').hexdigest(),rows=0,chain_sha256='2'*64)
    cp=dict(schema=CHECKPOINT,authority=TAINT,financial_authority=False,account_performance_computed=False,
        source_cursor='2021-01-29',discovery_transitions=356,strict_parent_outer_sha256='3'*64,
        runtime_checkpoint=run,journals={n:dict(empty) for n in ('daily','watch','formation','monthly')},
        events=events,event_chain_sha256='2'*64,transition_chain_sha256='4'*64)
    spec=dict(strict_parent_outer_sha256='3'*64,selected_session='2021-01-29',transitions=356,
        journals=deepcopy(cp['journals']),events=deepcopy(events),transition_chain_sha256='4'*64,
        runtime_checkpoint_sha256=run['checkpoint_sha256'],state_sha256=run['state_sha256'],input_sha256='1'*64)
    return cp,spec


def test_saved_diagnostic_identity_content_and_prefixes_are_bound():
    cp,spec=saved_pair();assert parent.validate_checkpoint(cp,spec) is cp
    for key,value in [('source_cursor','2021-02-01'),('discovery_transitions',357),('financial_authority',True)]:
        bad=deepcopy(cp);bad[key]=value
        with pytest.raises(ValueError):parent.validate_checkpoint(bad,spec)
    cp['runtime_checkpoint']['state']['wealth_core']['cash']+=1
    with pytest.raises(ValueError,match='INNER_STATE_INPUT'):parent.validate_checkpoint(cp,spec)


@pytest.mark.parametrize('raw',[b'changed\n',b'{}\nunsent\n',b'{}'])
def test_changed_prefix_or_uncommitted_tail_is_not_silently_truncated(raw):
    original=b'{}\n';entry=dict(bytes=len(original),prefix_sha256=hashlib.sha256(original).hexdigest())
    with pytest.raises(ValueError,match='COMMITTED_PREFIX_ZERO_TAIL'):parent.verify_stream(raw,entry)


def test_actual_original_replay_ast_has_only_explicit_suffix_sites():
    raw=replay.exact_raw(replay.original)
    iterator=ast.unparse(replay.iterator_tree(raw));body=ast.unparse(replay.suffix_tree(raw))
    assert "runtime.restore(saved['runtime_checkpoint']" in iterator
    assert "old.verify(parent['journals'])" in iterator
    assert iterator.count('anchors.observe(packet)')==1
    assert 'observed = list(old_days)' in body and "chain = saved['transition_chain_sha256']" in body
    assert 'complete = observed == full_wanted' in body
    assert 'len(full_wanted) - len(observed)' in body
    assert 'recovered_stream(book, saved)' in body and 'first.after(run, next_run)' in body
    assert "runtime.advance(run, published)" in body
    assert 'if len(observed) == len(old_days) + 1:' in body
    compile(replay.suffix_tree(raw),'<actual-suffix-static>','exec')


def test_worker_exact_previous_readonly_mount_and_entrypoint(monkeypatch,tmp_path):
    monkeypatch.setattr(job.os,'getuid',lambda:1001,raising=False)
    monkeypatch.setattr(job.os,'getgid',lambda:1001,raising=False)
    cmd=job.worker_command('capital-system-discovery-p01-suffix-worker-123-1',tmp_path/'source',tmp_path/'frozen',
        tmp_path/'out',tmp_path/'old',tmp_path/'previous')
    assert cmd[cmd.index('-B'):]==job.entrypoint()
    assert any('target=/previous,readonly' in v for v in cmd)
    assert '--network' in cmd and cmd[cmd.index('--network')+1]=='none'
    value=dict(Name='/capital-system-discovery-p01-suffix-worker-123-1',Image=job.EXECUTION_IMAGE,Id='1'*64,
        HostConfig=dict(NetworkMode='none',Memory=8*1024**3,MemorySwap=8*1024**3,NanoCpus=2000000000,
            PidsLimit=64,ReadonlyRootfs=True,CapDrop=['ALL'],SecurityOpt=['no-new-privileges']),
        Config=dict(Cmd=job.entrypoint(),WorkingDir='/variant',User='1001:1001',Env=[],
            Labels={'research.study':'full-system-search-20261029','research.role':'worker'}),
        Mounts=[dict(Destination=n,Type='bind',RW=n=='/out') for n in ('/variant','/frozen','/driver','/out','/old','/previous')])
    monkeypatch.setattr(job.inspector_source.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout=json.dumps([value]).encode()))
    assert job.inspect(value['Name'][1:],'1'*64)==value
    value['Mounts'][-1]['RW']=True
    with pytest.raises(ValueError,match='MOUNTS'):job.inspect(value['Name'][1:],'1'*64)


def fake_state():
    episode=dict(security_id='SYNTHETIC',slot_id=0,current_shares=2,entry_date='2020-01-02',entry_raw_open=5.)
    return dict(wealth_core=dict(episodes={'0':episode},slots={'0':'SYNTHETIC'},
        last_valid_mark_session={'SYNTHETIC':'2020-01-03'}),
        feed=dict(series={'SYNTHETIC':dict(signal_basis_anchor=['2020-01-03',6.,6.])}),ledger=dict(events=[]))


def first_case(tmp_path):
    before=fake_state();holder=SimpleNamespace(to_dict=lambda:deepcopy(before))
    guard=replay.FirstTransition(tmp_path,SimpleNamespace(commitment=lambda:dict(rows=1)),{}, {})
    guard.prepared=True;guard.affected=['SYNTHETIC'];guard.prior=deepcopy(before);guard.proof={}
    after=deepcopy(before)
    current=SimpleNamespace(state=holder)
    nxt=SimpleNamespace(state=SimpleNamespace(to_dict=lambda:deepcopy(after),state_hash='1'*64))
    return guard,current,nxt,after


def test_actual_first_transition_postconditions_allow_unrelated_work(tmp_path):
    guard,current,nxt,after=first_case(tmp_path)
    after['ledger']['events'].append(dict(security_id='OTHER',operation='FILL'))
    guard.after(current,nxt)
    assert guard.passed and json.loads((tmp_path/'retained-anchor-canonical-qualification.json').read_bytes())['no_current_quote_fill_or_settlement']


@pytest.mark.parametrize('mutation',['shares','slot','mark_date','anchor','settlement'])
def test_first_transition_rejects_economic_changes_to_carried_security(tmp_path,mutation):
    guard,current,nxt,after=first_case(tmp_path)
    if mutation=='shares':after['wealth_core']['episodes']['0']['current_shares']=3
    elif mutation=='slot':after['wealth_core']['slots']['0']='OTHER'
    elif mutation=='mark_date':after['wealth_core']['last_valid_mark_session']['SYNTHETIC']='2021-02-01'
    elif mutation=='anchor':after['feed']['series']['SYNTHETIC']['signal_basis_anchor'][1]=7.
    elif mutation=='settlement':after['ledger']['events'].append(dict(security_id='SYNTHETIC',operation='PAYMENT'))
    with pytest.raises(ValueError,match='P01_SUFFIX_'):guard.after(current,nxt)
    assert not guard.passed and not (tmp_path/'retained-anchor-canonical-qualification.json').exists()


def test_actual_position_guard_removal_falsifier(tmp_path):
    guard,current,nxt,after=first_case(tmp_path);after['wealth_core']['episodes']['0']['current_shares']=3
    owner,=[n for n in ast.parse(Path(replay.__file__).read_bytes()).body if isinstance(n,ast.ClassDef) and n.name=='FirstTransition']
    fn,=[n for n in owner.body if isinstance(n,ast.FunctionDef) and n.name=='after']
    for node in ast.walk(fn):
        if isinstance(node,ast.For):
            node.body=[n for n in node.body if not(isinstance(n,ast.Expr) and any(isinstance(v,ast.Constant)
                and v.value=='P01_SUFFIX_NO_ANCHOR_BASED_POSITION_REMOVAL_OR_SHARE_CHANGE' for v in ast.walk(n)))]
    scope=dict(vars(replay));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<actual-position-guard-removed>','exec'),scope)
    scope['after'](guard,current,nxt);assert guard.passed


def test_event_append_keeps_old_bytes_sequence_hash_and_transition_count(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parent))
    import test_discovery_context as stubs
    monkeypatch.setattr(replay.context_source,'hosted',lambda:None)
    previous=tmp_path/'old';previous.mkdir();out=tmp_path/'new';out.mkdir()
    old_event=dict(sequence=0,context=dict(bypass=True))
    old_chain=digest(dict(previous=digest(dict(authority=TAINT)),event=old_event))
    raw=encoded(dict(event=old_event,chain_sha256=old_chain))+b'\n'
    (previous/'discovery-events.jsonl').write_bytes(raw)
    saved=dict(events=dict(bytes=len(raw),prefix_sha256=hashlib.sha256(raw).hexdigest(),rows=1,chain_sha256=old_chain),
        discovery_transitions=356)
    value=replay.ContinuedContext(out,source_sha256='1'*64,previous=previous,saved=saved)
    value.bindings=stubs.bindings()
    with value as ctx:
        ctx.current=(stubs.prior(),stubs.Publication())
        ctx.emit('SYNTHETIC_SUFFIX_EVENT')
        assert ctx.sequence==2 and ctx.transitions==356 and ctx.tainted
        actual=(out/'discovery-events.jsonl').read_bytes()
        assert actual.startswith(raw) and ctx.commitment()['prefix_sha256']==hashlib.sha256(actual).hexdigest()
        assert json.loads(actual.splitlines()[-1])['event']['sequence']==1


def test_first_prepare_reproduces_old_refusal_and_requires_real_cached_quote(tmp_path):
    class OriginalRefusal(ValueError):pass
    context=anchors_module.RetainedAnchors(tmp_path,None,source_sha256='1'*64,input_sha256='3'*64)
    context.stream=(tmp_path/anchors_module.STREAM).open('xb')
    context.m=SimpleNamespace(adapter=SimpleNamespace(protected=lambda state:{'SYNTHETIC'},TemporalViolation=OriginalRefusal),
        VendorBar=lambda day,sid,ticker,raw,*a,signal_close:SimpleNamespace(session=day,security_id=sid,
            ticker=ticker,raw_close=raw,signal_close=signal_close))
    context.store(SimpleNamespace(session='2020-01-03',security_id='SYNTHETIC',ticker='SYNTHETIC',
        raw_close=6.,signal_close=6.),'FROZEN_SOURCE_PACKET')
    before=fake_state()
    state=SimpleNamespace(feed=before['feed'],last_processed_session='2021-01-29',data_version=1,
        state_hash='1'*64,to_dict=lambda:deepcopy(before))
    buffer=SimpleNamespace(current=SimpleNamespace(day='2021-02-01',bars=()),rings={},axis=['2021-01-29']*300)
    def original(*a,**k):raise OriginalRefusal('LIVE_ANCHOR_OUTSIDE_WINDOW: SYNTHETIC')
    context.original=original
    def corrected(*a,**k):
        bar=context.retained(buffer,state,'SYNTHETIC',state.feed['series']['SYNTHETIC']['signal_basis_anchor'])
        return SimpleNamespace(session='2021-02-01',bars=(),signal_basis_anchors={'SYNTHETIC':bar},
            window_features=dict(sessions=list(buffer.axis)))
    buffer.prepare=corrected
    try:
        guard=replay.FirstTransition(tmp_path,context,dict(runtime_checkpoint=dict(checkpoint_sha256='2'*64)),
            dict(next_session='2021-02-01'))
        published=guard.prepare(buffer,SimpleNamespace(state=state))
        assert guard.prepared and not guard.passed and published.bars==()
        assert len(guard.proof['source_anchor_falsifiers'])==3 and context.commitment()['rows']==1
    finally:context.stream.close()
