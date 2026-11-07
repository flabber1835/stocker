"""Host-only alias staging contract. Tiny synthetic asset; no finance/network."""
import ast,csv,hashlib,importlib.util,io,json,os,sys,zipfile
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
P=Path(__file__).parent
C=P.parent
D=Path(os.environ.get('ALIAS_SOURCE_DEPENDENCY_DIR',str(C)))
sha=lambda raw:hashlib.sha256(raw).hexdigest()
digest=lambda v:sha(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
def need(value,code):
    if not value:raise ValueError(code)
def synthetic_rows():
    return json.loads((P/'fixtures/qualified-alias-source.json').read_bytes())['synthetic_rows']
def synthetic_asset():
    text=io.StringIO();writer=csv.DictWriter(text,fieldnames=['date','ticker','name','action','contraticker','contraname','synthetic_fixture']);writer.writeheader();writer.writerows(synthetic_rows())
    binary=io.BytesIO()
    with zipfile.ZipFile(binary,'w',compression=zipfile.ZIP_DEFLATED)as archive:
        info=zipfile.ZipInfo('synthetic.csv',date_time=(2020,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;archive.writestr(info,text.getvalue())
    return binary.getvalue()
class SourceFiles:
    def __truediv__(self,name):
        if name=='system-campaign-sprint-terminal-facts.json':
            value=dict(provider_alias_source=dict(selected_row_sha256=sorted(digest(row)for row in synthetic_rows())),added=dict(security_id='957008674074369745'))
            return SimpleNamespace(read_bytes=lambda:json.dumps(value).encode())
        return D/name


def need(value,code):
    if not value:raise ValueError(code)

class Fence:
    def find_spec(self,name,path=None,target=None):
        if name.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('ALIAS_SOURCE_DATA_ONLY:'+name)

@pytest.fixture(autouse=True)
def fence(monkeypatch):
    guard=Fence();sys.meta_path.insert(0,guard)
    for key,value in [('GITHUB_ACTIONS','true'),('RUNNER_ENVIRONMENT','github-hosted'),('GITHUB_RUN_ATTEMPT','1')]:monkeypatch.setenv(key,value)
    yield
    sys.meta_path.remove(guard)

def module(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def sprint_parser():
    raw=(D/'system_campaign_sprint_facts.py').read_bytes();assert sha(raw)=='1f532038b78a89c1ddac805a786f14cf516707b69ecdad4ef621c1902e93fd3b'
    tree=ast.parse(raw);nodes=[]
    for node in tree.body:
        if isinstance(node,ast.Assign)and any(isinstance(t,ast.Name)and t.id in('ALIAS_BYTES','ALIAS_SHA','ALIAS_URL')for t in node.targets):nodes.append(node)
        if isinstance(node,ast.FunctionDef)and node.name=='alias_rows':nodes.append(node)
    ns=dict(csv=csv,io=io,zipfile=zipfile,sha=sha,digest=digest,need=need)
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<original-alias-parser-input-only>','exec'),ns)
    return ns

def own_spec(n):
    root,outer,completed=n['ROOT_BOUND_ALIAS_SOURCE_PHASES']['P03','2019-09-30']
    return dict(arm='P03',selected_session='2019-09-30',root_admission_sha256=root,outer_sha256=outer,measured_closes=completed)

class Response:
    status=200
    headers={'Content-Encoding':'identity'}
    def __init__(self,raw):self.raw=raw;self.reads=[]
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,limit):self.reads.append(limit);return self.raw[:limit]

def folders(tmp_path):
    old,out=tmp_path/'old',tmp_path/'out';old.mkdir();out.mkdir();return old,out

def test_exact_retained_source_and_original_selected_rows(tmp_path,raw_alias):
    n=namespace();old,out=folders(tmp_path);folder=old/'provider-source';folder.mkdir();(folder/'SHARADAR_ACTIONS.zip').write_bytes(raw_alias)
    n['urlopen']=lambda *a,**k:pytest.fail('retained source must not fetch')
    n['stage_selected_sources'](own_spec(n),old,out)
    assert (out/'provider-source/SHARADAR_ACTIONS.zip').read_bytes()==raw_alias
    proof=json.loads((out/'provider-alias-proof.json').read_bytes())
    assert proof['acquisition']=='EXACT_RETAINED_ORIGINAL' and len(proof['selected_rows'])==4
    assert proof['source_sha256']==n['ALIAS_SHA'] and proof['source_bytes']==n['ALIAS_BYTES']
    assert proof['strategy_metadata_upgraded']is False

def test_missing_source_fetches_exact_original_once(tmp_path,raw_alias):
    n=namespace();old,out=folders(tmp_path);calls=[];response=Response(raw_alias)
    def opened(url,timeout):calls.append((url,timeout));return response
    n['urlopen']=opened;n['stage_selected_sources'](own_spec(n),old,out)
    assert calls==[(n['ALIAS_URL'],60)] and response.reads==[n['ALIAS_BYTES']+1]
    assert sha((out/'provider-source/SHARADAR_ACTIONS.zip').read_bytes())==n['ALIAS_SHA']
    assert json.loads((out/'provider-alias-proof.json').read_bytes())['acquisition']=='EXACT_FROZEN_PUBLIC_OBJECT_FETCHED_ONCE'

@pytest.mark.parametrize('field,value',[('root_admission_sha256','0'*64),('outer_sha256','0'*64),('measured_closes',440),('root_admission_sha256',None)])
def test_foreign_root_refuses_before_any_acquisition(tmp_path,field,value):
    n=namespace();old,out=folders(tmp_path);spec=own_spec(n);spec[field]=value
    n['urlopen']=lambda *a,**k:pytest.fail('foreign root cannot fetch')
    with pytest.raises(ValueError,match='EXACT_QUALIFIED_OWN_ROOT'):n['stage_selected_sources'](spec,old,out)
    assert list(out.iterdir())==[]

def test_foreign_phase_has_no_acquisition(tmp_path):
    n=namespace();old,out=folders(tmp_path);spec=own_spec(n);spec['selected_session']='2019-10-31'
    n['urlopen']=lambda *a,**k:pytest.fail('foreign phase cannot fetch')
    n['stage_selected_sources'](spec,old,out);assert list(out.iterdir())==[]

def test_following_source_still_retained_only(tmp_path):
    n=namespace();old,out=folders(tmp_path);n['urlopen']=lambda *a,**k:pytest.fail('FOLLOWING cannot fetch')
    with pytest.raises(ValueError,match='MUST_BE_RETAINED_NOT_REFETCHED'):n['stage_selected_sources'](dict(arm='P07',selected_session='2020-03-31'),old,out)

def test_bad_retained_source_is_not_refetched_or_parsed(tmp_path):
    n=namespace();old,out=folders(tmp_path);folder=old/'provider-source';folder.mkdir();(folder/'SHARADAR_ACTIONS.zip').write_bytes(b'bad')
    n['urlopen']=lambda *a,**k:pytest.fail('bad retained object cannot refetch')
    n['alias_rows']=lambda *a,**k:pytest.fail('bad retained object cannot parse')
    with pytest.raises(ValueError,match='PROVIDER_BYTES_BEFORE_PARSE'):n['stage_selected_sources'](own_spec(n),old,out)

@pytest.mark.parametrize('field,value',[('GITHUB_ACTIONS','false'),('RUNNER_ENVIRONMENT','self-hosted'),('GITHUB_RUN_ATTEMPT','2')])
def test_original_host_context_guards(tmp_path,monkeypatch,field,value):
    n=namespace();old,out=folders(tmp_path);monkeypatch.setenv(field,value);n['urlopen']=lambda *a,**k:pytest.fail('wrong context cannot fetch')
    with pytest.raises(ValueError,match='HOSTED_ORCHESTRATOR_ONLY'):n['stage_selected_sources'](own_spec(n),old,out)

@pytest.mark.parametrize('status,encoding',[(429,'identity'),(200,'gzip')])
def test_original_response_refusal_once(tmp_path,raw_alias,status,encoding):
    n=namespace();old,out=folders(tmp_path);calls=[];response=Response(raw_alias);response.status=status;response.headers={'Content-Encoding':encoding}
    def opened(*a,**k):calls.append(1);return response
    n['urlopen']=opened
    with pytest.raises(ValueError,match='PINNED_PUBLIC_SOURCE_RESPONSE'):n['stage_selected_sources'](own_spec(n),old,out)
    assert calls==[1] and response.reads==[]

def test_new_root_guard_removal_detected(tmp_path,raw_alias):
    n=namespace();old,out=folders(tmp_path);spec=own_spec(n);spec['root_admission_sha256']='0'*64;n['urlopen']=lambda *a,**k:Response(raw_alias)
    with pytest.raises(ValueError):n['stage_selected_sources'](spec,old,out)
    mutant=namespace(remove='FUTURE_ALIAS_SOURCE_EXACT_QUALIFIED_OWN_ROOT');mutant['urlopen']=lambda *a,**k:Response(raw_alias)
    mutant['stage_selected_sources'](spec,old,out)
    assert sha((out/'provider-source/SHARADAR_ACTIONS.zip').read_bytes())==n['ALIAS_SHA']

def financial_launch_slice():
    tree=ast.parse((C/'system_campaign_financial_resume.py').read_bytes())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='launch')
    branch=next(n.orelse for n in ast.walk(fn)if isinstance(n,ast.If)and any(isinstance(v,ast.Expr)and isinstance(v.value,ast.Call)and isinstance(v.value.func,ast.Name)and v.value.func.id=='stage_selected_sources'for v in n.orelse))
    end=next(i for i,n in enumerate(branch)if isinstance(n,ast.Assign)and any(isinstance(v,ast.Call)and isinstance(v.func,ast.Name)and v.func.id=='worker'and v.args and isinstance(v.args[0],ast.Constant)and v.args[0].value=='economic'for v in ast.walk(n)))
    class Imports(ast.NodeTransformer):
        def visit_ImportFrom(self,n):return None
    selected=Imports().visit(ast.Module(body=deepcopy(branch[:end+1]),type_ignores=[]))
    return ast.fix_missing_locations(selected),fn

def test_failed_stage_cannot_reach_offline_hydration(tmp_path):
    n=namespace();old,out=folders(tmp_path);calls=[]
    def failure(*args,**kwargs):calls.append('host');raise OSError('synthetic source unavailable')
    n['urlopen']=failure;fragment,_=financial_launch_slice()
    with pytest.raises(OSError):exec(compile(fragment,'<actual-host-failed-stage>','exec'),dict(need=need,
        request={'financial_resume_authorized':True},stage_selected_sources=n['stage_selected_sources'],spec=own_spec(n),old=old,out=out,
        receipt={},public=lambda:None,worker=lambda *a,**k:calls.append('worker')))
    assert calls==['host']

@pytest.fixture(scope='session')
def raw_alias():return synthetic_asset()

def namespace(*,remove=None):
    m=module(C/'forecast_tests/test_research_unheld_cash_source.py','portable_alias_input_loader')
    m.C=D;m.FUTURE=C/'system_campaign_financial_future.py';m.CATALOG=C/'system-campaign-selected-own-cash-terminal-facts.json'
    ns=m.load(remove=remove);parser=sprint_parser()
    assert parser['ALIAS_BYTES']==9855560 and parser['ALIAS_SHA']=='db67132dca8cf38107ca4bcaea7276ea5d0e8f77254f6556802caad6efa91b02'
    parser['ALIAS_BYTES']=len(synthetic_asset());parser['ALIAS_SHA']=sha(synthetic_asset())
    ns.update({key:parser[key]for key in ('ALIAS_BYTES','ALIAS_SHA','ALIAS_URL','alias_rows')})
    ns.update(os=os,HERE=SourceFiles());return ns


def test_acquisition_parser_proof_suffix_byte_exact():
    raw=(C/'system_campaign_financial_future.py').read_text()
    fn=ast.get_source_segment(raw,next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef)and n.name=='stage_selected_sources'))
    assert sha(fn[fn.index('    import os\n'):].encode())=='990e864b4dbf32198d48b1ca8189e89f71502fafc165df3cca9870d15f9b7324'


def test_actual_launch_stages_before_actual_hydration_alias_prefix(tmp_path,raw_alias):
    n=namespace();old,out=folders(tmp_path);calls=[]
    n['urlopen']=lambda *a,**k:Response(raw_alias)
    function=next(f for f in ast.parse((C/'system_campaign_financial_future.py').read_bytes()).body if isinstance(f,ast.FunctionDef)and f.name=='hydrate')
    end=next(i for i,node in enumerate(function.body)if isinstance(node,ast.If)and 'SINGLE_PHASES'in ast.unparse(node.test))
    class Imports(ast.NodeTransformer):
        def visit_Import(self,node):return None
        def visit_ImportFrom(self,node):return None
    prefix=deepcopy(function);prefix.name='offline_alias_hydration';prefix.body=prefix.body[:end+1]+[ast.Return(value=ast.Name(id='aliases',ctx=ast.Load()))]
    prefix=Imports().visit(prefix)
    n['selected']=lambda arm,cursor:(SimpleNamespace(catalog={}),None,[])
    exec(compile(ast.fix_missing_locations(ast.Module(body=[prefix],type_ignores=[])),'<actual-hydration-alias-prefix>','exec'),n)
    original_stage=n['stage_selected_sources']
    def stage(spec,old,out):
        original_stage(spec,old,out);calls.append('host_stage')
    def worker(mode,output):
        assert mode=='economic'and output==out;calls.append('offline_hydration')
        aliases=n['offline_alias_hydration'](dict(source_cursor='2019-09-30'),'P03',source_root=out)
        proof=json.loads((out/'provider-alias-proof.json').read_bytes())
        assert aliases==proof['selected_rows'] and (out/'provider-source/SHARADAR_ACTIONS.zip').read_bytes()==raw_alias
        return dict(synthetic_stopped=True)
    fragment,launch=financial_launch_slice()
    exec(compile(fragment,'<actual-host-stage-order>','exec'),dict(need=need,request={'financial_resume_authorized':True},stage_selected_sources=stage,
        spec=own_spec(n),old=old,out=out,receipt={},public=lambda:None,worker=worker))
    assert calls==['host_stage','offline_hydration']
    call=next(v for v in ast.walk(launch)if isinstance(v,ast.Call)and isinstance(v.func,ast.Name)and v.func.id=='seal')
    assert isinstance(call.args[0],ast.Name)and call.args[0].id=='out'
