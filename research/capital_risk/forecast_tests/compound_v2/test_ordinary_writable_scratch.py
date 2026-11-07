"""Actual245 mount contract + unchanged input hydrator AST, synthetic IO only."""
import ast
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict,make_dataclass
import errno
import importlib.abc
import json
from pathlib import Path
import re
import sys
import tempfile
from types import MethodType,SimpleNamespace

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import system_campaign_financial_compound_ordinary_v2 as o
import system_campaign_financial_compound_input_v2 as model

CODE=Path(model.__file__).parent
FIX=Path(__file__).parent/'fixtures/actual-financial245-scratch.json'

class Fence(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise AssertionError('NO_CANONICAL_FINANCIAL_IMPORT:'+fullname)

@pytest.fixture(autouse=True)
def imported():
    guard=Fence();sys.meta_path.insert(0,guard);yield;sys.meta_path.remove(guard)

def mount_fixture():
    raw=FIX.read_bytes();assert o.sha(raw)=='84b4543b5f6eff67531ee6c8d0406170e0b28b48043cc9726f88b09aabced5a5'
    value=json.loads(raw)
    assert value['readonly_rootfs'] is True and value['mounts']['/variant'] is False and value['mounts']['/out'] is True
    assert value['tmpfs']=={'/tmp':'rw,noexec,nosuid,size=128m'} and value['no_financial_state_or_runtime'] is True
    return value

def source_input(tmp_path):
    raw=(CODE/'forecast_tests/compound_v2/fixtures/actual-own838-inherited-repairs.json').read_bytes()
    assert o.sha(raw)=='08a3d38514e5d1e2b21d3eff741be0aae2fb05f08c34f7f3345c392fff08de0c'
    actual=json.loads(raw);parent=deepcopy(actual['parent_metadata']);folder=tmp_path/'old/book/repairs';folder.mkdir(parents=True)
    ordinary=[]
    for descriptor in parent['repairs']:
        body=actual['documents'][descriptor['filename']].encode();assert o.sha(body)==descriptor['sha256']
        (folder/descriptor['filename']).write_bytes(body)
        if json.loads(body)['schema']=='terminal-repair/1':ordinary.append(deepcopy(descriptor))
    assert len(parent['repairs'])==18 and len(ordinary)==17
    view=dict(deepcopy(parent),repairs=ordinary)
    data=json.loads((CODE/'forecast_tests/compound_v2/fixtures/VCRA-unadopted-original-input-evidence.json').read_bytes())
    catalog=json.loads((CODE/data['catalog_file']).read_bytes());catalog['terms']=[deepcopy(data['term'])]
    return tmp_path/'old',view,catalog,data

def original_hydrator(catalog,data,*,bad=None):
    raw=(CODE/'system_campaign_cash_calendar.py').read_bytes()
    assert o.sha(raw)==mount_fixture()['cash_calendar_sha256']=='183c548f7ddf95e277446f9704c5ffa2537ea9807a3305abbecbaae3d4ea262f'
    cls=next(n for n in ast.parse(raw).body if isinstance(n,ast.ClassDef) and n.name=='CashCalendar')
    fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='hydrate')
    # Bind only the two source-reading dependencies to synthetic source inputs.
    # No canonical module is imported or any financial routine executed.
    class Bind(ast.NodeTransformer):
        count=0
        def visit_ImportFrom(self,node):
            lookup={'from research.pooled_input_support import inputs':('inputs','synthetic_inputs'),
                    'from research.pooled_input_support.bundle import axis':('axis','synthetic_axis')}
            value=lookup.get(ast.unparse(node));assert value is not None
            self.count+=1
            return ast.Assign(targets=[ast.Name(id=value[0],ctx=ast.Store())],value=ast.Name(id=value[1],ctx=ast.Load()))
    binder=Bind();fn=binder.visit(fn);assert binder.count==2
    typed=deepcopy(data['native'])
    if bad=='native':typed['cash_per_share']=79.25
    Native=make_dataclass('SyntheticNative',[(key,object) for key in typed]);Native.completeness=lambda self,quantity:(False,('missing cash',))
    native=Native(**typed);row=deepcopy(data['source_observation'])
    if bad=='row':row['issuer_id']='unreviewed upgrade'
    dates=['2022-02-18','2022-02-22','2022-02-23'] if bad!='axis' else ['2022-02-18','2022-02-22','2022-02-24']
    calls=[]
    def load_actions(path):calls.append(('actions',str(path)));return SimpleNamespace(terminal={'2022-02-22':(native,)})
    def archive_rows(archive,name):
        assert name=='observations-2022.csv.gz';calls.append(('fullrow',name));return iter([deepcopy(row)])
    class Archive:
        def __init__(self,path):assert path=='/frozen/archive/corpus.zip'
        def __enter__(self):return self
        def __exit__(self,*args):pass
    def source_path(value):
        if value=='/variant':return SimpleNamespace(is_dir=lambda:True)
        if value=='/driver/system_campaign_cash_calendar.py':return SimpleNamespace(resolve=lambda:value)
        return Path(value)
    def save(path,value):Path(path).write_bytes(o.encoded(value))
    namespace=dict(Path=source_path,__file__='/driver/system_campaign_cash_calendar.py',os=SimpleNamespace(environ={'FULL_SYSTEM_HOSTED':'1'}),
        need=o.need,save=save,digest=o.digest,asdict=asdict,zipfile=SimpleNamespace(ZipFile=Archive),
        synthetic_inputs=SimpleNamespace(load_actions=load_actions,_archive_rows=archive_rows),synthetic_axis=lambda:dates)
    raw=(CODE/'system_campaign_action_preflight.py').read_bytes();assert o.sha(raw)==o.PREFLIGHT_SHA
    preflight=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef)]
    original=dict(Path=Path,need=o.need,sha=o.sha,digest=o.digest,json=json,re=re,defaultdict=defaultdict)
    exec(compile(ast.fix_missing_locations(ast.Module(body=preflight,type_ignores=[])),'<unchanged-original-collision-input-analysis>','exec'),original)
    namespace.update(analyze_new_catalog=original['analyze_new_catalog'],require_disjoint=original['require_disjoint'])
    raw=(CODE/'system_campaign_2021_completions_facts.py').read_bytes()
    witness=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='require_witness')
    exec(compile(ast.fix_missing_locations(ast.Module(body=[witness],type_ignores=[])),'<unchanged-original-fullrow-predicate>','exec'),namespace)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<unchanged-original-input-hydrator-with-synthetic-source-readers>','exec'),namespace)
    codec=SimpleNamespace(catalog=deepcopy(catalog),rows={},alias_rows=0)
    codec.hydrate=MethodType(namespace['hydrate'],codec)
    return codec,calls

def with_block(*,old=False):
    if old:
        node,=ast.parse(mount_fixture()['original_ordinary_input_with']).body
    else:
        fn=next(n for n in ast.parse(Path(o.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='ordinary_input')
        node=next(n for n in fn.body if isinstance(n,ast.With))
    return node

def run_block(codec,parent,root,tmp_path,*,old=False):
    recorded=[];paths=[];contract=mount_fixture();scratch=tmp_path/'worker-scratch';scratch.mkdir(exist_ok=True)
    def temporary(*,prefix,dir):
        recorded.append(dir)
        if dir in contract['mounts'] and contract['mounts'][dir] is False:
            raise OSError(errno.EROFS,'Read-only file system',dir+'/'+prefix+'synthetic')
        assert dir=='/tmp' and contract['tmpfs'][dir].startswith('rw,')
        obj=tempfile.TemporaryDirectory(prefix=prefix,dir=scratch);paths.append(obj.name);return obj
    fn=ast.FunctionDef(name='run',args=ast.arguments(posonlyargs=[],args=[ast.arg(arg=n) for n in ('codec','collision_parent','root')],kwonlyargs=[],kw_defaults=[],defaults=[]),
        body=[deepcopy(with_block(old=old)),ast.Return(ast.Tuple(elts=[ast.Name(id='private',ctx=ast.Load()),ast.Name(id='collision',ctx=ast.Load())],ctx=ast.Load()))],decorator_list=[])
    scope=dict(tempfile=SimpleNamespace(TemporaryDirectory=temporary),Path=Path,json=json)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<exact-ordinary-tempfile-call-and-hydration-block>','exec'),scope)
    return scope['run'](codec,parent,root),recorded,paths

def test_original_variant_path_reproduces_actual_readonly_failure_before_hydration(tmp_path):
    root,parent,catalog,data=source_input(tmp_path);codec,calls=original_hydrator(catalog,data)
    with pytest.raises(OSError) as error:run_block(codec,parent,root,tmp_path,old=True)
    assert error.value.errno==errno.EROFS and error.value.filename.startswith('/variant/') and calls==[]

def test_existing_tmpfs_path_runs_actual_hydrator_and_random_paths_never_enter_material(tmp_path):
    root,parent,catalog,data=source_input(tmp_path)
    first,calls1=original_hydrator(catalog,data);a,dirs1,paths1=run_block(first,parent,root,tmp_path)
    second,calls2=original_hydrator(catalog,data);b,dirs2,paths2=run_block(second,parent,root,tmp_path)
    assert a==b and dirs1==dirs2==['/tmp'] and paths1!=paths2
    assert all(not Path(path).exists() for path in paths1+paths2)
    serialized=o.encoded(dict(private=a[0],collision=a[1]))
    assert b'compound-ordinary-source-' not in serialized and str(tmp_path).encode() not in serialized
    assert a[1]['retained_ordinary_repairs']==17 and a[1]['status']=='DISJOINT_UNCONSUMED'
    assert a[0]['source_witnesses']==[data['source_observation']] and a[0]['source_metadata_unchanged'] is True
    assert len(calls1)==len(calls2)==2

@pytest.mark.parametrize('bad',['native','row','axis'])
def test_writable_path_keeps_original_native_fullrow_and_calendar_guards(bad,tmp_path):
    root,parent,catalog,data=source_input(tmp_path);codec,calls=original_hydrator(catalog,data,bad=bad)
    with pytest.raises(ValueError):run_block(codec,parent,root,tmp_path)

def test_only_temp_directory_literal_changed_and_original_output_is_not_a_temp_path():
    before=with_block(old=True);after=with_block()
    old_calls=[n for n in ast.walk(before) if isinstance(n,ast.Call) and ast.unparse(n.func)=='tempfile.TemporaryDirectory']
    new_calls=[n for n in ast.walk(after) if isinstance(n,ast.Call) and ast.unparse(n.func)=='tempfile.TemporaryDirectory']
    assert len(old_calls)==len(new_calls)==1
    keyword=next(k for k in old_calls[0].keywords if k.arg=='dir');assert ast.literal_eval(keyword.value)=='/variant';keyword.value=ast.Constant('/tmp')
    assert ast.dump(before,include_attributes=False)==ast.dump(after,include_attributes=False)
    assert all('stock_strategy_shared' not in name and not name.startswith('research.pooled_') for name in sys.modules)
