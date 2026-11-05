"""Original inactive APHA loader lifecycle, with synthetic DATA objects only."""
import ast
from copy import deepcopy
import importlib.abc
import json
from pathlib import Path
import sys
from types import MethodType,SimpleNamespace

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

class Fence(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('stock_strategy_shared','sentinel','research.pooled_','numpy','pandas')):
            raise AssertionError('NO_LOCAL_FINANCIAL_IMPORT:'+fullname)

@pytest.fixture(autouse=True)
def imports():
    fence=Fence();sys.meta_path.insert(0,fence);yield;sys.meta_path.remove(fence)


def code():
    root=Path(__file__).resolve().parents[1]
    path=root/'system_campaign_financial_partial.py.after'
    if not path.exists():path=root/'system_campaign_financial_partial.py'
    return path.read_bytes()


def helper(*,remove=None):
    import system_campaign_financial_projection as p
    fn=next(n for n in ast.parse(code()).body if isinstance(n,ast.FunctionDef) and n.name=='activate_retained_projection')
    if remove:
        before=len(fn.body)
        fn.body=[n for n in fn.body if not isinstance(n,ast.Expr) or not any(isinstance(v,ast.Constant) and v.value==remove for v in ast.walk(n))]
        assert len(fn.body)==before-1
    scope=dict(Path=Path,sha=p.sha,need=p.need)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<retained-activation-orchestration-only>','exec'),scope)
    return scope['activate_retained_projection']


def fixture(tmp_path,monkeypatch):
    import system_campaign_financial_projection as p
    root=Path(p.__file__).parent;binding=json.loads((root/p.BINDING).read_bytes())
    original=(root/'system_campaign_future_amendment.py').read_bytes()
    assert p.sha(original)==binding['original_adapter_sha256']
    assert p.sha(Path(p.__file__).read_bytes())=='2165e64a961bf0ee44c8f19ac2d6ec65059cc92a2b4154ad735685d29e120777'
    owner=next(n for n in ast.parse(original).body if isinstance(n,ast.ClassDef) and n.name=='FutureProjection')
    load=next(n for n in owner.body if isinstance(n,ast.FunctionDef) and n.name=='load')
    scope=dict(Path=Path,need=p.need,CUTOVER='2021-03-31',INNER='a'*64,TARGET='c'*64)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[load],type_ignores=[])),'<unchanged-original-pure-APHA-load>','exec'),scope)
    class Codec:
        def __init__(self):self.objects=[];self.calls=[];self.private_cursor=None
        def load(self,path,*,resume_session,predecessor_checkpoint_sha256):
            self.calls.append((path,resume_session,predecessor_checkpoint_sha256))
            obj=SimpleNamespace(sha256=p.sha(Path(path).read_bytes()),_resume_session=self.private_cursor or resume_session,
                                predecessor_checkpoint_sha256=predecessor_checkpoint_sha256)
            self.objects.append(obj);return obj
    class OwnProjection:
        def load(self,path,**kwargs):return scope['load'](self,path,**kwargs)
    monkeypatch.setattr(p,'OwnProjection',OwnProjection)
    codec=Codec();projection=OwnProjection();projection.active=False;projection.loaded_target=[]
    projection.original_load=codec.load;projection.cp=dict(source_cursor='2021-03-31',base={'same':'own source'},run=dict(checkpoint_sha256='a'*64))
    raw=b'{"schema":"synthetic-original-committed-activation"}\n';sha=p.sha(raw)
    projection.overlay_raw=raw;projection.activation_sha=sha
    folder=tmp_path/'book/repairs';folder.mkdir(parents=True);path=folder/(sha+'.json');path.write_bytes(raw)
    d=dict(filename=sha+'.json',sha256=sha,resume_session='2021-03-31',predecessor_checkpoint_sha256='a'*64)
    current=dict(base=deepcopy(projection.cp['base']),source_cursor='2021-04-30',repairs=[d])
    projection.backtest=SimpleNamespace(load_repair=projection.load)
    return p,projection,codec,current,d,path


def test_actual_false_active_failure_and_original_committed_load_fixes_it(tmp_path,monkeypatch):
    p,projection,codec,current,d,path=fixture(tmp_path,monkeypatch)
    assert projection.active is False
    with pytest.raises(ValueError,match='BRANCH_CODEC_ONLY_AFTER_ACTIVATION'):
        p.branch_loader_owner(projection.backtest.load_repair)
    loaded=helper()(tmp_path,current,projection)
    assert projection.active is True and loaded is codec.objects[-1]
    assert p.branch_loader_owner(projection.backtest.load_repair) is codec
    assert codec.calls==[(path,'2021-03-31','a'*64)]
    assert loaded._resume_session!='2021-04-30'
    assert current['source_cursor']=='2021-04-30' and len(current['repairs'])==1


@pytest.mark.parametrize('kind',['current_cursor','predecessor','raw','filename','hash','base','duplicate','missing'])
def test_wrong_original_descriptor_clock_source_and_bytes_refuse_before_activation(tmp_path,monkeypatch,kind):
    p,projection,codec,current,d,path=fixture(tmp_path,monkeypatch)
    if kind=='current_cursor':d['resume_session']=current['source_cursor']
    elif kind=='predecessor':d['predecessor_checkpoint_sha256']='b'*64
    elif kind=='raw':path.write_bytes(b'changed activation bytes')
    elif kind=='filename':d['filename']='other.json'
    elif kind=='hash':d['sha256']='b'*64
    elif kind=='base':current['base']={'other':'source'}
    elif kind=='duplicate':current['repairs'].append(deepcopy(d))
    else:current['repairs']=[]
    with pytest.raises((ValueError,FileNotFoundError)):helper()(tmp_path,current,projection)
    assert projection.active is False and codec.calls==[]


def test_duplicate_descriptor_guard_removal_really_admits_ambiguous_activation(tmp_path,monkeypatch):
    p,projection,codec,current,d,path=fixture(tmp_path,monkeypatch);current['repairs'].append(deepcopy(d))
    with pytest.raises(ValueError):helper()(tmp_path,current,projection)
    loaded=helper(remove='PARTIAL_ONE_EXACT_RETAINED_PROJECTION_ACTIVATION')(tmp_path,current,projection)
    assert loaded is codec.objects[-1] and projection.active is True


def test_wrong_loaded_private_clock_guard_removal_is_meaningful(tmp_path,monkeypatch):
    p,projection,codec,current,d,path=fixture(tmp_path,monkeypatch);codec.private_cursor='2021-04-30'
    with pytest.raises(ValueError,match='ACTUAL_LOADED_OBJECT_ORIGINAL_CLOCK'):helper()(tmp_path,current,projection)
    loaded=helper(remove='PARTIAL_RETAINED_PROJECTION_ACTUAL_LOADED_OBJECT_ORIGINAL_CLOCK')(tmp_path,current,projection)
    assert loaded._resume_session=='2021-04-30' and projection.active is True


def test_uninstalled_foreign_loader_refuses(tmp_path,monkeypatch):
    p,projection,codec,current,d,path=fixture(tmp_path,monkeypatch);projection.backtest.load_repair=codec.load
    with pytest.raises(ValueError,match='ACTUAL_INSTALLED_LOADER'):helper()(tmp_path,current,projection)
    assert projection.active is False and codec.calls==[]


def test_nonprojection_context_delegates_without_loader_changes(tmp_path):
    assert helper()(tmp_path,{},None) is None


def test_orchestration_load_occurs_after_context_enter_before_yield_without_manual_active():
    tree=ast.parse(code());activate=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='activate_retained_projection')
    context=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='model_context')
    assignments=[n for n in ast.walk(activate) if isinstance(n,(ast.Assign,ast.AnnAssign,ast.AugAssign))]
    assert not any(isinstance(v,ast.Attribute) and v.attr=='active' and isinstance(v.ctx,ast.Store) for n in assignments for v in ast.walk(n))
    call=next(n for n in ast.walk(context) if isinstance(n,ast.Call) and ast.unparse(n.func)=='activate_retained_projection')
    entered=next(n for n in ast.walk(context) if isinstance(n,ast.Assign) and any(isinstance(v,ast.Name) and v.id=='projection' for v in n.targets))
    yielded=next(n for n in ast.walk(context) if isinstance(n,ast.Yield))
    assert entered.lineno<call.lineno<yielded.lineno
