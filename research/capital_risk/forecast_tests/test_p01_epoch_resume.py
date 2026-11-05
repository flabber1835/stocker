"""Hosted continuation seam stubs only; no canonical strategy execution."""
import ast
from contextlib import contextmanager
from copy import deepcopy
import gzip
import inspect
import json
from pathlib import Path
import sys
import textwrap
from types import ModuleType,SimpleNamespace

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import p01_epoch_resume as resume


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    raw=json.dumps(value,sort_keys=True).encode()
    path.write_bytes(gzip.compress(raw) if path.name.endswith('.gz') else raw)


def rehash(value):
    value['run']['state_sha256']=resume.digest(value['run']['state'])
    value['run']['checkpoint_sha256']=resume.digest({k:v for k,v in value['run'].items() if k!='checkpoint_sha256'})
    value['sha256']=resume.digest({k:v for k,v in value.items() if k!='sha256'})
    return value


@pytest.fixture
def setup(tmp_path,monkeypatch):
    receipt=tmp_path/'old/source-successor.json';write(receipt,dict(schema='research.p01-celg-own475-source-successor/1'))
    receipt_sha=resume.sha(receipt.read_bytes());monkeypatch.setattr(resume,'SOURCE_RECEIPT',receipt_sha)
    base=dict(sources={'source.py':'a'*64},source_successor_sha256=receipt_sha,policy='STUB',capital='50000')
    repairs=[dict(filename=f'{n:064x}.json',sha256=f'{n:064x}',resume_session='2019-01-01',predecessor_checkpoint_sha256='e'*64) for n in range(10)]
    zero=dict(bytes=0,prefix_sha256=resume.sha(b''),last_record_sha256=None)
    parent=dict(schema='research.pooled-vacancy-backtest/1',base=base,repairs=repairs,source_cursor='2020-02-04',completed=526,
        economics={},stats={},spy_base='1',retries={},chain='oldchain',journals=dict(daily=zero,watch=zero),
        run=dict(policy='STUB',state={'ledger':{'events':[]},'pending':[]},input_sha256=resume.digest(dict(base=base,repairs=repairs))))
    rehash(parent);monkeypatch.setattr(resume,'OUTER',parent['sha256'])
    checkpoint=tmp_path/'out/book/checkpoint.json.gz';write(checkpoint,parent)
    original=lambda *args:('LEGACY',None)
    module=SimpleNamespace(load_successor=original)
    monkeypatch.setattr(resume,'_hosted',lambda:None);monkeypatch.setattr(resume,'_source_module',lambda:module)
    return SimpleNamespace(parent=parent,mapping={'successor_financial_sources':base['sources']},receipt=receipt,
        checkpoint=checkpoint,module=module,original=original,tmp=tmp_path)


def test_current_epoch_resume_has_no_source_binding_or_event(setup):
    s=setup
    with resume.EpochSourceGate(s.parent,s.mapping,s.receipt,s.checkpoint) as gate:
        base,binding=s.module.load_successor(s.receipt,{k:v for k,v in s.parent['base'].items() if k!='source_successor_sha256'})
        assert base==s.parent['base'] and binding is None
        assert gate.parent==s.parent and gate.loads==1
    assert s.module.load_successor is s.original


@pytest.mark.parametrize('change',['receipt','path','source','checkpoint'])
def test_wrong_epoch_receipt_source_or_checkpoint_refuses(setup,change):
    s=setup;base=deepcopy(s.parent['base']);path=s.receipt
    if change=='receipt':write(path,dict(schema='research.p01-celg-own475-source-successor/1',changed=True))
    if change=='path':path=s.tmp/'other.json';path.write_bytes(s.receipt.read_bytes())
    if change=='source':base['sources']['source.py']='b'*64
    if change=='checkpoint':
        wrong=deepcopy(s.parent);wrong['run']['state']['pending']=['changed'];write(s.checkpoint,rehash(wrong))
    with resume.EpochSourceGate(s.parent,s.mapping,s.receipt,s.checkpoint) as gate,pytest.raises(ValueError):
        gate.load(path,base)


def test_legacy_authority_delegation_unchanged(setup):
    s=setup;path=s.tmp/'legacy.json';write(path,dict(schema='OLD_LEGACY_SCHEMA'))
    with resume.EpochSourceGate(s.parent,s.mapping,s.receipt,s.checkpoint) as gate:
        assert gate.load(path,{})==('LEGACY',None)


def input_zero(parent,earliest='2020-02-05'):
    saved=deepcopy(parent);descriptor=dict(filename='b'*64+'.json',sha256='b'*64,resume_session=parent['source_cursor'],
        predecessor_checkpoint_sha256=parent['run']['checkpoint_sha256'])
    saved['repairs'].append(descriptor)
    saved['run']['input_sha256']=resume.digest(dict(base=saved['base'],repairs=saved['repairs']))
    saved['journals']['watch']=dict(bytes=1,prefix_sha256='c'*64,last_record_sha256='c'*64)
    event=dict(schema='research.pooled-action-successor/1',predecessor_checkpoint_sha256=parent['run']['checkpoint_sha256'],
        unchanged_through=parent['source_cursor'],earliest_affected_session=earliest,state_sha256=parent['run']['state_sha256'],
        overlay=descriptor,predecessor_input_sha256=parent['run']['input_sha256'],successor_input_sha256=saved['run']['input_sha256'])
    saved['chain']=resume.digest(dict(previous=parent['chain'],event=event))
    return rehash(saved)


def test_eleven_zero_requires_actual_canonical_adoption_checker(setup,monkeypatch):
    from system_campaign_pxd_pause import adoption
    s=setup;calls=[]
    def checked(*args):calls.append(args);return adoption(*args)
    monkeypatch.setattr(resume,'_adoption',checked)
    with resume.EpochSourceGate(s.parent,s.mapping,s.receipt,s.checkpoint) as gate:
        saved=input_zero(s.parent);gate.allow_input(saved,'b'*64,'2020-02-05');write(s.checkpoint,saved)
        assert gate.load(s.receipt,s.parent['base'])==(s.parent['base'],None)
        assert len(calls)==1 and calls[0][1]==s.parent
        wrong=deepcopy(saved);wrong['run']['state']['pending']=['changed'];rehash(wrong)
        with pytest.raises(ValueError):gate.allow_input(wrong,'b'*64,'2020-02-05')


def test_future_input_guard_removal_falsifier(setup):
    s=setup;gate=resume.EpochSourceGate(s.parent,s.mapping,s.receipt,s.checkpoint)
    saved=input_zero(s.parent,earliest='2020-02-04')
    with pytest.raises(ValueError):gate.allow_input(saved,'b'*64,'2020-02-04')
    raw=textwrap.dedent(inspect.getsource(resume.EpochSourceGate.allow_input))
    changed=raw.replace("and type(earliest) is str and earliest > self.parent['source_cursor']",'')
    assert changed!=raw
    namespace=dict(vars(resume));exec(compile(ast.parse(changed),'<future-guard-removal-falsifier>','exec'),namespace)
    namespace['allow_input'](gate,saved,'b'*64,'2020-02-04')


@pytest.mark.parametrize('registration',['SAME','EQUAL_OTHER','NONE'])
def test_auth_quote_and_all_ten_codecs_before_caller_restore(setup,monkeypatch,registration):
    s=setup;events=[];old=s.receipt.parent;out=s.checkpoint.parents[1]
    quote={'authenticated':'only-approved-input'};descriptor={'descriptor':'whole'}
    document=dict(quote_capsule=descriptor,terms={'right_quote':quote},quote_input_sha256=resume.digest(quote))
    for d in s.parent['repairs']:write(old/'book/repairs'/d['filename'],document if d is s.parent['repairs'][-1] else {})
    monkeypatch.setattr(resume,'TENTH',resume.sha((old/'book/repairs'/s.parent['repairs'][-1]['filename']).read_bytes()))
    mapping=dict(s.mapping,successor_all_sources={'source.py':'a'*64});write(old/'source-map.json',mapping)
    monkeypatch.setattr(resume,'validate_contents',lambda *args:deepcopy(s.parent))
    monkeypatch.setattr(resume,'_source_files',lambda:mapping['successor_all_sources'])
    def authenticated(*args):events.append('quote_authenticated');return quote,descriptor
    monkeypatch.setattr(resume,'_quote',authenticated)
    @contextmanager
    def old_inputs(*args):events.append('old9_enter');yield
    class Codec:
        def __init__(self,*args):self.objects=[]
        def __enter__(self):events.append('CELG10_enter');return self
        def __exit__(self,*args):pass
    codec=Codec();bridge=ModuleType('p01_celg_bridge_run');bridge.old_inputs=old_inputs;bridge.native=lambda *args:None
    codec_module=ModuleType('p01_celg_bridge_codec');codec_module.InputCodec=lambda *args:codec;codec_module.OLD='2019-11-20';codec_module.SID='SOURCE'
    def load(path,**kwargs):
        index=len([v for v in events if v.startswith('load')]);events.append('load'+str(index))
        obj=SimpleNamespace(sha256=s.parent['repairs'][index]['sha256'])
        if index==9 and registration!='NONE':
            codec.objects.append(obj if registration=='SAME' else SimpleNamespace(**vars(obj)))
        return obj
    backtest=SimpleNamespace(load_repair=load)
    package=ModuleType('research.pooled_vacancy_funding');package.backtest=backtest
    monkeypatch.setitem(sys.modules,'p01_celg_bridge_run',bridge);monkeypatch.setitem(sys.modules,'p01_celg_bridge_codec',codec_module)
    monkeypatch.setitem(sys.modules,'research.pooled_vacancy_funding',package)
    original_checkpoint=s.checkpoint.read_bytes()
    if registration!='SAME':
        with pytest.raises(ValueError),resume.historical_epoch(old,out,{},checkpoint_path=s.checkpoint):
            pytest.fail('unregistered tenth codec must refuse before caller restore')
        assert s.checkpoint.read_bytes()==original_checkpoint
        return
    with resume.historical_epoch(old,out,{},checkpoint_path=s.checkpoint) as binding:
        assert events==['quote_authenticated','old9_enter','CELG10_enter']+['load'+str(n) for n in range(10)]
        events.append('caller_restore_stub')
        assert binding.source_args==['--source-successor',str(s.receipt)] and len(binding.objects)==10
        assert s.checkpoint.read_bytes()==original_checkpoint
    assert s.module.load_successor is s.original
    assert s.checkpoint.read_bytes()==original_checkpoint


def test_wrong_actual_source_refuses_before_quote_or_parser(setup,monkeypatch):
    s=setup;write(s.receipt.parent/'source-map.json',dict(s.mapping,successor_all_sources={'expected':'a'*64}))
    monkeypatch.setattr(resume,'validate_contents',lambda *args:s.parent);monkeypatch.setattr(resume,'_source_files',lambda:{'wrong':'b'*64})
    monkeypatch.setattr(resume,'_quote',lambda *args:pytest.fail('must refuse before quote/parsers'))
    with pytest.raises(ValueError),resume.historical_epoch(s.receipt.parent,s.tmp/'out',{}):pass
