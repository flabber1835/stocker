"""Synthetic packet/byte-identity checks only; no local financial execution."""
import ast,gzip,hashlib,json
from dataclasses import asdict,replace
from pathlib import Path
import pytest
from forecast_tests.test_p02_alder import fixture,Packet
from system_campaign_p02_retained_run import idempotent_dispatch
from system_campaign_correlation_prefix import restore,seed
from system_campaign_facts import digest


def test_actual_v2_repeated_dispatch_is_exactly_idempotent(monkeypatch,tmp_path):
    alder,backtest,_=fixture(monkeypatch,tmp_path);packet=Packet('2019-10-22',())
    with alder,idempotent_dispatch(alder):
        first=backtest.apply_repair(packet,None)
        for _ in range(4):assert backtest.apply_repair(first,None)==first
        bad=replace(first,terminal=(replace(first.terminal[0],cash_per_share=18.),))
        with pytest.raises(ValueError,match='EXACT_ALREADY_INJECTED'):backtest.apply_repair(bad,None)
        assert packet.terminal==() and first.terminal[0].cash_per_share is None


def test_actual_dispatch_conflict_guard_removal_falsifier(monkeypatch,tmp_path):
    import system_campaign_p02_retained_run as module
    alder,backtest,_=fixture(monkeypatch,tmp_path);bad=Packet('2019-10-22',(replace(alder.native,session='2019-10-22',cash_per_share=18.),))
    with alder,idempotent_dispatch(alder):
        with pytest.raises(ValueError,match='EXACT_ALREADY_INJECTED'):backtest.apply_repair(bad,None)
    node=next(n for n in ast.parse(Path(module.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='idempotent_dispatch')
    apply=next(n for n in node.body if isinstance(n,ast.FunctionDef))
    branch=next(n for n in apply.body if isinstance(n,ast.If))
    branch.body=[n for n in branch.body if not any(isinstance(x,ast.Constant) and x.value=='P02_EXACT_ALREADY_INJECTED_UNRESOLVED_TERM' for x in ast.walk(n))]
    scope=dict(module.__dict__);exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<actual-dispatch-conflict-guard-removed>','exec'),scope)
    with alder,scope['idempotent_dispatch'](alder):assert backtest.apply_repair(bad,None).terminal[0].cash_per_share is None


def prefix_fixture(tmp_path):
    current=tmp_path/'current';source=tmp_path/'source';sha=lambda b:hashlib.sha256(b).hexdigest()
    financial=[{'session':'2019-09-27','state_sha256':'a'*64},{'session':'2019-09-30','state_sha256':'b'*64}]
    raw=b''.join((json.dumps(r)+'\n').encode() for r in financial);empty={'bytes':0,'prefix_sha256':sha(b'')}
    cp={'base':{'sources':{'x':'c'*64}},'source_cursor':'2019-09-30','sha256':'d'*64,'run':{'state_sha256':'b'*64},
        'journals':{'formation':empty,'daily':{'bytes':len(raw),'prefix_sha256':sha(raw)}}}
    for root in (current,source):
        (root/'book').mkdir(parents=True);(root/'book/daily.jsonl').write_bytes(raw);(root/'book/formation.jsonl').write_bytes(b'')
        (root/'book/checkpoint.json.gz').write_bytes(gzip.compress(json.dumps(cp).encode(),mtime=0));(root/'source-bindings.json').write_bytes(b'{}')
    chain=digest('system-optimization-002/raw-correlation/1');records=[]
    for r in financial:
        v={'session':r['session'],'next_state_sha256':r['state_sha256']};chain=digest({'previous':chain,'record':v});v['chain_sha256']=chain
        records.append((json.dumps(v)+'\n').encode())
    raw=b''.join(records);(source/'correlation-inputs.jsonl.gz').write_bytes(gzip.compress(raw,mtime=0))
    spec={'selected_file':{'sha256':sha((source/'book/checkpoint.json.gz').read_bytes())},'source_binding_sha256':sha(b'{}'),
        'outer_sha256':cp['sha256'],'artifact_id':1,'run_id':2,'zip_sha256':'e'*64}
    return current,source,spec,{'rows':2,'bytes':len(raw),'sha256':sha(raw)},cp


def test_derived_prefix_matches_every_committed_state_and_original_bytes(tmp_path):
    current,source,spec,expected,cp=prefix_fixture(tmp_path);before=(source/'correlation-inputs.jsonl.gz').read_bytes()
    proof=restore(current,source,tmp_path/'derived',spec,expected)
    assert proof['new_financial_sessions']==0 and proof['raw_prefix']==expected
    assert len(seed(current,cp,tmp_path/'derived/prefix.jsonl.gz'))==2
    assert (source/'correlation-inputs.jsonl.gz').read_bytes()==before


def test_wrong_ancestor_state_or_frozen_prefix_refuses(tmp_path):
    current,source,spec,expected,cp=prefix_fixture(tmp_path)
    with pytest.raises(ValueError,match='FROZEN_RAW_PREFIX'):restore(current,source,tmp_path/'bad',spec,{**expected,'rows':3})
    cp['run']['state_sha256']='f'*64;(current/'book/checkpoint.json.gz').write_bytes(gzip.compress(json.dumps(cp).encode()))
    with pytest.raises(ValueError,match='SAME_OWN_COMMITTED'):restore(current,source,tmp_path/'bad',spec,expected)


def test_missing_observer_for_nonempty_financial_prefix_refuses(tmp_path):
    from system_campaign_factual_run import correlation_seed
    with pytest.raises(ValueError,match='NONEMPTY_CORRELATION_PREFIX'):correlation_seed(tmp_path,{'journals':{'daily':{'bytes':1},'formation':{'bytes':0}}})
    assert correlation_seed(tmp_path,{'journals':{'daily':{'bytes':0},'formation':{'bytes':0}}})==[]


def test_actual_raw_prefix_commitment_guard_removal_falsifier(tmp_path):
    import system_campaign_correlation_prefix as module
    current,source,spec,expected,cp=prefix_fixture(tmp_path);wrong={**expected,'rows':3}
    with pytest.raises(ValueError,match='FROZEN_RAW_PREFIX'):restore(current,source,tmp_path/'real',spec,wrong)
    node=next(n for n in ast.parse(Path(module.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='restore')
    node.body=[n for n in node.body if not any(isinstance(x,ast.Constant) and x.value=='CORRELATION_FROZEN_RAW_PREFIX_COMMITMENT' for x in ast.walk(n))]
    scope=dict(module.__dict__);exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<actual-prefix-commitment-guard-removed>','exec'),scope)
    assert scope['restore'](current,source,tmp_path/'mutant',spec,wrong)['raw_prefix']['rows']==2


def test_actual_missing_prefix_guard_removal_falsifier(tmp_path):
    import system_campaign_factual_run as module
    cp={'journals':{'daily':{'bytes':1},'formation':{'bytes':0}}}
    with pytest.raises(ValueError,match='NONEMPTY_CORRELATION_PREFIX'):module.correlation_seed(tmp_path,cp)
    node=next(n for n in ast.parse(Path(module.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='correlation_seed')
    branch=next(n for n in node.body if isinstance(n,ast.If) and any(isinstance(x,ast.Constant) and x.value=='FACTUAL_NONEMPTY_CORRELATION_PREFIX_REQUIRED' for x in ast.walk(n)))
    branch.body=[n for n in branch.body if not any(isinstance(x,ast.Constant) and x.value=='FACTUAL_NONEMPTY_CORRELATION_PREFIX_REQUIRED' for x in ast.walk(n))]
    scope=dict(module.__dict__);exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<actual-nonempty-prefix-guard-removed>','exec'),scope)
    assert scope['correlation_seed'](tmp_path,cp)==[]
