"""Pure hydration seam/identity stubs only; never restore a financial state."""
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
import p01_iac_unit_epoch as epoch


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);raw=json.dumps(value,sort_keys=True).encode()
    path.write_bytes(gzip.compress(raw) if path.name.endswith('.gz') else raw)


def rehash(cp):
    cp['run']['state_sha256']=epoch.digest(cp['run']['state'])
    cp['run']['checkpoint_sha256']=epoch.digest({k:v for k,v in cp['run'].items() if k!='checkpoint_sha256'})
    cp['sha256']=epoch.digest({k:v for k,v in cp.items() if k!='sha256'});return cp


@pytest.fixture
def seam(tmp_path,monkeypatch):
    receipt=tmp_path/'old/source-successor.json';write(receipt,{'schema':'research.p01-celg-own475-source-successor/1'})
    receipt_sha=epoch.sha(receipt.read_bytes());monkeypatch.setattr(epoch,'SOURCE_RECEIPT',receipt_sha)
    base=dict(sources={'source.py':'a'*64},source_successor_sha256=receipt_sha,policy='SYNTHETIC',capital='50000')
    repairs=[dict(filename=f'{n:064x}.json',sha256=f'{n:064x}',resume_session='2019-01-01',
                  predecessor_checkpoint_sha256='e'*64) for n in range(11)]
    parent=rehash(dict(base=base,repairs=repairs,source_cursor='2020-06-30',completed=628,economics={},stats={},spy_base={},retries={},chain='e'*64,
        journals={name:dict(bytes=1,prefix_sha256='f'*64,last_record_sha256='f'*64) for name in ('daily','formation','monthly','watch')},run=dict(state={'ledger':{'events':[]},'pending':[]},input_sha256=epoch.digest(dict(base=base,repairs=repairs)))))
    monkeypatch.setattr(epoch,'OUTER',parent['sha256']);monkeypatch.setattr(epoch,'STATE',parent['run']['state_sha256']);monkeypatch.setattr(epoch,'INPUT',parent['run']['input_sha256']);cp=tmp_path/'out/book/checkpoint.json.gz';write(cp,parent)
    original=lambda *args:('LEGACY',None);module=SimpleNamespace(load_successor=original)
    monkeypatch.setattr(epoch,'_hosted',lambda:None);monkeypatch.setattr(epoch,'_source_module',lambda:module)
    return SimpleNamespace(parent=parent,mapping={'successor_financial_sources':base['sources']},receipt=receipt,
        checkpoint=cp,module=module,original=original,tmp=tmp_path)


def test_same_actual628_base_none_no_input_adoption_or_event(seam):
    s=seam;before=s.checkpoint.read_bytes()
    with epoch.IacEpochSourceGate(s.parent,s.mapping,s.receipt,s.checkpoint) as gate:
        assert gate.load(s.receipt,{k:v for k,v in s.parent['base'].items() if k!='source_successor_sha256'})==(s.parent['base'],None)
        assert gate.loads==1 and hasattr(gate,'allow_input') and s.checkpoint.read_bytes()==before
    assert s.module.load_successor is s.original


@pytest.mark.parametrize('change',['receipt','path','source','state','twelfth','older526'])
def test_wrong_scope_or_any_changed_checkpoint_refuses(seam,change):
    s=seam;path=s.receipt;base=deepcopy(s.parent['base']);cp=deepcopy(s.parent)
    if change=='receipt':write(path,dict(schema='research.p01-celg-own475-source-successor/1',changed=True))
    elif change=='path':path=s.tmp/'copy.json';path.write_bytes(s.receipt.read_bytes())
    elif change=='source':base['sources']['source.py']='b'*64
    elif change=='state':cp['run']['state']['pending']=['changed'];write(s.checkpoint,rehash(cp))
    elif change=='twelfth':
        cp['repairs'].append({'sha256':'b'*64});cp['run']['input_sha256']=epoch.digest(dict(base=cp['base'],repairs=cp['repairs']))
        write(s.checkpoint,rehash(cp))
    elif change=='older526':cp.update(source_cursor='2020-02-04',completed=526);write(s.checkpoint,rehash(cp))
    with epoch.IacEpochSourceGate(s.parent,s.mapping,s.receipt,s.checkpoint) as gate,pytest.raises(ValueError):gate.load(path,base)


def test_legacy_loader_delegation(seam):
    s=seam;path=s.tmp/'legacy.json';write(path,dict(schema='LEGACY'))
    with epoch.IacEpochSourceGate(s.parent,s.mapping,s.receipt,s.checkpoint) as gate:assert gate.load(path,{})==('LEGACY',None)


def test_identical_parent_guard_removal_falsifier(seam):
    s=seam;changed=deepcopy(s.parent);changed['run']['state']['pending']=['changed'];write(s.checkpoint,rehash(changed))
    gate=epoch.IacEpochSourceGate(s.parent,s.mapping,s.receipt,s.checkpoint)
    with pytest.raises(ValueError):gate.load(s.receipt,s.parent['base'])
    raw=textwrap.dedent(inspect.getsource(epoch.IacEpochSourceGate.load))
    tree=ast.parse(raw);fn=tree.body[0]
    guard=next(n for n in ast.walk(fn) if isinstance(n,ast.Call) and any(isinstance(v,ast.Constant)
        and v.value=='ONLY_EXACT_ADMITTED628_OR_REGISTERED_TWELFTH_INPUT_ZERO' for v in ast.walk(n)))
    guard.args[0]=ast.Constant(True);ns=dict(vars(epoch))
    exec(compile(ast.fix_missing_locations(tree),'<identical628-guard-removal>','exec'),ns)
    assert ns['load'](gate,s.receipt,s.parent['base'])==(s.parent['base'],None)


@pytest.mark.parametrize('registration',['SAME','EQUAL_OTHER','MISSING'])
def test_quote_and_all_eleven_original_codecs_before_caller_restore(seam,monkeypatch,registration):
    s=seam;old=s.receipt.parent;out=s.checkpoint.parents[1];events=[]
    quote={'authenticated':'retained_input'};descriptor={'exact':'descriptor'}
    document=dict(quote_capsule=descriptor,terms={'right_quote':quote},quote_input_sha256=epoch.digest(quote))
    for i,d in enumerate(s.parent['repairs']):write(old/'book/repairs'/d['filename'],document if i==9 else {'original':i})
    monkeypatch.setattr(epoch,'TENTH',epoch.sha((old/'book/repairs'/s.parent['repairs'][9]['filename']).read_bytes()))
    monkeypatch.setattr(epoch,'ELEVENTH',epoch.sha((old/'book/repairs'/s.parent['repairs'][10]['filename']).read_bytes()))
    mapping=dict(s.mapping,successor_all_sources={'source.py':'a'*64});write(old/'source-map.json',mapping)
    monkeypatch.setattr(epoch,'validate_contents',lambda *args:deepcopy(s.parent))
    monkeypatch.setattr(epoch,'_source_files',lambda:mapping['successor_all_sources'])
    def authenticate(*args):events.append('quote_authenticated');return quote,descriptor
    monkeypatch.setattr(epoch,'_quote',authenticate)
    @contextmanager
    def old_inputs(*args):events.append('old9_enter');yield
    class Codec:
        def __init__(self,name):self.objects=[];self.name=name
        def __enter__(self):events.append(self.name);return self
        def __exit__(self,*args):pass
    celg,batch=Codec('CELG10_enter'),Codec('batch11_enter')
    bridge=ModuleType('p01_celg_bridge_run');bridge.old_inputs=old_inputs;bridge.native=lambda *args:None
    cmod=ModuleType('p01_celg_bridge_codec');cmod.InputCodec=lambda *args:celg;cmod.OLD='2019-11-20';cmod.SID='SOURCE'
    bmod=ModuleType('p01_factual_batch_codec');bmod.InputCodec=lambda *args:batch;bmod.source_terms=lambda:None
    def load(path,**kwargs):
        i=len([x for x in events if x.startswith('load')]);events.append('load'+str(i))
        assert kwargs==dict(resume_session=s.parent['repairs'][i]['resume_session'],
            predecessor_checkpoint_sha256=s.parent['repairs'][i]['predecessor_checkpoint_sha256'])
        obj=SimpleNamespace(sha256=s.parent['repairs'][i]['sha256'])
        if i==9:celg.objects.append(obj)
        if i==10 and registration!='MISSING':batch.objects.append(obj if registration=='SAME' else SimpleNamespace(**vars(obj)))
        return obj
    package=ModuleType('research.pooled_vacancy_funding');package.backtest=SimpleNamespace(load_repair=load)
    for name,m in [('p01_celg_bridge_run',bridge),('p01_celg_bridge_codec',cmod),('p01_factual_batch_codec',bmod),
                  ('research.pooled_vacancy_funding',package)]:monkeypatch.setitem(sys.modules,name,m)
    before=s.checkpoint.read_bytes()
    if registration!='SAME':
        with pytest.raises(ValueError),epoch.historical_epoch(old,out,{},checkpoint_path=s.checkpoint):pytest.fail('must refuse before restore')
    else:
        with epoch.historical_epoch(old,out,{},checkpoint_path=s.checkpoint) as binding:
            assert events==['quote_authenticated','old9_enter','CELG10_enter','batch11_enter']+['load'+str(i) for i in range(11)]
            events.append('caller_restore_stub');assert len(binding.objects)==11 and binding.parent==s.parent
            assert binding.source_args==['--source-successor',str(s.receipt)]
    assert s.checkpoint.read_bytes()==before and s.module.load_successor is s.original


def test_wrong_actual_source_refuses_before_quote_parsers_or_restore(seam,monkeypatch):
    s=seam;write(s.receipt.parent/'source-map.json',dict(s.mapping,successor_all_sources={'expected':'a'*64}))
    monkeypatch.setattr(epoch,'validate_contents',lambda *args:s.parent);monkeypatch.setattr(epoch,'_source_files',lambda:{'wrong':'b'*64})
    monkeypatch.setattr(epoch,'_quote',lambda *args:pytest.fail('must refuse before quote/parsers'))
    with pytest.raises(ValueError),epoch.historical_epoch(s.receipt.parent,s.tmp/'out',{}):pass


@pytest.fixture
def adoption_checker(monkeypatch):
    here=Path(epoch.__file__).parent
    raw=(here/'system_campaign_pxd_pause.py').read_bytes()
    request=json.loads((here/'p01_native_resume_request.json').read_bytes())
    assert epoch.sha(raw)==request['sources']['system_campaign_pxd_pause.py']
    tree=ast.parse(raw)
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='adoption')
    unchanged=next(n for n in tree.body if isinstance(n,ast.Assign)
        and any(isinstance(t,ast.Name) and t.id=='UNCHANGED' for t in n.targets))
    ns=dict(need=epoch.need,digest=epoch.digest,UNCHANGED=ast.literal_eval(unchanged.value))
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<frozen-canonical-adoption-metadata-checker>','exec'),ns)
    monkeypatch.setattr(epoch,'_adoption',ns['adoption'])


def input_zero(s,*,earliest='2020-07-01'):
    cp=deepcopy(s.parent);h='b'*64
    d=dict(filename=h+'.json',sha256=h,resume_session=cp['source_cursor'],
        predecessor_checkpoint_sha256=s.parent['run']['checkpoint_sha256'])
    cp['repairs'].append(d);cp['run']['input_sha256']=epoch.digest(dict(base=cp['base'],repairs=cp['repairs']))
    cp['journals']['watch']=dict(bytes=2,prefix_sha256='d'*64,last_record_sha256='c'*64)
    event=dict(schema='research.pooled-action-successor/1',
        predecessor_checkpoint_sha256=s.parent['run']['checkpoint_sha256'],
        unchanged_through=s.parent['source_cursor'],earliest_affected_session=earliest,
        state_sha256=s.parent['run']['state_sha256'],overlay=d,
        predecessor_input_sha256=s.parent['run']['input_sha256'],successor_input_sha256=cp['run']['input_sha256'])
    cp['chain']=epoch.digest(dict(previous=s.parent['chain'],event=event))
    return rehash(cp),h,event


def test_exact_canonical_twelfth_input_zero_registered_once_after_actual_write(seam,adoption_checker):
    s=seam;cp,h,event=input_zero(s)
    with epoch.IacEpochSourceGate(s.parent,s.mapping,s.receipt,s.checkpoint) as gate:
        write(s.checkpoint,cp);before=s.checkpoint.read_bytes()
        with pytest.raises(ValueError):gate.load(s.receipt,s.parent['base'])
        assert gate.allow_input(cp,h,'2020-07-01')==event
        assert gate.load(s.receipt,s.parent['base'])==(s.parent['base'],None)
        with pytest.raises(ValueError):gate.allow_input(cp,h,'2020-07-01')
        assert s.checkpoint.read_bytes()==before and len(gate.allowed)==2


@pytest.mark.parametrize('change',['state','old_descriptor','extra_input','not_zero','base','hash','not_written'])
def test_unqualified_input_zero_or_graft_refuses_before_registration(seam,adoption_checker,change):
    s=seam;cp,h,event=input_zero(s)
    if change=='state':cp['run']['state']['pending']=['graft']
    if change=='old_descriptor':cp['repairs'][0]['resume_session']='2020-06-30'
    if change=='extra_input':cp['repairs'].append(dict(sha256='d'*64))
    if change=='not_zero':cp['completed']=629
    if change=='base':cp['base']['policy']='OTHER'
    if change=='hash':cp['sha256']='0'*64
    elif change!='not_written':rehash(cp)
    if change!='not_written':write(s.checkpoint,cp)
    with epoch.IacEpochSourceGate(s.parent,s.mapping,s.receipt,s.checkpoint) as gate:
        with pytest.raises(ValueError):gate.allow_input(cp,h,'2020-07-01')
        assert not gate.input_registered and set(gate.allowed)=={s.parent['sha256']}


def test_future_effective_clock_guard_removal_falsifier(seam,adoption_checker):
    s=seam;cp,h,event=input_zero(s,earliest='2020-06-30');write(s.checkpoint,cp)
    gate=epoch.IacEpochSourceGate(s.parent,s.mapping,s.receipt,s.checkpoint)
    with pytest.raises(ValueError):gate.allow_input(cp,h,'2020-06-30')
    tree=ast.parse(textwrap.dedent(inspect.getsource(epoch.IacEpochSourceGate.allow_input)))
    guard=next(n for n in ast.walk(tree) if isinstance(n,ast.Call)
        and any(isinstance(v,ast.Constant) and v.value=='ONE_EXACT_OWN628_FUTURE_TWELFTH_INPUT_ZERO'
                for v in ast.walk(n)))
    guard.args[0]=ast.Constant(True);ns=dict(vars(epoch))
    exec(compile(ast.fix_missing_locations(tree),'<future-input-clock-guard-removal>','exec'),ns)
    assert ns['allow_input'](gate,cp,h,'2020-06-30')==event


def test_actual_input_zero_file_guard_removal_falsifier(seam,adoption_checker):
    s=seam;cp,h,event=input_zero(s)
    gate=epoch.IacEpochSourceGate(s.parent,s.mapping,s.receipt,s.checkpoint)
    with pytest.raises(ValueError):gate.allow_input(cp,h,'2020-07-01')
    tree=ast.parse(textwrap.dedent(inspect.getsource(epoch.IacEpochSourceGate.allow_input)))
    guard=next(n for n in ast.walk(tree) if isinstance(n,ast.Call)
        and any(isinstance(v,ast.Constant) and v.value=='ACTUAL_CURRENT_FILE_AND_ENTIRE_SESSIONSTATE_UNCHANGED_AT_INPUT_ZERO'
                for v in ast.walk(n)))
    guard.args[0]=ast.Constant(True);ns=dict(vars(epoch))
    exec(compile(ast.fix_missing_locations(tree),'<actual-input-zero-file-guard-removal>','exec'),ns)
    assert ns['allow_input'](gate,cp,h,'2020-07-01')==event
